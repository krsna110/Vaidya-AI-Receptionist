import asyncio
import logging
import json
import os
import hashlib
import re
from datetime import datetime, timedelta, date

from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.responses import RedirectResponse, FileResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import text
from passlib.context import CryptContext
from typing import Annotated
from pydantic import BaseModel, Field, model_validator

from dotenv import load_dotenv

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
JWT_SECRET = os.getenv("JWT_SECRET")
if not GEMINI_API_KEY:
    print("WARNING: GEMINI_API_KEY not set")
if not GROQ_API_KEY:
    print("WARNING: GROQ_API_KEY not set")
if not JWT_SECRET:
    print("WARNING: JWT_SECRET not set")

import database
import models
import auth
from agent import Agent
from state import StateManager
from calendar_service import GoogleCalendarService
from scheduler import Scheduler
from database import engine, Base

# ---------- Logging ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def session_log_ref(user_id: str) -> str:
    """Return a stable, non-reversible correlation ID instead of logging patient phone IDs."""
    return hashlib.sha256((user_id or "").encode("utf-8")).hexdigest()[:12]


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
    try:
        from zoneinfo import ZoneInfo
        today_obj = datetime.now(ZoneInfo(os.getenv("CLINIC_TIMEZONE", "Asia/Kolkata"))).date()
    except Exception:
        today_obj = date.today()
    if value == "today":
        return today_obj.isoformat()
    if value in ("tomorrow", "tommorrow"):
        return (today_obj + timedelta(days=1)).isoformat()
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return raw_date.strip()


def normalize_booking_time(raw_time: str) -> str:
    """Normalize common time phrases while keeping them readable."""
    value = (raw_time or "").strip().lower().replace(".", "")
    if not value:
        return ""
    value = re.sub(r"\s+", " ", value)
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*([ap]m)?", value)
    if not match:
        return ""
    hour = int(match.group(1))
    minute = int(match.group(2) or "00")
    meridiem = match.group(3)
    if minute > 59:
        return ""
    if meridiem:
        if hour < 1 or hour > 12:
            return ""
        hour = hour % 12 + (12 if meridiem == "pm" else 0)
    elif hour > 23:
        return ""
    return f"{hour:02d}:{minute:02d}"


def parse_booking_datetime(iso_date: str, time_text: str) -> datetime | None:
    """Parse booking date/time strings into a naive datetime for calendar creation."""
    if not iso_date or not time_text:
        return None
    clean_time = normalize_booking_time(time_text)
    if not clean_time:
        return None
    try:
        time_obj = datetime.strptime(clean_time, "%H:%M").time()
        date_obj = datetime.strptime(iso_date, "%Y-%m-%d").date()
        return datetime.combine(date_obj, time_obj)
    except ValueError:
        return None


def is_confirmation_message(message: str) -> bool:
    """Accept explicit confirmations only; substring matching can book on unrelated words."""
    text_msg = re.sub(r"[^a-z ]", " ", (message or "").strip().lower())
    text_msg = re.sub(r"\s+", " ", text_msg).strip()
    confirmations = {
        "yes", "yes confirm", "yes confirm booking", "confirm", "confirmed",
        "confirm booking", "book it", "proceed", "i confirm", "please confirm",
    }
    return text_msg in confirmations


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

    phone_match = re.search(
        r"(?:\+?\d[\d\s-]{7,}\d)",
        text,
    )
    if phone_match:
        details["phone"] = normalize_phone(phone_match.group(0))

    date_match = re.search(
        r"\b(today|tomorrow|tommorrow|\d{4}-\d{1,2}-\d{1,2})\b",
        lowered,
        re.IGNORECASE,
    )
    if date_match:
        details["date"] = normalize_booking_date(date_match.group(1))

    time_match = re.search(r"\b(\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)?)\b", lowered, re.IGNORECASE)
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


def cancel_appointment_record(db: Session, appointment_id: int) -> bool:
    """Cancel appointment in local DB by ID."""
    appointment = db.query(models.Appointment).filter(models.Appointment.id == appointment_id).first()
    if not appointment:
        return False
    appointment.is_confirmed = False
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
        logger.info("Created patient record | patient_id=%s", patient.id)
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
        logger.info("Updated patient record | patient_id=%s", patient.id)


def create_appointment_from_booking_data(db: Session, data: dict) -> int | None:
    """Create a confirmed appointment row from collected booking data."""
    name = (data.get("name") or "").strip()
    phone = normalize_phone(data.get("phone") or "")
    appt_date = normalize_booking_date(data.get("date") or "")
    appt_time = (data.get("time") or "").strip()
    reason = (data.get("reason") or "").strip()

    if not (name and phone and appt_date and appt_time and reason):
        return None
    if len(name) > 100 or len(reason) > 500 or len(phone) > 16:
        return None
    if not re.fullmatch(r"\+?\d{8,15}", phone):
        return None
    try:
        parsed_date = datetime.strptime(appt_date, "%Y-%m-%d").date()
        normalized_time = normalize_booking_time(appt_time)
        if not normalized_time:
            return None
        appt_time = normalized_time
        from zoneinfo import ZoneInfo
        clinic_now = datetime.now(ZoneInfo(os.getenv("CLINIC_TIMEZONE", "Asia/Kolkata")))
        if parsed_date < clinic_now.date():
            return None
        if parsed_date == clinic_now.date():
            parsed_start = datetime.combine(parsed_date, datetime.strptime(appt_time, "%H:%M").time())
            if parsed_start <= clinic_now.replace(tzinfo=None):
                return None
    except (ValueError, TypeError):
        return None

    patient = db.query(models.Patient).filter(models.Patient.phone_number == phone).first()
    if patient is None and name:
        patient = db.query(models.Patient).filter(models.Patient.name == name).first()
    if patient is None:
        return None

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
        return existing.id

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
        logger.warning(
            f"Slot conflict: date={appt_date} time={appt_time} already booked by appointment_id={slot_conflict.id}"
        )
        return None

    appointment = models.Appointment(
        patient_id=patient.id,
        start_time=datetime.utcnow(),
        end_time=None,
        description=reason,
        is_confirmed=True,
        date=appt_date,
        time=appt_time,
        reason=reason,
    )
    db.add(appointment)
    db.commit()
    db.refresh(appointment)
    logger.info(
        f"Created appointment | id={appointment.id} | patient_id={patient.id} | date={appt_date} | time={appt_time}"
    )
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
    user_id: str | None = Field(default=None, min_length=1, max_length=128)
    session_id: str | None = Field(default=None, min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def ensure_user_identifier(self):
        if not self.user_id and self.session_id:
            self.user_id = self.session_id
        if not self.user_id or not self.user_id.strip():
            raise ValueError("Either user_id or session_id is required")
        if not self.message.strip():
            raise ValueError("Message cannot be empty")
        return self


class StateResetRequest(BaseModel):
    user_id: str

# ---------- Create database tables ----------
Base.metadata.create_all(bind=engine)


def ensure_sqlite_schema_upgrades() -> None:
    """Apply lightweight SQLite column upgrades for existing local DBs."""
    appointment_required_columns = {
        "date": "VARCHAR",
        "time": "VARCHAR",
        "reason": "VARCHAR",
        "google_event_id": "VARCHAR",
        "reminder_status": "VARCHAR",
        "followup_status": "VARCHAR",
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

            conv_rows = conn.execute(text("PRAGMA table_info(conversations)")).fetchall()
            conv_existing_cols = {row[1] for row in conv_rows}
            for col_name, col_type in conversation_required_columns.items():
                if col_name not in conv_existing_cols:
                    conn.execute(text(f"ALTER TABLE conversations ADD COLUMN {col_name} {col_type}"))
                    logger.info(f"DB upgrade applied: added conversations.{col_name}")
    except Exception as e:
        logger.error(f"Failed schema upgrade check: {e}", exc_info=True)


ensure_sqlite_schema_upgrades()
logger.info("Database configured | dialect=%s", engine.dialect.name)

# Optional one-time admin bootstrap. Credentials are supplied only through the
# deployment environment; the plaintext password is never stored.
def bootstrap_admin_user() -> None:
    username = os.getenv("ADMIN_USERNAME", "").strip()
    password = os.getenv("ADMIN_PASSWORD", "")
    if not username or not password:
        logger.warning("Admin bootstrap skipped; set ADMIN_USERNAME and ADMIN_PASSWORD to create the first admin.")
        return
    if len(password) < 12:
        raise RuntimeError("ADMIN_PASSWORD must be at least 12 characters.")
    db = database.SessionLocal()
    try:
        existing_user = db.query(models.User).filter(models.User.username == username).first()
        if existing_user:
            return
        db.add(models.User(
            username=username,
            email=f"{username}@localhost.invalid",
            hashed_password=auth.hash_password(password),
        ))
        db.commit()
        logger.warning("Bootstrapped initial admin account from environment configuration.")
    finally:
        db.close()


bootstrap_admin_user()

# ---------- FastAPI app ----------
app = FastAPI(
    title="Medical AI Receptionist Backend",
    description="Backend for a medical AI receptionist system.",
    version="1.0.0",
)

# Rate limiter is initialized before route decorators use it.
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    # Never log request headers: they can contain bearer tokens and API credentials.
    response = await call_next(request)
    logger.info(
        "HTTP request completed | method=%s path=%s status=%s",
        request.method,
        request.url.path,
        response.status_code,
    )
    return response

# Mount Static Files (directory relative to CWD which is medical-receptionist/)
app.mount("/static", StaticFiles(directory="static"), name="static")

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
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

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


@app.get("/chat")
def serve_chat():
    """Serve the chat HTML UI directly."""
    return FileResponse("static/chat.html")


@app.get("/admin")
def serve_admin():
    """Serve the admin dashboard UI."""
    return FileResponse("static/admin.html")


@app.get("/appointments")
async def get_all_appointments(
    current_user: auth.TokenData = Depends(auth.get_current_user),
    db: Session = Depends(database.get_db),
):
    appointments = db.query(models.Appointment).all()
    return appointments


@app.post("/appointments/{appointment_id}/cancel")
async def cancel_appointment(
    appointment_id: int,
    current_user: auth.TokenData = Depends(auth.get_current_user),
    db: Session = Depends(database.get_db),
):
    """Cancel an appointment through the authenticated admin API."""
    appointment = db.query(models.Appointment).filter(models.Appointment.id == appointment_id).first()
    if appointment is None:
        raise HTTPException(status_code=404, detail="Appointment not found.")
    if not appointment.is_confirmed:
        return {"status": "already_cancelled", "appointment_id": appointment_id}

    if appointment.google_event_id:
        if calendar_service is None:
            raise HTTPException(status_code=503, detail="Calendar service is unavailable; appointment was not changed.")
        if not calendar_service.cancel_appointment(appointment.google_event_id):
            raise HTTPException(status_code=502, detail="Google Calendar cancellation failed; appointment was not changed.")

    appointment.is_confirmed = False
    db.add(appointment)
    db.commit()
    return {"status": "cancelled", "appointment_id": appointment_id}


@app.get("/patients")
async def get_all_patients(
    current_user: auth.TokenData = Depends(auth.get_current_user),
    db: Session = Depends(database.get_db),
):
    patients = db.query(models.Patient).all()
    return patients


@app.post("/state/reset")
async def reset_user_state(
    payload: StateResetRequest,
    current_user: auth.TokenData = Depends(auth.get_current_user),
):
    state_manager.reset_state(payload.user_id)
    logger.info("Conversation state reset | session_ref=%s", session_log_ref(payload.user_id))
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
@limiter.limit("5/minute")
async def login_for_access_token(
    request: Request,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Session = Depends(database.get_db),
):
    """Authenticate a database-backed user and return a short-lived JWT."""
    user = db.query(models.User).filter(models.User.username == form_data.username).first()
    if not user or not auth.verify_password(form_data.password, user.hashed_password):
        # Keep the response identical for unknown usernames and bad passwords.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = auth.create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


@app.post("/webhook")
@limiter.limit("10/minute")
async def webhook_receiver(
    request: Request,
    payload: WebhookRequest,
    db: Session = Depends(database.get_db),
):
    """Receives incoming webhook events (e.g., from a messaging platform)."""
    user_id = payload.user_id
    message = (payload.message or "").strip()[:500]
    if not message:
        return {"response": "Please send a message", "intent": "UNKNOWN"}

    # Get current conversation state
    conversation_state = state_manager.get_state(user_id)
    current_state = conversation_state.state

    logger.info("Webhook received | session_ref=%s", session_log_ref(user_id))
    logger.info("Webhook message received | state=%s | message_length=%s", current_state, len(message))

    # Fetch last 6 messages for conversation history
    conversation_history = [
        {"role": ((conv.sender_type or conv.speaker or "user").lower()), "content": conv.message}
        for conv in db.query(models.Conversation)
        .filter(models.Conversation.session_id == user_id)
        .order_by(models.Conversation.timestamp.asc())
        .limit(6)
        .all()
    ]

    # Public chat is intentionally unauthenticated for browser clients. Keep it
    # bounded and rate-limited; use a server-side gateway/WAF for stronger abuse
    # controls because CORS is not authentication.
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
        state_manager.set_state(user_id, current_state, {**conversation_state.data, "name": extracted_name})
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
        known_name = (conversation_state.data or {}).get("name")
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
        logger.error("Agent error | session_ref=%s | error_type=%s", session_log_ref(user_id), type(e).__name__, exc_info=True)
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
        logger.error("Failed to save conversation history | session_ref=%s", session_log_ref(user_id), exc_info=True)

    # Extract patient data using the new agent method
    extracted_patient_data = await asyncio.to_thread(agent.extract_patient_data, message, conversation_history)
    logger.info("Patient data extraction completed")

    # Merge LLM extracted data with deterministic data
    deterministic_data = extract_booking_details(message)
    if isinstance(data, dict):
        data = {**data, **deterministic_data, **extracted_patient_data}
    else:
        data = {**deterministic_data, **extracted_patient_data}

    booking_states = {"COLLECT_INFO", "SUGGEST_SLOT", "CONFIRM", "BOOKING"}
    if current_state in booking_states and intent in {"GREETING", "FAQ", "UNKNOWN"} and is_booking_message(message, data):
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

    # Apply normalizations to merged data
    if merged_data.get("date"):
        merged_data["date"] = normalize_booking_date(merged_data.get("date"))
    if merged_data.get("time"):
        merged_data["time"] = normalize_booking_time(merged_data.get("time"))
    if merged_data.get("phone"):
        merged_data["phone"] = normalize_phone(merged_data.get("phone"))

    try:
        upsert_patient_from_data(db, merged_data)
    except Exception as e:
        logger.error(f"Patient upsert failed for user {user_id}: {e}", exc_info=True)

    # Update conversation state based on intent and current state
    new_state = current_state

    if current_state == "CONFIRM" and is_confirmation_message(message):
        try:
            appt_id = create_appointment_from_booking_data(db, merged_data)
            if appt_id:
                merged_data["appointment_id"] = appt_id
                event_id = sync_appointment_to_google_calendar(db, appt_id)
                if event_id:
                    merged_data["google_event_id"] = event_id
                    appointment = db.query(models.Appointment).filter(models.Appointment.id == appt_id).first()
                    if appointment:
                        appointment.is_confirmed = True
                        db.commit()
                    new_state = "BOOKED"
                    response_text = f"Your appointment is confirmed. Your appointment ID is {appt_id}."
                else:
                    appointment = db.query(models.Appointment).filter(models.Appointment.id == appt_id).first()
                    if appointment:
                        appointment.is_confirmed = False
                        db.commit()
                    new_state = "COLLECT_INFO"
                    response_text = (
                        "I saved your appointment request, but could not confirm it with the clinic calendar. "
                        "Please contact the clinic before visiting."
                    )
            else:
                new_state = "COLLECT_INFO"
                response_text = "I could not reserve that slot. Please choose a different date or time."
        except Exception as e:
            db.rollback()
            logger.error("Appointment creation failed | session_id=%s | error_type=%s", user_id, type(e).__name__)
            new_state = "COLLECT_INFO"
            response_text = "I could not create the appointment right now. Please try again."
    elif current_state == "CONFIRM" and re.sub(r"[^a-z ]", " ", message.lower()).strip() in {
        "no", "no thanks", "not now", "change it", "cancel", "do not confirm"
    }:
        new_state = "COLLECT_INFO"
        response_text = "No problem. Tell me which appointment detail you would like to change."
    elif intent == "GREETING":
        new_state = "INTENT_DETECT"
    elif intent == "BOOKING":
        missing_fields = missing_booking_fields(merged_data)
        if "name" in missing_fields:
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

    logger.info("Conversation updated | session_ref=%s | new_state=%s | intent=%s", session_log_ref(user_id), new_state, intent)

    return {
        "response": response_text,
        "intent": intent,
        "state": new_state,
        "confidence": confidence,
        "language": language,
        "session_id": user_id,
    }
