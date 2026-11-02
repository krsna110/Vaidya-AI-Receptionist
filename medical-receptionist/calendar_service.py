import os
import datetime
import json
import logging
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
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

CLINIC_TIMEZONE = ZoneInfo(os.getenv("CLINIC_TIMEZONE", "Asia/Kolkata"))
CLINIC_OPEN_TIME = datetime.time.fromisoformat(os.getenv("CLINIC_OPEN_TIME", "09:00"))
CLINIC_CLOSE_TIME = datetime.time.fromisoformat(os.getenv("CLINIC_CLOSE_TIME", "18:00"))
APPOINTMENT_DURATION_MINUTES = int(os.getenv("APPOINTMENT_DURATION_MINUTES", "30"))
CLINIC_ADDRESS = os.getenv("CLINIC_ADDRESS", "").strip()

if CLINIC_OPEN_TIME >= CLINIC_CLOSE_TIME:
    raise ValueError("CLINIC_OPEN_TIME must be earlier than CLINIC_CLOSE_TIME")
if APPOINTMENT_DURATION_MINUTES < 5 or APPOINTMENT_DURATION_MINUTES > 240:
    raise ValueError("APPOINTMENT_DURATION_MINUTES must be between 5 and 240")


def _calendar_datetime(value: str, all_day: bool = False) -> datetime.datetime:
    """Parse Google Calendar event times into aware clinic-local datetimes."""
    if all_day:
        parsed_date = datetime.date.fromisoformat(value[:10])
        return datetime.datetime.combine(parsed_date, datetime.time.min, tzinfo=CLINIC_TIMEZONE)
    parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=CLINIC_TIMEZONE)
    return parsed.astimezone(CLINIC_TIMEZONE)

class GoogleCalendarService:
    def __init__(self):
        self.creds = None
        try:
            self.service = self._authenticate()
        except Exception as e:
            print(f"Calendar not configured: {e}")
            logger.warning(f"Calendar not configured: {e}")
            self.service = None

    def _authenticate(self):
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

    def get_available_slots(self, date: datetime.date, duration_minutes: int | None = None) -> list:
        """Return clinic-local slots that do not overlap existing calendar events."""
        if not self.service:
            return []
        duration = duration_minutes or APPOINTMENT_DURATION_MINUTES
        if duration < 5 or duration > 240:
            raise ValueError("duration_minutes must be between 5 and 240")

        now = datetime.datetime.now(CLINIC_TIMEZONE)
        if date < now.date():
            return []
        day_start = datetime.datetime.combine(date, CLINIC_OPEN_TIME, tzinfo=CLINIC_TIMEZONE)
        day_end = datetime.datetime.combine(date, CLINIC_CLOSE_TIME, tzinfo=CLINIC_TIMEZONE)
        query_start = max(day_start, now) if date == now.date() else day_start
        if query_start >= day_end:
            return []

        try:
            events_result = (
                self.service.events()
                .list(
                    calendarId="primary",
                    timeMin=query_start.isoformat(),
                    timeMax=day_end.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
            events = []
            for event in events_result.get("items", []):
                start_value = event.get("start", {})
                end_value = event.get("end", {})
                start_raw = start_value.get("dateTime") or start_value.get("date")
                end_raw = end_value.get("dateTime") or end_value.get("date")
                if not start_raw or not end_raw:
                    continue
                events.append((
                    _calendar_datetime(start_raw, "dateTime" not in start_value),
                    _calendar_datetime(end_raw, "dateTime" not in end_value),
                ))

            free_slots = []
            current = day_start
            step = datetime.timedelta(minutes=duration)
            while current + step <= day_end:
                slot_end = current + step
                if current >= query_start and all(
                    event_end <= current or event_start >= slot_end
                    for event_start, event_end in events
                ):
                    free_slots.append(current.strftime("%H:%M"))
                current += step
            return free_slots
        except HttpError:
            logger.exception("Google Calendar failed while retrieving available slots")
            return []
        except Exception:
            logger.exception("Unexpected error while calculating available slots")
            return []

    def book_appointment(self, patient_name: str, phone: str, start_datetime: datetime.datetime, reason: str) -> str | None:
        if not self.service:
            return None

        if start_datetime.tzinfo is None:
            start_datetime = start_datetime.replace(tzinfo=CLINIC_TIMEZONE)
        else:
            start_datetime = start_datetime.astimezone(CLINIC_TIMEZONE)
        end_datetime = start_datetime + datetime.timedelta(minutes=APPOINTMENT_DURATION_MINUTES)

        event = {
            "summary": f"Appointment: {reason} - {patient_name}",
            "location": CLINIC_ADDRESS or None,
            "description": f"Appointment reason: {reason}",
            "start": {
                "dateTime": start_datetime.isoformat(),
                "timeZone": CLINIC_TIMEZONE.key,
            },
            "end": {
                "dateTime": end_datetime.isoformat(),
                "timeZone": CLINIC_TIMEZONE.key,
            },
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "email", "minutes": 24 * 60},
                    {"method": "popup", "minutes": 10},
                ],
            },
        }

        try:
            created = self.service.events().insert(calendarId="primary", body=event).execute()
            logger.info("Google Calendar event created for appointment")
            return created.get("id")
        except HttpError:
            logger.exception("Google Calendar failed while booking an appointment")
            return None
        except Exception:
            logger.exception("Unexpected error while booking an appointment")
            return None

    def cancel_appointment(self, event_id: str) -> bool:
        if not self.service:
            return False

        try:
            self.service.events().delete(calendarId="primary", eventId=event_id).execute()
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


