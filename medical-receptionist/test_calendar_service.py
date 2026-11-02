"""Calendar slot calculations tested without Google credentials or network access."""
import os
import unittest
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("JWT_SECRET", "test-only-secret-for-unit-tests")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_ci.db")
os.environ.setdefault("CLINIC_TIMEZONE", "Asia/Kolkata")
os.environ.setdefault("CLINIC_OPEN_HOUR", "9")
os.environ.setdefault("CLINIC_CLOSE_HOUR", "18")
os.environ.setdefault("APPOINTMENT_DURATION_MINUTES", "30")

from calendar_service import GoogleCalendarService


class FakeEvents:
    def __init__(self, events):
        self.items = events
        self.last_query = None

    def list(self, **kwargs):
        self.last_query = kwargs
        return self

    def execute(self):
        return {"items": self.items}


class FakeCalendar:
    def __init__(self, events):
        self.events_api = FakeEvents(events)

    def events(self):
        return self.events_api


class CalendarSlotTests(unittest.TestCase):
    def test_slot_overlap_uses_timezone_aware_event_times(self):
        clinic_tz = ZoneInfo("Asia/Kolkata")
        future_day = datetime.now(clinic_tz).date() + timedelta(days=10)
        service = GoogleCalendarService.__new__(GoogleCalendarService)
        service.calendar_id = "clinic-calendar@example.test"
        service.service = FakeCalendar([{
            "start": {"dateTime": f"{future_day.isoformat()}T10:00:00+05:30"},
            "end": {"dateTime": f"{future_day.isoformat()}T10:30:00+05:30"},
        }])

        slots = service.get_available_slots(future_day)
        self.assertNotIn("10:00", slots)
        self.assertIn("10:30", slots)
        self.assertEqual(service.service.events_api.last_query["calendarId"], "clinic-calendar@example.test")
        self.assertIn("+05:30", service.service.events_api.last_query["timeMin"])

    def test_invalid_clinic_timezone_fails_closed(self):
        service = GoogleCalendarService.__new__(GoogleCalendarService)
        service.calendar_id = "primary"
        service.service = FakeCalendar([])
        previous = os.environ.get("CLINIC_TIMEZONE")
        os.environ["CLINIC_TIMEZONE"] = "Not/A_Timezone"
        try:
            self.assertEqual(service.get_available_slots(date.today()), [])
        finally:
            if previous is None:
                os.environ.pop("CLINIC_TIMEZONE", None)
            else:
                os.environ["CLINIC_TIMEZONE"] = previous


if __name__ == "__main__":
    unittest.main()
