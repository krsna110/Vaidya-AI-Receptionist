import logging
import json
import os
import re
from datetime import datetime, timedelta, date

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.responses import RedirectResponse, FileResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Annotated
from pydantic import BaseModel

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

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
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger(__name__)


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
    today_obj = date.today()
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


def is_confirmation_message(message: str) -> bool:
    text_msg = (message or "").strip().lower()
    confirmations = [
        "yes",
        "confirm",
        "confirmed",
        "yes confirm",
        "yes confirm booking",
        "book it",
        "proceed",
        "done",
    ]
    return any(token in text_msg for token in confirmations)


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
        logger.info(f"Created patient record | id={patient.id} | name={patient.name} | phone={patient.phone_number}")
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
        logger.info(f"Updated patient record | id={patient.id} | name={patient.name} | phone={patient.phone_number}")


def create_appointment_from_booking_data(db: Session, data: dict) -> int | None:
    """Create a confirmed appointment row from collected booking data."""
    name = (data.get("name") or "").strip()
    phone = normalize_phone(data.get("phone") or "")
    appt_date = normalize_booking_date(data.get("date") or "")
    appt_time = (data.get("time") or "").strip()
    reason = (data.get("reason") or "").strip()

    if not (name and phone and appt_date and appt_time and reason):
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
    user_id: str
    message: str


class StateResetRequest(BaseModel):
    user_id: str

# ---------- Create database tables ----------
Base.metadata.create_all(bind=engine)


def ensure_sqlite_schema_upgrades() -> None:
    """Apply lightweight SQLite column upgrades for existing local DBs."""
    required_columns = {
        "date": "VARCHAR",
        "time": "VARCHAR",
        "reason": "VARCHAR",
        "google_event_id": "VARCHAR",
        "reminder_status": "VARCHAR",
        "followup_status": "VARCHAR",
    }
    try:
        with engine.begin() as conn:
            rows = conn.execute(text("PRAGMA table_info(appointments)")).fetchall()
            existing_cols = {row[1] for row in rows}
            for col_name, col_type in required_columns.items():
                if col_name not in existing_cols:
                    conn.execute(text(f"ALTER TABLE appointments ADD COLUMN {col_name} {col_type}"))
                    logger.info(f"DB upgrade applied: added appointments.{col_name}")
    except Exception as e:
        logger.error(f"Failed schema upgrade check for appointments table: {e}", exc_info=True)


ensure_sqlite_schema_upgrades()
logger.info(f"SQLite database URL: {database.SQLALCHEMY_DATABASE_URL}")

# ---------- FastAPI app ----------
app = FastAPI(
    title="Medical AI Receptionist Backend",
    description="Backend for a medical AI receptionist system.",
    version="1.0.0",
)

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
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
def health_check():
    """Health check endpoint to verify the API is running."""
    return {"status": "healthy"}


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
    logger.info(f"State reset for user_id={payload.user_id}")
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
    if form_data.username != "admin" or form_data.password != "password":
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


@app.post("/webhook")
async def webhook_receiver(
    payload: WebhookRequest,
    current_user: auth.TokenData = Depends(auth.get_current_user),
    db: Session = Depends(database.get_db),
):
    """Receives incoming webhook events (e.g., from a messaging platform)."""
    user_id = payload.user_id
    message = payload.message

    # Get current conversation state
    conversation_state = state_manager.get_state(user_id)
    current_state = conversation_state.state

    logger.info(f"User {user_id} | state={current_state} | msg={message!r}")

    # --- Generate AI response with error handling ---
    try:
        agent_response = agent.generate_response(message)
        intent = agent_response.get("intent", "UNKNOWN")
        response_text = agent_response.get("response", "Sorry, something went wrong.")
        data = agent_response.get("data", {})
    except Exception as e:
        logger.error(f"Agent error for user {user_id}: {e}", exc_info=True)
        return {
            "response": "I'm experiencing technical difficulties. Please try again shortly.",
            "intent": "UNKNOWN",
            "state": current_state,
        }

    deterministic_data = extract_booking_details(message)
    booking_states = {"COLLECT_INFO", "SUGGEST_SLOT", "CONFIRM", "BOOKING"}
    if current_state in booking_states and intent in {"GREETING", "FAQ", "UNKNOWN"} and is_booking_message(message, deterministic_data):
        intent = "BOOKING"
    elif intent in {"FAQ", "UNKNOWN"} and is_booking_message(message, deterministic_data):
        intent = "BOOKING"

    if isinstance(data, dict):
        data = {**data, **deterministic_data}
    else:
        data = deterministic_data

    # Merge with existing state data so multi-turn collection is preserved.
    try:
        existing_data = json.loads(conversation_state.data or "{}")
        if not isinstance(existing_data, dict):
            existing_data = {}
    except Exception:
        existing_data = {}
    merged_data = {**existing_data, **(data if isinstance(data, dict) else {})}
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
    new_state = current_state  # Default to current state if no transition

    if intent == "GREETING":
        new_state = "INTENT_DETECT"
    elif current_state == "CONFIRM" and is_confirmation_message(message):
        # Deterministic confirmation guard so booking doesn't get stuck on model variance.
        new_state = "BOOKED"
        try:
            appt_id = create_appointment_from_booking_data(db, merged_data)
            if appt_id:
                merged_data["appointment_id"] = appt_id
                event_id = sync_appointment_to_google_calendar(db, appt_id)
                if event_id:
                    merged_data["google_event_id"] = event_id
                response_text = f"Your appointment is confirmed. Your appointment ID is {appt_id}."
            else:
                new_state = "COLLECT_INFO"
                response_text = "I could not create the appointment. Please choose a different date or time."
        except Exception as e:
            logger.error(f"Appointment creation failed for user {user_id}: {e}", exc_info=True)
            new_state = "COLLECT_INFO"
            response_text = "I could not create the appointment right now. Please try again."
    elif intent == "BOOKING":
        missing_fields = missing_booking_fields(merged_data)
        if current_state in ("GREETING", "INTENT_DETECT", "FAQ", "UNKNOWN", "CANCEL", "CANCELLED", "BOOKED"):
            if missing_fields:
                new_state = "COLLECT_INFO"
                response_text = (
                    "Sure, I can help book your appointment. Please share your "
                    f"{', '.join(missing_fields)}."
                )
            else:
                new_state = "CONFIRM"
                response_text = (
                    "I have your appointment details: "
                    f"{booking_summary(merged_data)}. Should I confirm this booking?"
                )
        elif current_state == "COLLECT_INFO":
            if missing_fields:
                new_state = "COLLECT_INFO"
                response_text = (
                    "Thanks. I still need your "
                    f"{', '.join(missing_fields)} to book the appointment."
                )
            else:
                new_state = "CONFIRM"
                response_text = (
                    "Great, I have your details: "
                    f"{booking_summary(merged_data)}. Should I confirm this booking?"
                )
        elif current_state == "SUGGEST_SLOT":
            new_state = "CONFIRM"
            response_text = (
                "I have your appointment details: "
                f"{booking_summary(merged_data)}. Should I confirm this booking?"
            )
        elif current_state == "CONFIRM":
            if is_confirmation_message(message):
                new_state = "BOOKED"
                try:
                    appt_id = create_appointment_from_booking_data(db, merged_data)
                    if appt_id:
                        merged_data["appointment_id"] = appt_id
                        event_id = sync_appointment_to_google_calendar(db, appt_id)
                        if event_id:
                            merged_data["google_event_id"] = event_id
                        response_text = f"Your appointment is confirmed. Your appointment ID is {appt_id}."
                    else:
                        new_state = "COLLECT_INFO"
                        response_text = "I could not create the appointment. Please choose a different date or time."
                except Exception as e:
                    logger.error(f"Appointment creation failed for user {user_id}: {e}", exc_info=True)
                    new_state = "COLLECT_INFO"
                    response_text = "I could not create the appointment right now. Please try again."
            else:
                new_state = "CONFIRM"
                response_text = "Please reply yes to confirm this appointment, or share any detail you want to change."
    elif intent == "CANCEL":
        appointment_id = extract_appointment_id(merged_data, message)
        if appointment_id:
            appointment = db.query(models.Appointment).filter(models.Appointment.id == appointment_id).first()
            if appointment and appointment.google_event_id and calendar_service is not None:
                try:
                    calendar_service.cancel_appointment(appointment.google_event_id)
                    logger.info(
                        f"Google Calendar event cancel requested | appointment_id={appointment_id} | event_id={appointment.google_event_id}"
                    )
                except Exception as e:
                    logger.warning(
                        f"Google Calendar event cancellation failed | appointment_id={appointment_id}: {e}"
                    )
        if appointment_id and cancel_appointment_record(db, appointment_id):
            new_state = "CANCELLED"
            merged_data["cancelled_appointment_id"] = appointment_id
            response_text = f"Your appointment #{appointment_id} has been cancelled successfully."
        else:
            new_state = "CANCEL"
            response_text = (
                "Please share your appointment ID to cancel (example: appointment 1)."
            )
    elif intent == "FAQ":
        new_state = "FAQ"
    elif intent == "UNKNOWN":
        new_state = "UNKNOWN"

    state_manager.set_state(user_id, new_state, merged_data)

    logger.info(f"User {user_id} | new_state={new_state} | intent={intent}")

    return {"response": response_text, "intent": intent, "state": new_state}
