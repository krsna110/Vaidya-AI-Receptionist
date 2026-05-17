import os
import datetime
import json
import logging

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

    def get_available_slots(self, date: datetime.date, duration_minutes: int = 30) -> list:
        if not self.service:
            return []

        now = datetime.datetime.utcnow().isoformat() + "Z"  # 'Z' indicates UTC time
        end_of_day = datetime.datetime.combine(date, datetime.time(23, 59, 59)).isoformat() + "Z"
        
        # Adjust start time to now if the date is today
        start_time = max(datetime.datetime.combine(date, datetime.time(9, 0, 0)), datetime.datetime.utcnow())
        if start_time.date() != date:
            start_time = datetime.datetime.combine(date, datetime.time(9, 0, 0))
        
        start_time = start_time.isoformat() + "Z"

        try:
            events_result = (
                self.service.events()
                .list(
                    calendarId="primary",
                    timeMin=start_time,
                    timeMax=end_of_day,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
            events = events_result.get("items", [])

            # Define business hours
            BUSINESS_START_HOUR = 9
            BUSINESS_END_HOUR = 18  # 6 PM

            free_slots = []
            current_time = datetime.datetime.combine(date, datetime.time(BUSINESS_START_HOUR, 0, 0))
            
            while current_time.hour < BUSINESS_END_HOUR or \
                  (current_time.hour == BUSINESS_END_HOUR and current_time.minute == 0 and current_time.second == 0):
                slot_end_time = current_time + datetime.timedelta(minutes=duration_minutes)

                # Ensure the slot is within business hours and on the specified date
                if slot_end_time.hour > BUSINESS_END_HOUR or \
                   (slot_end_time.hour == BUSINESS_END_HOUR and (slot_end_time.minute > 0 or slot_end_time.second > 0)):
                    break

                is_slot_free = True
                for event in events:
                    event_start_str = event["start"].get("dateTime", event["start"].get("date"))
                    event_end_str = event["end"].get("dateTime", event["end"].get("date"))

                    event_start = datetime.datetime.fromisoformat(event_start_str.replace('Z', '+00:00'))
                    event_end = datetime.datetime.fromisoformat(event_end_str.replace('Z', '+00:00'))

                    # Check for overlap, considering both fixed slots and manual availability
                    # An event occupies the time if its start is before our slot_end_time and its end is after our current_time
                    if not (event_end <= current_time or event_start >= slot_end_time):
                        is_slot_free = False
                        break
                
                if is_slot_free:
                    free_slots.append(current_time.strftime("%H:%M"))
                
                current_time += datetime.timedelta(minutes=duration_minutes)

            return free_slots
        except HttpError as error:
            print(f"An error occurred while retrieving free slots: {error}")
            return []
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            return []

    def book_appointment(self, patient_name: str, phone: str, start_datetime: datetime.datetime, reason: str) -> str or None:
        if not self.service:
            return None

        end_datetime = start_datetime + datetime.timedelta(minutes=30)

        event = {
            "summary": f"Appointment: {reason} - {patient_name}",
            "location": "Clinic Address Here",  # Placeholder
            "description": f"Patient Phone: {phone}",
            "start": {
                "dateTime": start_datetime.isoformat(),
                "timeZone": "Asia/Kolkata",  # Or appropriate timezone
            },
            "end": {
                "dateTime": end_datetime.isoformat(),
                "timeZone": "Asia/Kolkata",
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
            event = self.service.events().insert(calendarId="primary", body=event).execute()
            print(f"Event created: {event.get('htmlLink')}")
            return event.get("id")
        except HttpError as error:
            print(f"An error occurred while booking the appointment: {error}")
            return None
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
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


