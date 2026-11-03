"""Calendar slot calculations tested without Google credentials or network access."""
import os
import json
import hashlib
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import Mock
from googleapiclient.errors import HttpError
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
    def __init__(self, events, delete_error=None, insert_error=None, items_after_insert_error=None):
        self.items = events
        self.delete_error = delete_error
        self.insert_error = insert_error
        self.items_after_insert_error = items_after_insert_error
        self.last_query = None
        self.last_list_query = None
        self.last_deleted_event_id = None
        self.last_insert_body = None
        self.operation = "list"

    def list(self, **kwargs):
        self.operation = "list"
        self.last_query = kwargs
        self.last_list_query = kwargs
        return self

    def delete(self, **kwargs):
        self.operation = "delete"
        self.last_deleted_event_id = kwargs.get("eventId")
        self.last_query = kwargs
        return self

    def insert(self, **kwargs):
        self.operation = "insert"
        self.last_insert_body = kwargs
        return self

    def execute(self):
        if self.operation == "delete":
            if self.delete_error is not None:
                raise self.delete_error
            return {}
        if self.operation == "insert":
            if self.insert_error is not None:
                if self.items_after_insert_error is not None:
                    self.items = self.items_after_insert_error
                raise self.insert_error
            return {"id": "created-calendar-event"}
        return {"items": self.items}


class FakeCalendar:
    def __init__(self, events, delete_error=None, insert_error=None, items_after_insert_error=None):
        self.events_api = FakeEvents(
            events,
            delete_error=delete_error,
            insert_error=insert_error,
            items_after_insert_error=items_after_insert_error,
        )

    def events(self):
        return self.events_api


class CalendarSlotTests(unittest.TestCase):
    def test_cancelling_already_deleted_calendar_event_is_idempotent(self):
        service = GoogleCalendarService.__new__(GoogleCalendarService)
        service.calendar_id = "clinic-calendar@example.test"
        not_found = HttpError(Mock(status=404), b"event not found")
        service.service = FakeCalendar([], delete_error=not_found)

        self.assertTrue(service.cancel_appointment("already-deleted-event"))
        self.assertEqual(
            service.service.events_api.last_deleted_event_id,
            "already-deleted-event",
        )

    def test_calendar_cancellation_failure_other_than_not_found_is_not_ignored(self):
        service = GoogleCalendarService.__new__(GoogleCalendarService)
        service.calendar_id = "clinic-calendar@example.test"
        forbidden = HttpError(Mock(status=403), b"permission denied")
        service.service = FakeCalendar([], delete_error=forbidden)

        self.assertFalse(service.cancel_appointment("event-with-permission-error"))

    def test_cancellation_recovers_calendar_event_by_booking_reference(self):
        service = GoogleCalendarService.__new__(GoogleCalendarService)
        service.calendar_id = "clinic-calendar@example.test"
        service.service = FakeCalendar([{"id": "orphan-event-id"}])

        self.assertTrue(service.cancel_appointment_by_reference("appointment-456"))
        self.assertEqual(
            service.service.events_api.last_list_query["privateExtendedProperty"],
            "vaidya_appointment_id=appointment-456",
        )
        self.assertEqual(
            service.service.events_api.last_deleted_event_id,
            "orphan-event-id",
        )

    def test_cancellation_by_booking_reference_is_idempotent_when_event_is_missing(self):
        service = GoogleCalendarService.__new__(GoogleCalendarService)
        service.calendar_id = "clinic-calendar@example.test"
        service.service = FakeCalendar([])

        self.assertTrue(service.cancel_appointment_by_reference("appointment-without-event"))

    def test_past_date_returns_no_available_slots_without_calendar_query(self):
        service = GoogleCalendarService.__new__(GoogleCalendarService)
        service.calendar_id = "clinic-calendar@example.test"
        service.service = FakeCalendar([])
        yesterday = datetime.now(ZoneInfo("Asia/Kolkata")).date() - timedelta(days=1)

        self.assertEqual(service.get_available_slots(yesterday), [])
        self.assertIsNone(service.service.events_api.last_list_query)

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

    def test_calendar_booking_reference_recovers_existing_event(self):
        service = GoogleCalendarService.__new__(GoogleCalendarService)
        service.calendar_id = "clinic-calendar@example.test"
        service.service = FakeCalendar([{"id": "existing-event-id"}])

        event_id = service.book_appointment(
            patient_name="Test Patient",
            phone="+919876543210",
            start_datetime=datetime(2098, 12, 29, 11, 30),
            reason="retry test",
            booking_reference="appointment-123",
        )
        self.assertEqual(event_id, "existing-event-id")
        self.assertEqual(
            service.service.events_api.last_query["privateExtendedProperty"],
            "vaidya_appointment_id=appointment-123",
        )

    def test_direct_calendar_booking_rejects_a_busy_slot_before_insert(self):
        clinic_tz = ZoneInfo("Asia/Kolkata")
        slot_date = date(2098, 12, 30)
        service = GoogleCalendarService.__new__(GoogleCalendarService)
        service.calendar_id = "clinic-calendar@example.test"
        service.service = FakeCalendar([{
            "start": {"dateTime": f"{slot_date.isoformat()}T10:00:00+05:30"},
            "end": {"dateTime": f"{slot_date.isoformat()}T10:30:00+05:30"},
        }])

        result = service.book_appointment(
            patient_name="Test Patient",
            phone="+919876543210",
            start_datetime=datetime.combine(slot_date, datetime.strptime("10:00", "%H:%M").time(), tzinfo=clinic_tz),
            reason="busy slot regression",
        )

        self.assertIsNone(result)
        self.assertIsNone(service.service.events_api.last_insert_body)

    def test_direct_calendar_booking_rejects_outside_clinic_hours(self):
        clinic_tz = ZoneInfo("Asia/Kolkata")
        slot_date = date(2098, 12, 30)
        service = GoogleCalendarService.__new__(GoogleCalendarService)
        service.calendar_id = "clinic-calendar@example.test"
        service.service = FakeCalendar([])

        result = service.book_appointment(
            patient_name="Test Patient",
            phone="+919876543210",
            start_datetime=datetime.combine(slot_date, datetime.strptime("08:30", "%H:%M").time(), tzinfo=clinic_tz),
            reason="outside hours regression",
        )

        self.assertIsNone(result)
        self.assertIsNone(service.service.events_api.last_insert_body)

    def test_calendar_event_omits_patient_identifiers_and_visit_reason(self):
        clinic_tz = ZoneInfo("Asia/Kolkata")
        slot_date = date(2098, 12, 30)
        service = GoogleCalendarService.__new__(GoogleCalendarService)
        service.calendar_id = "clinic-calendar@example.test"
        service.service = FakeCalendar([])

        event_id = service.book_appointment(
            patient_name="Private Patient Name",
            phone="+919876543210",
            start_datetime=datetime.combine(slot_date, datetime.strptime("10:00", "%H:%M").time(), tzinfo=clinic_tz),
            reason="sensitive medical reason",
            booking_reference="appointment-privacy-123",
        )

        self.assertEqual(event_id, "created-calendar-event")
        body = service.service.events_api.last_insert_body["body"]
        serialized_body = json.dumps(body)
        self.assertNotIn("Private Patient Name", serialized_body)
        self.assertNotIn("+919876543210", serialized_body)
        self.assertNotIn("sensitive medical reason", serialized_body)
        self.assertIn("appointment-privacy-123", body["description"])

    def test_find_appointment_event_recovers_orphaned_calendar_event(self):
        service = GoogleCalendarService.__new__(GoogleCalendarService)
        service.calendar_id = "clinic-calendar@example.test"
        service.service = FakeCalendar([{"id": "orphan-event-id"}])

        event_id = service.find_appointment_event("appointment-789")

        self.assertEqual(event_id, "orphan-event-id")
        self.assertEqual(
            service.service.events_api.last_list_query["privateExtendedProperty"],
            "vaidya_appointment_id=appointment-789",
        )

    def test_find_appointment_event_returns_none_when_no_event_exists(self):
        service = GoogleCalendarService.__new__(GoogleCalendarService)
        service.calendar_id = "clinic-calendar@example.test"
        service.service = FakeCalendar([])

        self.assertIsNone(service.find_appointment_event("appointment-without-event"))

    def test_working_days_and_holidays_close_the_schedule(self):
        service = GoogleCalendarService.__new__(GoogleCalendarService)
        service.calendar_id = "clinic-calendar@example.test"
        service.service = FakeCalendar([])
        future_day = datetime.now(ZoneInfo("Asia/Kolkata")).date() + timedelta(days=10)
        keys = ("CLINIC_WORKING_DAYS", "CLINIC_HOLIDAYS")
        original = {key: os.environ.get(key) for key in keys}
        try:
            os.environ["CLINIC_WORKING_DAYS"] = str((future_day.weekday() + 1) % 7)
            os.environ["CLINIC_HOLIDAYS"] = ""
            self.assertEqual(service.get_available_slots(future_day), [])

            os.environ["CLINIC_WORKING_DAYS"] = "0,1,2,3,4,5,6"
            os.environ["CLINIC_HOLIDAYS"] = future_day.isoformat()
            self.assertEqual(service.get_available_slots(future_day), [])
        finally:
            for key, value in original.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_configured_break_removes_overlapping_slots(self):
        service = GoogleCalendarService.__new__(GoogleCalendarService)
        service.calendar_id = "clinic-calendar@example.test"
        service.service = FakeCalendar([])
        future_day = datetime.now(ZoneInfo("Asia/Kolkata")).date() + timedelta(days=10)
        keys = ("CLINIC_OPEN_HOUR", "CLINIC_CLOSE_HOUR", "APPOINTMENT_DURATION_MINUTES", "CLINIC_BREAKS")
        original = {key: os.environ.get(key) for key in keys}
        try:
            os.environ["CLINIC_OPEN_HOUR"] = "9"
            os.environ["CLINIC_CLOSE_HOUR"] = "11"
            os.environ["APPOINTMENT_DURATION_MINUTES"] = "30"
            os.environ["CLINIC_BREAKS"] = "09:30-10:00"
            self.assertEqual(service.get_available_slots(future_day), ["09:00", "10:00", "10:30"])
        finally:
            for key, value in original.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_midnight_closing_hour_is_supported(self):
        service = GoogleCalendarService.__new__(GoogleCalendarService)
        service.calendar_id = "clinic-calendar@example.test"
        service.service = FakeCalendar([])
        future_day = datetime.now(ZoneInfo("Asia/Kolkata")).date() + timedelta(days=10)
        keys = (
            "CLINIC_OPEN_HOUR", "CLINIC_CLOSE_HOUR", "APPOINTMENT_DURATION_MINUTES",
            "CLINIC_WORKING_DAYS", "CLINIC_HOLIDAYS", "CLINIC_BREAKS",
        )
        original = {key: os.environ.get(key) for key in keys}
        try:
            os.environ["CLINIC_OPEN_HOUR"] = "23"
            os.environ["CLINIC_CLOSE_HOUR"] = "24"
            os.environ["APPOINTMENT_DURATION_MINUTES"] = "30"
            os.environ["CLINIC_WORKING_DAYS"] = "0,1,2,3,4,5,6"
            os.environ["CLINIC_HOLIDAYS"] = ""
            os.environ["CLINIC_BREAKS"] = ""
            self.assertEqual(service.get_available_slots(future_day), ["23:00", "23:30"])
        finally:
            for key, value in original.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

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
