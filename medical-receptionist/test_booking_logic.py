"""Deterministic unit tests for booking validation and clinic-local calendar slots."""
import unittest
import datetime

from main import (
    normalize_booking_time,
    normalize_phone,
    is_confirmation_message,
    missing_booking_fields,
)
from calendar_service import GoogleCalendarService, CLINIC_TIMEZONE


class BookingValidationTests(unittest.TestCase):
    def test_times_normalize_to_24_hour_format(self):
        self.assertEqual(normalize_booking_time("7 pm"), "19:00")
        self.assertEqual(normalize_booking_time("10:15 AM"), "10:15")
        self.assertEqual(normalize_booking_time("14:30"), "14:30")

    def test_phone_validation_rejects_short_or_long_numbers(self):
        self.assertEqual(normalize_phone("9876543210"), "9876543210")
        self.assertEqual(normalize_phone("1234"), "")
        self.assertEqual(normalize_phone("1" * 20), "")

    def test_confirmation_must_match_the_whole_message(self):
        self.assertTrue(is_confirmation_message("Yes!"))
        self.assertTrue(is_confirmation_message("haan confirm"))
        self.assertFalse(is_confirmation_message("yesterday"))
        self.assertFalse(is_confirmation_message("yes, but I need to change the time"))

    def test_missing_fields_handles_non_string_values(self):
        self.assertEqual(
            missing_booking_fields({"name": 123, "phone": None}),
            ["phone", "date", "time", "reason"],
        )


class FakeEvents:
    def __init__(self, events):
        self._events = events

    def list(self, **kwargs):
        return self

    def execute(self):
        return {"items": self._events}


class FakeCalendar:
    def __init__(self, events):
        self._events = events

    def events(self):
        return FakeEvents(self._events)


class CalendarSlotTests(unittest.TestCase):
    def test_timezone_aware_event_blocks_overlapping_slot(self):
        service = GoogleCalendarService.__new__(GoogleCalendarService)
        service.service = FakeCalendar([{
            "start": {"dateTime": "2099-01-01T09:00:00+05:30"},
            "end": {"dateTime": "2099-01-01T09:30:00+05:30"},
        }])
        slots = service.get_available_slots(datetime.date(2099, 1, 1))
        self.assertNotIn("09:00", slots)
        self.assertIn("09:30", slots)

    def test_all_day_event_blocks_entire_day(self):
        service = GoogleCalendarService.__new__(GoogleCalendarService)
        service.service = FakeCalendar([{
            "start": {"date": "2099-01-01"},
            "end": {"date": "2099-01-02"},
        }])
        self.assertEqual(service.get_available_slots(datetime.date(2099, 1, 1)), [])


if __name__ == "__main__":
    unittest.main()
