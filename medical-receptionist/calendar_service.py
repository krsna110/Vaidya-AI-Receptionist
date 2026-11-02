import os
import datetime
import json
import logging
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

logger = logging.getLogger(__name__)
TOKEN_PATH = os.path.join(BASE_DIR, "token.json")
CLIENT_SECRET_PATH = os.path.join(BASE_DIR, "client_secret.json")

SCOPES = ["https://www.googleapis.com/auth/calendar"]

class GoogleCalendarService:
    def __init__(self):
        self.creds = None
        self.calendar_id = os.getenv("GOOGLE_CALENDAR_ID", "primary").strip() or "primary"
        try:
            self.service = self._authenticate()
        except Exception as e:
            print(f"Calendar not configured: {e}")
            logger.warning(f"Calendar not configured: {e}")
            self.service = None

    def _authenticate(self):
        # Production deployments should use a service account shared with the clinic calendar.
        service_account_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
        if service_account_json:
            try:
                info = json.loads(service_account_json)
                self.creds = service_account.Credentials.from_service_account_info(
                    info, scopes=SCOPES
                )
                return build("calendar", "v3", credentials=self.creds)
            except Exception as exc:
                raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is invalid or cannot initialize Calendar.") from exc

        # Local development may use the desktop OAuth flow and token.json.
        # The file token.json stores the user's access and refresh tokens, and is
        # created automatically when the authorization flow completes for the first
        # time.
        if os.path.exists(TOKEN_PATH):
            self.creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
        # If there are no (valid) credentials available, let the user log in.
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())
            else:
                if os.getenv("GOOGLE_CALENDAR_ALLOW_OAUTH_FLOW", "false").lower() != "true":
                    raise RuntimeError(
                        "token.json not found or invalid. Set GOOGLE_CALENDAR_ALLOW_OAUTH_FLOW=true locally "
                        "to run browser OAuth, or disable calendar sync in deployment."
                    )
                # Ensure client_secret.json is available
                if not os.path.exists(CLIENT_SECRET_PATH):
                    raise FileNotFoundError("client_secret.json not found. Please download it from Google Cloud Console.")
                flow = InstalledAppFlow.from_client_secrets_file(
                    CLIENT_SECRET_PATH, SCOPES
                )
                self.creds = flow.run_local_server(port=0)
            # Save the credentials for the next run
            with open(TOKEN_PATH, "w") as token:
                token.write(self.creds.to_json())
        try:
            service = build("calendar", "v3", credentials=self.creds)
            return service
        except HttpError as error:
            print(f"An error occurred while connecting to Google Calendar: {error}")
            return None

    def get_available_slots(self, date: datetime.date, duration_minutes: int | None = None) -> list[str]:
        """Return free clinic-local slots using timezone-aware Calendar timestamps."""
        if not self.service:
            return []
        timezone_name = os.getenv("CLINIC_TIMEZONE", "Asia/Kolkata")
        try:
            clinic_tz = ZoneInfo(timezone_name)
        except Exception:
            logger.error("Invalid CLINIC_TIMEZONE=%s", timezone_name)
            return []
        duration = duration_minutes or int(os.getenv("APPOINTMENT_DURATION_MINUTES", "30"))
        if duration <= 0 or duration > 240:
            logger.error("Invalid APPOINTMENT_DURATION_MINUTES=%s", duration)
            return []

        try:
            start_hour = int(os.getenv("CLINIC_OPEN_HOUR", "9"))
            end_hour = int(os.getenv("CLINIC_CLOSE_HOUR", "18"))
            if not (0 <= start_hour < end_hour <= 24):
                raise ValueError("Clinic hours must satisfy 0 <= open < close <= 24")

            working_days_raw = os.getenv("CLINIC_WORKING_DAYS", "0,1,2,3,4,5,6")
            working_days = {
                int(value.strip()) for value in working_days_raw.split(",") if value.strip()
            }
            if not working_days or any(day_number < 0 or day_number > 6 for day_number in working_days):
                raise ValueError("CLINIC_WORKING_DAYS must be comma-separated weekday numbers from 0 (Monday) to 6 (Sunday)")
            if date.weekday() not in working_days:
                return []

            holidays = {
                value.strip() for value in os.getenv("CLINIC_HOLIDAYS", "").split(",")
                if value.strip()
            }
            for holiday in holidays:
                datetime.date.fromisoformat(holiday)
            if date.isoformat() in holidays:
                return []

            breaks: list[tuple[datetime.time, datetime.time]] = []
            for raw_break in os.getenv("CLINIC_BREAKS", "").split(","):
                raw_break = raw_break.strip()
                if not raw_break:
                    continue
                start_text, separator, end_text = raw_break.partition("-")
                if not separator:
                    raise ValueError("CLINIC_BREAKS entries must use HH:MM-HH:MM format")
                break_start = datetime.datetime.strptime(start_text.strip(), "%H:%M").time()
                break_end = datetime.datetime.strptime(end_text.strip(), "%H:%M").time()
                if break_start >= break_end:
                    raise ValueError("Each clinic break must end after it starts")
                if break_start < datetime.time(start_hour) or break_end > datetime.time(end_hour):
                    raise ValueError("Clinic breaks must fall within clinic opening hours")
                breaks.append((break_start, break_end))

            day_start = datetime.datetime.combine(date, datetime.time(start_hour), tzinfo=clinic_tz)
            day_end = datetime.datetime.combine(date, datetime.time(end_hour), tzinfo=clinic_tz)
            now = datetime.datetime.now(clinic_tz)
            current_time = day_start
            if date == now.date() and current_time < now:
                elapsed = (now - day_start).total_seconds()
                elapsed_slots = int(elapsed // (duration * 60)) + 1
                current_time = day_start + datetime.timedelta(minutes=elapsed_slots * duration)

            events_result = (
                self.service.events()
                .list(
                    calendarId=self.calendar_id,
                    timeMin=day_start.isoformat(),
                    timeMax=day_end.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
            events = events_result.get("items", [])

            def event_datetime(value: str, is_end: bool = False) -> datetime.datetime:
                if "T" not in value:
                    event_date = datetime.date.fromisoformat(value)
                    return datetime.datetime.combine(event_date, datetime.time.min, tzinfo=clinic_tz)
                parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=clinic_tz)
                return parsed.astimezone(clinic_tz)

            free_slots: list[str] = []
            while current_time + datetime.timedelta(minutes=duration) <= day_end:
                slot_end = current_time + datetime.timedelta(minutes=duration)
                is_free = not any(
                    datetime.datetime.combine(date, break_start, tzinfo=clinic_tz) < slot_end
                    and datetime.datetime.combine(date, break_end, tzinfo=clinic_tz) > current_time
                    for break_start, break_end in breaks
                )
                for event in events:
                    if not is_free:
                        break
                    event_start_raw = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
                    event_end_raw = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date")
                    if not event_start_raw or not event_end_raw:
                        continue
                    event_start = event_datetime(event_start_raw)
                    event_end = event_datetime(event_end_raw, is_end=True)
                    if event_end > current_time and event_start < slot_end:
                        is_free = False
                        break
                if is_free:
                    free_slots.append(current_time.strftime("%H:%M"))
                current_time += datetime.timedelta(minutes=duration)
            return free_slots
        except Exception:
            logger.exception("Failed to calculate available clinic slots")
            return []

    def book_appointment(
        self,
        patient_name: str,
        phone: str,
        start_datetime: datetime.datetime,
        reason: str,
        booking_reference: str | None = None,
    ) -> str | None:
        if not self.service:
            return None

        timezone_name = os.getenv("CLINIC_TIMEZONE", "Asia/Kolkata")
        try:
            clinic_tz = ZoneInfo(timezone_name)
            if start_datetime.tzinfo is None:
                start_datetime = start_datetime.replace(tzinfo=clinic_tz)
            else:
                start_datetime = start_datetime.astimezone(clinic_tz)
            duration = int(os.getenv("APPOINTMENT_DURATION_MINUTES", "30"))
            if duration <= 0 or duration > 240:
                raise ValueError("APPOINTMENT_DURATION_MINUTES must be between 1 and 240")
        except Exception:
            logger.exception("Invalid appointment timezone or duration configuration")
            return None

        end_datetime = start_datetime + datetime.timedelta(minutes=duration)

        # Recover an event created before a process crash or DB commit failure.
        # The private property contains only the internal appointment ID, not PHI.
        if booking_reference:
            try:
                existing = (
                    self.service.events()
                    .list(
                        calendarId=self.calendar_id,
                        privateExtendedProperty=f"vaidya_appointment_id={booking_reference}",
                        maxResults=1,
                        singleEvents=True,
                    )
                    .execute()
                    .get("items", [])
                )
                if existing:
                    return existing[0].get("id")
            except Exception:
                logger.exception("Could not check Calendar for an existing booking reference")
                return None

        clinic_name = os.getenv("CLINIC_NAME", "Clinic").strip() or "Clinic"
        event_body = {
            "summary": f"Appointment at {clinic_name}: {reason} - {patient_name}",
            "location": os.getenv("CLINIC_ADDRESS", "").strip() or None,
            "description": "Patient contact details are stored in the clinic system.",
            "extendedProperties": {
                "private": {"vaidya_appointment_id": str(booking_reference)}
            } if booking_reference else {},
            "start": {"dateTime": start_datetime.isoformat(), "timeZone": timezone_name},
            "end": {"dateTime": end_datetime.isoformat(), "timeZone": timezone_name},
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "popup", "minutes": 10},
                ],
            },
        }
        if not event_body["location"]:
            event_body.pop("location")

        try:
            event = self.service.events().insert(calendarId=self.calendar_id, body=event_body).execute()
            logger.info("Google Calendar event created")
            return event.get("id")
        except HttpError:
            logger.exception("Google Calendar rejected appointment creation")
            return None
        except Exception:
            logger.exception("Unexpected error while creating Google Calendar event")
            return None

    def cancel_appointment(self, event_id: str) -> bool:
        if not self.service:
            return False

        try:
            self.service.events().delete(calendarId=self.calendar_id, eventId=event_id).execute()
            print(f"Event {event_id} cancelled successfully.")
            return True
        except HttpError as error:
            if error.resp.status == 404:
                print(f"Event with ID {event_id} not found.")
            else:
                print(f"An error occurred while cancelling the appointment: {error}")
            return False
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            return False

    def suggest_best_slot(self, date: datetime.date, duration_minutes: int = 30) -> str or None:
        available_slots = self.get_available_slots(date, duration_minutes)
        if available_slots:
            # Return the earliest available slot within business hours
            return available_slots[0]
        return None


if __name__ == '__main__':
    calendar_service = GoogleCalendarService()

    # Example Usage:
    today = datetime.date.today()
    tomorrow = today + datetime.timedelta(days=1)

    print(f"Available slots for today ({today}): {calendar_service.get_available_slots(today)}") # Will only show slots after current time
    print(f"Available slots for tomorrow ({tomorrow}): {calendar_service.get_available_slots(tomorrow)}")

    # To test booking, you'll need to replace these with actual patient data and desired time
    # Ensure client_secret.json is present and authentication is done.
    # try:
    #     # Example booking for tomorrow at 10:00 AM
    #     booking_datetime = datetime.datetime.combine(tomorrow, datetime.time(10, 0, 0))
    #     event_id = calendar_service.book_appointment(
    #         patient_name="John Doe", 
    #         phone="123-456-7890", 
    #         start_datetime=booking_datetime, 
    #         reason="Dental Checkup"
    #     )
    #     print(f"Booked appointment with ID: {event_id}")

    #     if event_id:
    #         # Example cancellation
    #         # print(f"Cancelling appointment with ID {event_id}: {calendar_service.cancel_appointment(event_id)}")
    #         pass
    # except Exception as e:
    #     print(f"Booking/Cancellation test failed: {e}")

    # print(f"Suggested best slot for tomorrow: {calendar_service.suggest_best_slot(tomorrow)}")


