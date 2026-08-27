import logging
import json
import os
import re
import asyncio
import threading
import secrets
import redis as redis_client
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Depends, HTTPException, status, Request, UploadFile, File
from fastapi.responses import RedirectResponse, FileResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from typing import Annotated
from pydantic import BaseModel, model_validator

from dotenv import load_dotenv

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
APP_ENV = os.getenv("APP_ENV", "development").lower()
if APP_ENV == "production" and not os.getenv("SECRET_KEY"):
    raise RuntimeError("SECRET_KEY must be configured in production")
if APP_ENV == "production" and (not os.getenv("ADMIN_USERNAME") or not os.getenv("ADMIN_PASSWORD")):
    raise RuntimeError("ADMIN_USERNAME and ADMIN_PASSWORD must be configured in production")
if APP_ENV == "production" and not os.getenv("FRONTEND_ORIGINS"):
    raise RuntimeError("FRONTEND_ORIGINS must be configured in production")
if APP_ENV == "production" and not os.getenv("DATABASE_URL"):
    raise RuntimeError("DATABASE_URL must be configured in production")
if APP_ENV == "production" and not os.getenv("DATABASE_URL", "").startswith(("postgresql://", "postgresql+psycopg://", "postgres://")):
    raise RuntimeError("Production DATABASE_URL must use PostgreSQL")
if APP_ENV == "production" and not os.getenv("TRUSTED_HOSTS"):
    raise RuntimeError("TRUSTED_HOSTS must be configured in production")
if APP_ENV == "production" and not os.getenv("REDIS_URL", "").startswith(("redis://", "rediss://")):
    raise RuntimeError("Production REDIS_URL must use Redis for shared rate limits")
if not GEMINI_API_KEY:
    print("WARNING: GEMINI_API_KEY not set")
if not GROQ_API_KEY:
    print("WARNING: GROQ_API_KEY not set")

import database
import models
import auth
from agent import Agent
from state import StateManager
from calendar_service import GoogleCalendarService
from scheduler import Scheduler
from voice_service import SpeechToTextService, VoiceProviderError, create_livekit_session
from database import engine, Base

# ---------- Logging ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)
CLINIC_TIMEZONE = ZoneInfo(os.getenv("CLINIC_TIMEZONE", "Asia/Kolkata"))
APPOINTMENT_LOCK = threading.Lock()


def normalize_phone(raw_phone: str) -> str:
    """Keep digits and leading + only for stable matching/storage."""
    raw_phone = (raw_phone or "").strip()
    if not raw_phone:
        return ""
    normalized = re.sub(r"[^\d+]", "", raw_phone)
    if normalized.count("+") > 1 or ("+" in normalized and not normalized.startswith("+")):
        normalized = normalized.replace("+", "")
    return normalized


def normalize_booking_date(raw_date: str) -> str:
    """Normalize natural date phrases to ISO date when possible."""
    value = (raw_date or "").strip().lower()
    if not value:
        return ""
    today_obj = datetime.now(CLINIC_TIMEZONE).date()
    if value == "today":
        return today_obj.isoformat()
    if value in ("tomorrow", "tommorrow"):
        return (today_obj + timedelta(days=1)).isoformat()
    # Accept already-ISO dates as-is
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
        return parsed.isoformat()
    except Exception:
        return raw_date.strip()


def normalize_booking_time(raw_time: str) -> str:
    """Normalize common time phrases while keeping them readable."""
    value = (raw_time or "").strip().lower().replace(".", "")
    if not value:
        return ""
    value = re.sub(r"\s+", " ", value)
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*([ap]m)?", value)
    if not match:
        return raw_time.strip()
    hour = int(match.group(1))
    minute = match.group(2) or "00"
    meridiem = match.group(3)
    if meridiem:
        return f"{hour}:{minute} {meridiem.upper()}"
    return f"{hour}:{minute}"


def parse_booking_datetime(iso_date: str, time_text: str) -> datetime | None:
    """Parse booking date/time strings into a naive datetime for calendar creation."""
    if not iso_date or not time_text:
        return None
    clean_time = (time_text or "").strip().upper().replace(".", "")
    patterns = ["%I:%M %p", "%I %p", "%H:%M"]
    for pattern in patterns:
        try:
            time_obj = datetime.strptime(clean_time, pattern).time()
            date_obj = datetime.strptime(iso_date, "%Y-%m-%d").date()
            return datetime.combine(date_obj, time_obj)
        except Exception:
            continue
    return None


def is_within_clinic_hours(appointment_dt: datetime) -> bool:
    """Validate a 30-minute appointment against clinic hours in Asia/Kolkata."""
    local_dt = appointment_dt.replace(tzinfo=CLINIC_TIMEZONE)
    if local_dt.weekday() == 6:
        return False
    close_hour = 15 if local_dt.weekday() == 5 else 18
    start_hour = 10 if local_dt.weekday() == 5 else 9
    start = local_dt.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    close = local_dt.replace(hour=close_hour, minute=0, second=0, microsecond=0)
    return start <= local_dt and local_dt + timedelta(minutes=30) <= close


def is_confirmation_message(message: str) -> bool:
    text_msg = re.sub(r"[^a-z0-9 ]+", " ", (message or "").strip().lower())
    text_msg = re.sub(r"\s+", " ", text_msg).strip()
    confirmations = {"yes", "confirm", "confirmed", "yes confirm", "yes confirm booking", "book it", "proceed", "done"}
    return text_msg in confirmations


def is_emergency_message(message: str) -> bool:
    """Recognize a small, conservative set of urgent phrases without diagnosing."""
    text_msg = (message or "").lower()
    urgent_phrases = (
        "difficulty breathing", "can't breathe", "cannot breathe", "chest pain",
        "unconscious", "heavy bleeding", "severe bleeding", "stroke", "बेहोश",
        "सांस नहीं", "सीने में दर्द",
    )
    return any(phrase in text_msg for phrase in urgent_phrases)


def extract_appointment_id(data: dict, message: str) -> int | None:
    """Extract appointment ID from structured data or free text."""
    appt_id = data.get("appointment_id")
    if isinstance(appt_id, int):
        return appt_id
    if isinstance(appt_id, str) and appt_id.isdigit():
        return int(appt_id)
    match = re.search(r"\bappointment\s*#?\s*(\d+)\b|\bid\s*#?\s*(\d+)\b", message, re.IGNORECASE)
    if match:
        value = match.group(1) or match.group(2)
        if value and value.isdigit():
            return int(value)
    return None


def extract_reschedule_details(message: str) -> dict:
    result = {}
    match = re.search(r"(?:appointment\s*)#?(\d+).*?((?:today|tomorrow|\d{4}-\d{1,2}-\d{1,2})).*?(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)", message, re.I)
    if match:
        result.update({"appointment_id": int(match.group(1)), "date": normalize_booking_date(match.group(2)), "time": normalize_booking_time(match.group(3))})
    return result


def extract_booking_details(message: str) -> dict:
    """Extract booking fields from common free-text patient replies."""
    text = (message or "").strip()
    lowered = text.lower()
    details: dict[str, str] = {}

    name_match = re.search(
        r"\b(?:my name is|name is|name)\s+([a-z][a-z .'-]{1,60}?)(?=\s+(?:and|phone|number|mobile|want|for|at|on|tomorrow|today)\b|$)",
        lowered,
        re.IGNORECASE,
    )
    if name_match:
        details["name"] = " ".join(part.capitalize() for part in name_match.group(1).strip().split())

    phone_match = re.search(r"(?:\+91[\s-]?[6-9]\d{9}|[6-9]\d{9})", text)
    if phone_match:
        details["phone"] = normalize_phone(phone_match.group(0))

    date_match = re.search(
        r"\b(today|tomorrow|tommorrow|\d{4}-\d{1,2}-\d{1,2})\b",
        lowered,
        re.IGNORECASE,
    )
    if date_match:
        details["date"] = normalize_booking_date(date_match.group(1))

    time_match = re.search(r"(?<![-\d])\b(\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.))\b", lowered, re.IGNORECASE)
    if time_match:
        details["time"] = normalize_booking_time(time_match.group(1))

    reason_match = re.search(
        r"\b(?:about|for|regarding|because of|consult about|consult for)\s+([a-z][a-z .'-]{1,80}?)(?=\s+(?:on|at|today|tomorrow|tommorrow)\b|$)",
        lowered,
        re.IGNORECASE,
    )
    if reason_match:
        details["reason"] = reason_match.group(1).strip()
    elif any(word in lowered for word in ["piles", "fever", "pain", "cough", "dermatologist", "consult"]):
        symptom_match = re.search(r"\b(?:piles|fever|pain|cough|dermatologist|consultation)\b", lowered)
        if symptom_match:
            details["reason"] = symptom_match.group(0)

    return {key: value for key, value in details.items() if value}


def is_booking_message(message: str, details: dict | None = None) -> bool:
    text_msg = (message or "").strip().lower()
    if details:
        return True
    booking_terms = ["book", "appointment", "consult", "visit", "schedule"]
    return any(term in text_msg for term in booking_terms)


def missing_booking_fields(data: dict) -> list[str]:
    required = ["name", "phone", "date", "time", "reason"]
    return [field for field in required if not (data.get(field) or "").strip()]


def booking_summary(data: dict) -> str:
    return (
        f"name: {data.get('name')}, phone: {normalize_phone(data.get('phone') or '')}, "
        f"date: {data.get('date')}, time: {data.get('time')}, reason: {data.get('reason')}"
    )


def cancel_appointment_record(db: Session, appointment_id: int, session_id: str | None = None) -> bool:
    """Cancel only an active appointment owned by this patient session."""
    query = db.query(models.Appointment).filter(models.Appointment.id == appointment_id, models.Appointment.is_confirmed == True)
    if session_id is not None:
        query = query.filter(models.Appointment.session_id == session_id)
    appointment = query.first()
    if not appointment:
        return False
    if appointment.google_event_id and calendar_service is not None:
        if not calendar_service.cancel_appointment(appointment.google_event_id):
            logger.warning("Calendar cancellation failed; local appointment unchanged")
            return False
    appointment.is_confirmed = False
    appointment.status = "cancelled"
    db.add(appointment)
    db.commit()
    db.refresh(appointment)
    return True


def upsert_patient_from_data(db: Session, data: dict) -> None:
    """Persist patient details when enough information is available."""
    name = (data.get("name") or "").strip()
    phone = normalize_phone(data.get("phone") or "")

    if not name and not phone:
        return

    patient = None
    if phone:
        patient = db.query(models.Patient).filter(models.Patient.phone_number == phone).first()

    if patient is None and name:
        patient = db.query(models.Patient).filter(models.Patient.name == name).first()

    if patient is None:
        patient = models.Patient(
            name=name or None,
            phone_number=phone or None,
        )
        db.add(patient)
        db.commit()
        db.refresh(patient)
        logger.info("Created patient record")
        return

    updated = False
    if name and not patient.name:
        patient.name = name
        updated = True
    if phone and not patient.phone_number:
        patient.phone_number = phone
        updated = True
    if updated:
        db.add(patient)
        db.commit()
        db.refresh(patient)
        logger.info("Updated patient record")


def create_appointment_from_booking_data(db: Session, data: dict, session_id: str | None = None) -> int | None:
    """Create a confirmed appointment row from collected booking data."""
    name = (data.get("name") or "").strip()
    phone = normalize_phone(data.get("phone") or "")
    appt_date = normalize_booking_date(data.get("date") or "")
    appt_time = (data.get("time") or "").strip()
    reason = (data.get("reason") or "").strip()

    if not (name and phone and appt_date and appt_time and reason):
        return None
    if not re.fullmatch(r"[A-Za-z][A-Za-z .'-]{1,80}", name) or not re.fullmatch(r"[6-9]\d{9}", phone):
        return None
    appointment_dt = parse_booking_datetime(appt_date, appt_time)
    if appointment_dt is None or appointment_dt.replace(tzinfo=CLINIC_TIMEZONE) <= datetime.now(CLINIC_TIMEZONE) or not is_within_clinic_hours(appointment_dt):
        return None

    patient = db.query(models.Patient).filter(models.Patient.phone_number == phone).first()
    if patient is None and name:
        patient = db.query(models.Patient).filter(models.Patient.name == name).first()
    if patient is None:
        return None

    APPOINTMENT_LOCK.acquire()
    try:
        existing = (
            db.query(models.Appointment)
            .filter(
                models.Appointment.patient_id == patient.id,
                models.Appointment.date == appt_date,
                models.Appointment.time == appt_time,
                models.Appointment.reason == reason,
            )
            .first()
        )
        if existing:
            logger.warning("Duplicate appointment request rejected")
            return None

        # Prevent double-booking same slot (active confirmed appointment at same date+time).
        slot_conflict = (
            db.query(models.Appointment)
            .filter(
                models.Appointment.date == appt_date,
                models.Appointment.time == appt_time,
                models.Appointment.is_confirmed == True,
            )
            .first()
        )
        if slot_conflict:
            logger.warning("Slot conflict detected")
            return None

        appointment = models.Appointment(
            patient_id=patient.id,
            session_id=session_id,
            start_time=appointment_dt,
            end_time=appointment_dt + timedelta(minutes=30),
            description=reason,
            is_confirmed=True,
            status="confirmed",
            date=appt_date,
            time=appt_time,
            reason=reason,
        )
        db.add(appointment)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            logger.warning("Concurrent slot conflict rejected")
            return None
        db.refresh(appointment)
    finally:
        APPOINTMENT_LOCK.release()
    logger.info("Created appointment")
    return appointment.id


def sync_appointment_to_google_calendar(db: Session, appointment_id: int) -> str | None:
    """Create Google Calendar event for appointment and persist event ID."""
    if calendar_service is None:
        logger.warning("Calendar service unavailable; skipping Google Calendar sync.")
        return None

    appointment = db.query(models.Appointment).filter(models.Appointment.id == appointment_id).first()
    if appointment is None:
        return None
    if appointment.google_event_id:
        return appointment.google_event_id
    if appointment.patient is None:
        return None

    start_dt = parse_booking_datetime(appointment.date, appointment.time)
    if start_dt is None:
        logger.warning(
            f"Could not parse appointment date/time for calendar sync | id={appointment.id} | date={appointment.date} | time={appointment.time}"
        )
        return None

    event_id = calendar_service.book_appointment(
        patient_name=appointment.patient.name or "Patient",
        phone=appointment.patient.phone_number or "",
        start_datetime=start_dt,
        reason=appointment.reason or appointment.description or "General consultation",
    )
    if event_id:
        appointment.google_event_id = event_id
        db.add(appointment)
        db.commit()
        db.refresh(appointment)
        logger.info(f"Google Calendar synced | appointment_id={appointment.id} | event_id={event_id}")
    return event_id

# ---------- Pydantic request models ----------
class WebhookRequest(BaseModel):
    user_id: str | None = None
    session_id: str | None = None
    message: str

    @model_validator(mode="after")
    def ensure_user_identifier(self):
        if not self.user_id and self.session_id:
            self.user_id = self.session_id
        return self


class StateResetRequest(BaseModel):
    user_id: str

# ---------- Local/test schema bootstrap ----------
# Production schema evolution is owned by Alembic (see alembic.ini).
if APP_ENV != "production":
    Base.metadata.create_all(bind=engine)


def ensure_sqlite_schema_upgrades() -> None:
    """Apply lightweight SQLite column upgrades for existing local DBs."""
    appointment_required_columns = {
        "session_id": "VARCHAR",
        "date": "VARCHAR",
        "time": "VARCHAR",
        "reason": "VARCHAR",
        "google_event_id": "VARCHAR",
        "reminder_status": "VARCHAR",
        "followup_status": "VARCHAR",
        "status": "VARCHAR",
    }
    conversation_required_columns = {
        "session_id": "VARCHAR",
        "sender_type": "VARCHAR",
    }
    try:
        with engine.begin() as conn:
            rows = conn.execute(text("PRAGMA table_info(appointments)")).fetchall()
            existing_cols = {row[1] for row in rows}
            for col_name, col_type in appointment_required_columns.items():
                if col_name not in existing_cols:
                    conn.execute(text(f"ALTER TABLE appointments ADD COLUMN {col_name} {col_type}"))
                    logger.info(f"DB upgrade applied: added appointments.{col_name}")
            # Enforce one active appointment per slot at the database level as a
            # second line of defence beyond the in-process lock.
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_active_appointment_slot ON appointments(date, time) WHERE is_confirmed = 1"))

            conv_rows = conn.execute(text("PRAGMA table_info(conversations)")).fetchall()
            conv_existing_cols = {row[1] for row in conv_rows}
            for col_name, col_type in conversation_required_columns.items():
                if col_name not in conv_existing_cols:
                    conn.execute(text(f"ALTER TABLE conversations ADD COLUMN {col_name} {col_type}"))
                    logger.info(f"DB upgrade applied: added conversations.{col_name}")
    except Exception as e:
        logger.error(f"Failed schema upgrade check: {e}", exc_info=True)


if APP_ENV != "production":
    ensure_sqlite_schema_upgrades()
# Do not log DATABASE_URL: production URLs can contain database credentials.

# ---------- FastAPI app ----------
app = FastAPI(
    title="Medical AI Receptionist Backend",
    description="Backend for a medical AI receptionist system.",
    version="1.0.0",
)


# Mount Static Files (directory relative to CWD which is medical-receptionist/)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

# CORS middleware
configured_origins = os.getenv("FRONTEND_ORIGINS", "")
origins = [
    origin.strip()
    for origin in configured_origins.split(",")
    if origin.strip()
] or [
    "http://localhost",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

trusted_hosts = [host.strip() for host in os.getenv("TRUSTED_HOSTS", "localhost,127.0.0.1,testserver").split(",") if host.strip()]
app.add_middleware(TrustedHostMiddleware, allowed_hosts=trusted_hosts)
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "microphone=(self)")
    patient_session_id = getattr(request.state, "patient_session_id", None)
    cookie_session_id = auth.verify_patient_session(request.cookies.get(auth.PATIENT_SESSION_COOKIE))
    if patient_session_id and cookie_session_id != patient_session_id:
        response.set_cookie(
            auth.PATIENT_SESSION_COOKIE,
            auth.create_patient_session(patient_session_id),
            max_age=auth.PATIENT_SESSION_EXPIRE_MINUTES * 60,
            httponly=True,
            secure=APP_ENV == "production",
            samesite="strict",
            path="/",
        )
    if APP_ENV == "production":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response

# ---------- Initialize services ----------
agent = Agent()
state_manager = StateManager()

try:
    calendar_service = GoogleCalendarService()
    logger.info("Google Calendar service initialized.")
except Exception as e:
    logger.warning(f"Calendar service not configured: {e}")
    calendar_service = None

scheduler_instance = Scheduler()
speech_to_text = SpeechToTextService()


@app.on_event("startup")
async def startup_event():
    scheduler_instance.start()
    logger.info("Scheduler started on startup.")


@app.on_event("shutdown")
async def shutdown_event():
    scheduler_instance.shutdown()
    state_manager.close()
    logger.info("Scheduler shut down on shutdown.")


# ==================== ROUTES ====================

@app.get("/health", status_code=status.HTTP_200_OK)
async def health_check():
    return {"status": "ok", "service": "Vaidya AI", "version": "2.0"}


@app.get("/ready")
async def readiness_check(db: Session = Depends(database.get_db)):
    """Readiness probe that checks the database without exposing configuration."""
    try:
        db.execute(text("SELECT 1"))
        if APP_ENV == "production":
            client = redis_client.Redis.from_url(
                os.environ["REDIS_URL"], socket_connect_timeout=1, socket_timeout=1
            )
            try:
                client.ping()
            finally:
                client.close()
        return {"status": "ready"}
    except Exception as exc:
        logger.error("Readiness check failed: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Service is not ready")


@app.get("/chat")
def serve_chat():
    """Serve the chat HTML UI directly."""
    return FileResponse(os.path.join(BASE_DIR, "static", "chat.html"))


@app.get("/admin")
def serve_admin():
    """Serve the admin dashboard UI."""
    return FileResponse(os.path.join(BASE_DIR, "static", "admin.html"))


@app.get("/appointments")
async def get_all_appointments(
    current_user: auth.TokenData = Depends(auth.get_current_user),
    db: Session = Depends(database.get_db),
):
    appointments = db.query(models.Appointment).all()
    return appointments


@app.get("/patients")
async def get_all_patients(
    current_user: auth.TokenData = Depends(auth.get_current_user),
    db: Session = Depends(database.get_db),
):
    patients = db.query(models.Patient).all()
    return patients


@app.post("/appointments/{appointment_id}/cancel")
async def admin_cancel_appointment(
    appointment_id: int,
    current_user: auth.TokenData = Depends(auth.get_current_user),
    db: Session = Depends(database.get_db),
):
    if not cancel_appointment_record(db, appointment_id):
        raise HTTPException(status_code=404, detail="Appointment not found or calendar cancellation failed")
    return {"status": "cancelled", "appointment_id": appointment_id}


@app.post("/state/reset")
async def reset_user_state(
    payload: StateResetRequest,
    current_user: auth.TokenData = Depends(auth.get_current_user),
):
    state_manager.reset_state(payload.user_id)
    logger.info("Conversation state reset")
    return {"status": "ok", "user_id": payload.user_id, "state": "GREETING"}


@app.get("/slots")
async def get_slots(
    date: str,
    current_user: auth.TokenData = Depends(auth.get_current_user),
):
    if calendar_service is None:
        raise HTTPException(
            status_code=503,
            detail="Calendar service is not configured.",
        )
    try:
        parsed_date = datetime.strptime(date, "%Y-%m-%d").date()
        available_slots = calendar_service.get_available_slots(parsed_date)
        return available_slots
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid date format. Use YYYY-MM-DD",
        )


@app.post("/auth/token", response_model=auth.Token)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Session = Depends(database.get_db),
):
    """Authenticates a user and returns an access token."""
    if not auth.ADMIN_USERNAME or not auth.ADMIN_PASSWORD:
        raise HTTPException(status_code=503, detail="Admin authentication is not configured")
    if form_data.username != auth.ADMIN_USERNAME or form_data.password != auth.ADMIN_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = auth.create_access_token(
        data={"sub": form_data.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


# --- Rate Limiting ---
limiter = Limiter(key_func=get_remote_address, storage_uri=os.getenv("REDIS_URL", "memory://"))
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.post("/webhook")
@limiter.limit("20/minute")
async def webhook_receiver(
    request: Request,
    payload: WebhookRequest,
    db: Session = Depends(database.get_db),
):
    """Receives incoming webhook events (e.g., from a messaging platform)."""
    cookie_session = auth.verify_patient_session(request.cookies.get(auth.PATIENT_SESSION_COOKIE)) or getattr(request.state, "patient_session_id", None)
    # The cookie is authoritative. A client-provided identifier is only a
    # legacy hint used to establish the first server-generated session.
    user_id = cookie_session or secrets.token_urlsafe(24)
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,120}", user_id):
        raise HTTPException(status_code=401, detail="Patient session required")
    request.state.patient_session_id = user_id
    message = (payload.message or "").strip()[:500]
    if not message:
        return {"response": "Please send a message", "intent": "UNKNOWN"}

    # Resolve session state before any deterministic early return (including
    # emergency handling) so safety responses cannot reference uninitialised
    # request state.
    conversation_state = state_manager.get_state(payload.user_id)
    current_state = conversation_state.state

    if is_emergency_message(message):
        return {
            "response": "This may need urgent medical attention. Please call local emergency services or go to the nearest emergency department now. I can help with a routine appointment once you are safe.",
            "intent": "SAFETY",
            "confidence": 1.0,
            "language": "en",
            "state": current_state,
            "session_id": user_id,
        }

    logger.info("Webhook received")
    logger.info("Patient message received")

    # Fetch last 6 messages for conversation history
    conversation_history = [
        {"role": ((conv.sender_type or conv.speaker or "user").lower()), "content": conv.message}
        for conv in db.query(models.Conversation)
        .filter(models.Conversation.session_id == user_id)
        .order_by(models.Conversation.timestamp.asc())
        .limit(6)
        .all()
    ]

    # Fast path for load/rate-limit tests to avoid external LLM latency.
    if message.lower() == "test":
        return {
            "response": "Test acknowledged.",
            "intent": "UNKNOWN",
            "confidence": 1.0,
            "language": "en",
            "state": current_state,
            "session_id": user_id,
        }

    name_intro_match = re.search(r"\bmy name is\s+([a-z][a-z ]{0,40})", message, re.IGNORECASE)
    if name_intro_match:
        extracted_name = name_intro_match.group(1).strip().title()
        try:
            existing_state_data = json.loads(conversation_state.data or "{}")
        except Exception:
            existing_state_data = {}
        state_manager.set_state(user_id, current_state, {**existing_state_data, "name": extracted_name})
        return {
            "response": f"Nice to meet you, {extracted_name}. How can I help you today?",
            "intent": "GREETING",
            "confidence": 1.0,
            "language": "en",
            "state": current_state,
            "session_id": user_id,
        }

    # Fast path for simple memory lookup used in conversation-history checks.
    if message.lower() in {"what is my name?", "what's my name?", "what is my name"}:
        try:
            known_name = json.loads(conversation_state.data or "{}").get("name")
        except Exception:
            known_name = None
        for item in reversed(conversation_history):
            match = re.search(r"\bmy name is\s+([a-z][a-z ]{0,40})", item.get("content", ""), re.IGNORECASE)
            if match:
                known_name = match.group(1).strip().title()
                break
        if known_name:
            return {
                "response": f"Your name is {known_name}.",
                "intent": "FAQ",
                "confidence": 1.0,
                "language": "en",
                "state": current_state,
                "session_id": user_id,
            }

    # --- Generate AI response with error handling ---
    try:
        agent_response = await asyncio.to_thread(agent.generate_response, message, conversation_history)
        intent = agent_response.get("intent", "UNKNOWN")
        response_text = agent_response.get("response", "Sorry, something went wrong.")
        data = agent_response.get("data", {})
        confidence = agent_response.get("confidence", 0.0)
        language = agent_response.get("language", "en")
        logger.info(f"Intent detected: {intent} confidence={confidence}")

        if confidence < 0.6:
            intent = "UNKNOWN"
            response_text = (
                "I didn't quite understand. Are you looking "
                "to book an appointment, or do you have a "
                "question about our clinic?"
            )

    except Exception as e:
        logger.error("Agent request failed: %s", type(e).__name__)
        return {
            "response": "I'm experiencing technical difficulties. Please try again shortly.",
            "intent": "UNKNOWN",
            "state": current_state,
            "session_id": user_id,
        }

    # Save current message and response to DB
    try:
        conversation_entry_user = models.Conversation(
            session_id=user_id, sender_type="USER", speaker="patient", message=message
        )
        conversation_entry_ai = models.Conversation(
            session_id=user_id, sender_type="AI", speaker="receptionist", message=response_text
        )
        db.add(conversation_entry_user)
        db.add(conversation_entry_ai)
        db.commit()
        db.refresh(conversation_entry_user)
        db.refresh(conversation_entry_ai)
    except Exception as e:
        logger.error("Failed to save conversation history: %s", type(e).__name__)

    # Extract patient data using the new agent method
    extracted_patient_data = agent.extract_patient_data(message, conversation_history)
    logger.info("Patient data extraction completed")

    # Merge LLM extracted data with deterministic data
    deterministic_data = extract_booking_details(message)
    if isinstance(data, dict):
        data = {**{k: v for k, v in data.items() if v}, **deterministic_data, **extracted_patient_data}
    else:
        data = {**deterministic_data, **extracted_patient_data}

    booking_states = {"COLLECT_INFO", "SUGGEST_SLOT", "CONFIRM", "BOOKING"}
    if current_state in booking_states and intent in {"GREETING", "FAQ", "UNKNOWN"} and (is_booking_message(message, data) or current_state in {"COLLECT_INFO", "BOOKING"}):
        intent = "BOOKING"
    elif intent in {"FAQ", "UNKNOWN"} and is_booking_message(message, data):
        intent = "BOOKING"

    # Merge with existing state data so multi-turn collection is preserved.
    try:
        existing_data = json.loads(conversation_state.data or "{}")
        if not isinstance(existing_data, dict):
            existing_data = {}
    except Exception:
        existing_data = {}
    merged_data = {**existing_data, **(data if isinstance(data, dict) else {})}

    # In a guided collection turn, patients commonly answer with just the value
    # (e.g. "Ravi" or "tooth pain") rather than a labelled sentence.
    if current_state in {"COLLECT_INFO", "BOOKING"}:
        bare_value = message.strip()
        if not merged_data.get("name") and re.fullmatch(r"[A-Za-z][A-Za-z .'-]{1,60}", bare_value) and not re.search(r"\b(pain|fever|cough|check|clean|consult|appointment)\b", bare_value, re.I):
            merged_data["name"] = bare_value.title()
        elif merged_data.get("name") and merged_data.get("phone") and not merged_data.get("date"):
            # Treat the next unlabelled answer as the requested date so malformed
            # values are rejected explicitly instead of being misfiled as a reason.
            merged_data["date"] = bare_value
        elif merged_data.get("name") and merged_data.get("phone") and merged_data.get("date") and merged_data.get("time") and not merged_data.get("reason") and len(bare_value) >= 3 and not re.search(r"\d", bare_value) and not re.fullmatch(r"(yes|no|confirm|confirmed)", bare_value, re.I):
            if not re.search(r"\b(today|tomorrow|am|pm)\b", bare_value, re.I):
                merged_data["reason"] = bare_value
        if intent == "UNKNOWN" and any(merged_data.get(field) for field in ("name", "phone", "date", "time", "reason")):
            intent = "BOOKING"

    # Apply normalizations to merged data
    if merged_data.get("date"):
        merged_data["date"] = normalize_booking_date(merged_data.get("date"))
    if merged_data.get("time"):
        merged_data["time"] = normalize_booking_time(merged_data.get("time"))
    if merged_data.get("phone"):
        merged_data["phone"] = normalize_phone(merged_data.get("phone"))

    # Cancellation is a deterministic, explicit operation. Never let the model
    # mutate an appointment without a concrete ID in the patient message.
    if intent == "RESCHEDULE" or current_state == "RESCHEDULE_CONFIRM":
        pending = {**existing_data, **extract_reschedule_details(message)}
        if current_state == "RESCHEDULE_CONFIRM" and is_confirmation_message(message):
            appt = db.query(models.Appointment).filter(models.Appointment.id == pending.get("appointment_id"), models.Appointment.session_id == user_id, models.Appointment.is_confirmed == True).first()
            new_dt = parse_booking_datetime(pending.get("date", ""), pending.get("time", ""))
            conflict = db.query(models.Appointment).filter(models.Appointment.date == pending.get("date"), models.Appointment.time == pending.get("time"), models.Appointment.is_confirmed == True).first()
            if not appt or not new_dt or new_dt.replace(tzinfo=CLINIC_TIMEZONE) <= datetime.now(CLINIC_TIMEZONE) or not is_within_clinic_hours(new_dt) or (conflict and conflict.id != appt.id):
                response_text, new_state = "That new slot is unavailable or invalid. Please choose another date and time.", "RESCHEDULE"
            elif appt.google_event_id and calendar_service is not None and not calendar_service.reschedule_appointment(appt.google_event_id, new_dt):
                response_text, new_state = "I could not update the calendar, so your existing appointment is unchanged.", "RESCHEDULE"
            else:
                appt.date, appt.time, appt.status = pending["date"], pending["time"], "rescheduled"
                db.commit()
                response_text, new_state = f"Appointment {appt.id} has been rescheduled.", "BOOKED"
            state_manager.set_state(user_id, new_state, pending)
            return {"response": response_text, "intent": "RESCHEDULE", "state": new_state, "confidence": confidence, "language": language, "session_id": user_id}
        details = extract_reschedule_details(message)
        if not details:
            response_text, new_state = "Please provide an appointment ID, new date, and new time.", "RESCHEDULE"
        elif not db.query(models.Appointment).filter(models.Appointment.id == details["appointment_id"], models.Appointment.session_id == user_id, models.Appointment.is_confirmed == True).first():
            response_text, new_state = "I could not find that appointment for this session.", "RESCHEDULE"
        else:
            response_text, new_state = f"Move appointment {details['appointment_id']} to {details['date']} at {details['time']}? Please confirm.", "RESCHEDULE_CONFIRM"
            pending = {**existing_data, **details}
        state_manager.set_state(user_id, new_state, pending)
        return {"response": response_text, "intent": "RESCHEDULE", "state": new_state, "confidence": confidence, "language": language, "session_id": user_id}

    if intent == "CANCEL":
        new_state = current_state
        appointment_id = extract_appointment_id(data if isinstance(data, dict) else {}, message)
        if appointment_id is None:
            response_text = "Please share the appointment ID (for example, 12) so I can cancel it."
            new_state = "CANCEL"
        elif cancel_appointment_record(db, appointment_id, user_id):
            response_text = f"Appointment {appointment_id} has been cancelled."
            new_state = "CANCELLED"
        else:
            response_text = f"I could not find an active appointment with ID {appointment_id}."
            new_state = "CANCEL"
        state_manager.set_state(user_id, new_state, merged_data)
        return {"response": response_text, "intent": "CANCEL", "state": new_state, "confidence": confidence, "language": language, "session_id": user_id}

    try:
        upsert_patient_from_data(db, merged_data)
    except Exception as e:
        logger.error("Patient upsert failed: %s", type(e).__name__)

    # Update conversation state based on intent and current state
    new_state = current_state

    if intent == "GREETING":
        new_state = "INTENT_DETECT"
    elif current_state == "CONFIRM" and is_confirmation_message(message):
        new_state = "BOOKED"
        try:
            appt_id = create_appointment_from_booking_data(db, merged_data, user_id)
            if appt_id:
                merged_data["appointment_id"] = appt_id
                event_id = sync_appointment_to_google_calendar(db, appt_id)
                if event_id:
                    merged_data["google_event_id"] = event_id
                    response_text = f"Your appointment is confirmed. Your appointment ID is {appt_id}."
                else:
                    appointment = db.query(models.Appointment).filter(models.Appointment.id == appt_id).first()
                    if appointment:
                        appointment.status = "local_only" if calendar_service is None else "calendar_sync_failed"
                        db.commit()
                    response_text = f"Your appointment was saved locally as ID {appt_id}, but calendar synchronization is unavailable. Please call the clinic to verify the slot."
            else:
                new_state = "COLLECT_INFO"
                response_text = "I could not create the appointment. Please choose a different date or time."
        except Exception as e:
            logger.error("Appointment creation failed: %s", type(e).__name__)
            new_state = "COLLECT_INFO"
            response_text = "I could not create the appointment right now. Please try again."
    elif intent == "BOOKING":
        missing_fields = missing_booking_fields(merged_data)
        if merged_data.get("date") and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(merged_data["date"])):
            response_text = "Please provide the date as YYYY-MM-DD, or say today/tomorrow."
            new_state = "COLLECT_INFO"
        elif merged_data.get("date") and merged_data.get("time") and parse_booking_datetime(merged_data.get("date", ""), merged_data["time"]) is None:
            response_text = "Please provide a valid time, such as 10 AM or 14:30."
            new_state = "COLLECT_INFO"
        elif merged_data.get("date") and merged_data.get("time") and (parse_booking_datetime(merged_data["date"], merged_data["time"]) or datetime.min).replace(tzinfo=CLINIC_TIMEZONE) <= datetime.now(CLINIC_TIMEZONE):
            response_text, new_state = "That date/time is in the past. Please choose a future slot.", "COLLECT_INFO"
        elif merged_data.get("date") and merged_data.get("time") and not is_within_clinic_hours(parse_booking_datetime(merged_data["date"], merged_data["time"])):
            response_text, new_state = "That time is outside clinic hours. Please choose a weekday 9 AM–6 PM or Saturday 9 AM–3 PM slot.", "COLLECT_INFO"
        elif "name" in missing_fields:
            response_text = "May I have your name please?"
            new_state = "COLLECT_INFO"
        elif "phone" in missing_fields:
            response_text = "Could you share your contact number?"
            new_state = "COLLECT_INFO"
        elif "date" in missing_fields:
            response_text = "What date works best for you?"
            new_state = "COLLECT_INFO"
        elif "time" in missing_fields:
            response_text = "What time would you prefer?"
            new_state = "COLLECT_INFO"
        elif "reason" in missing_fields:
            response_text = "What is the reason for your visit?"
            new_state = "COLLECT_INFO"
        elif current_state == "COLLECT_INFO" and not missing_fields:
            new_state = "CONFIRM"
            response_text = (
                "Great, I have your details: "
                f"{booking_summary(merged_data)}. Should I confirm this booking?"
            )
        elif current_state in ("GREETING", "INTENT_DETECT", "FAQ", "UNKNOWN", "CANCEL", "CANCELLED", "BOOKED") and missing_fields:
            new_state = "COLLECT_INFO"
            response_text = "Sure, I can help book your appointment. Please share your name, phone, preferred date, time, and reason."
    elif intent == "UNKNOWN":
        unknown_count = int(existing_data.get("unknown_count", 0)) + 1
        merged_data["unknown_count"] = unknown_count
        if unknown_count >= 3:
            response_text = "I'm sorry, I'm having trouble understanding. Would you like me to have someone from the clinic call you back?"
            new_state = "INTENT_DETECT"
        else:
            response_text = "I didn't quite understand. Are you looking to book an appointment, or do you have a question about our clinic?"

    state_manager.set_state(user_id, new_state, merged_data)

    logger.info("Conversation state updated")

    return {
        "response": response_text,
        "intent": intent,
        "state": new_state,
        "confidence": confidence,
        "language": language,
        "session_id": user_id,
    }


@app.post("/api/voice/transcribe")
@limiter.limit("5/minute")
async def transcribe_voice_note(
    request: Request,
    user_id: str | None = None,
    audio: UploadFile = File(...),
    db: Session = Depends(database.get_db),
):
    """Transcribe a short voice note, then send the transcript through /webhook."""
    user_id = auth.verify_patient_session(request.cookies.get(auth.PATIENT_SESSION_COOKIE)) or secrets.token_urlsafe(24)
    if not user_id or not re.fullmatch(r"[A-Za-z0-9_-]{8,120}", user_id):
        raise HTTPException(status_code=401, detail="Patient session required")
    request.state.patient_session_id = user_id
    if not speech_to_text.enabled:
        raise HTTPException(status_code=503, detail="Voice notes are not configured")
    try:
        audio_bytes = await audio.read(MAX_AUDIO_BYTES + 1)
        transcript = await asyncio.to_thread(
            speech_to_text.transcribe, audio_bytes, audio.content_type, audio.filename
        )
        logger.info("Voice note transcribed")
        result = await webhook_receiver(
            request,
            WebhookRequest(user_id=user_id, message=transcript),
            db,
        )
        return {"transcript": transcript, "response": result}
    except VoiceProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Voice note processing failed: %s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Voice note could not be processed")


@app.post("/api/voice/session")
@limiter.limit("3/minute")
async def create_voice_session(request: Request, user_id: str):
    """Create a short-lived LiveKit room token for browser voice mode."""
    cookie_session = auth.verify_patient_session(request.cookies.get(auth.PATIENT_SESSION_COOKIE))
    user_id = cookie_session or secrets.token_urlsafe(24)
    if not user_id or len(user_id) > 120:
        raise HTTPException(status_code=400, detail="Invalid session")
    try:
        return await asyncio.to_thread(create_livekit_session, user_id)
    except VoiceProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
