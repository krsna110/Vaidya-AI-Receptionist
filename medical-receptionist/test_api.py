"""Deterministic unit tests for booking helpers; no live server or AI keys required."""
import os
import unittest

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("JWT_SECRET", "test-only-secret-for-unit-tests")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_ci.db")

from main import (
    extract_booking_details,
    is_confirmation_message,
    missing_booking_fields,
    normalize_booking_date,
    normalize_booking_time,
    normalize_phone,
    parse_booking_datetime,
)


class BookingHelperTests(unittest.TestCase):
    def test_phone_normalization(self):
        self.assertEqual(normalize_phone("+91 98765-43210"), "+919876543210")
        self.assertEqual(normalize_phone(""), "")

    def test_time_normalization_uses_canonical_24_hour_format(self):
        self.assertEqual(normalize_booking_time("10 AM"), "10:00")
        self.assertEqual(normalize_booking_time("7:30 pm"), "19:30")
        self.assertEqual(normalize_booking_time("00:15"), "00:15")
        self.assertEqual(normalize_booking_time("25:90"), "")

    def test_booking_datetime_rejects_invalid_values(self):
        self.assertIsNotNone(parse_booking_datetime("2026-11-03", "10 AM"))
        self.assertIsNone(parse_booking_datetime("not-a-date", "10 AM"))
        self.assertIsNone(parse_booking_datetime("2026-11-03", "not-a-time"))

    def test_confirmation_requires_an_explicit_exact_phrase(self):
        self.assertTrue(is_confirmation_message("Yes"))
        self.assertTrue(is_confirmation_message("YES, confirm booking!"))
        self.assertFalse(is_confirmation_message("yesterday"))
        self.assertFalse(is_confirmation_message("yes, but I have a question"))

    def test_date_normalization_rejects_no_value_as_a_valid_date_later(self):
        self.assertEqual(normalize_booking_date("2026-11-03"), "2026-11-03")
        self.assertEqual(normalize_booking_date("tomorrow"), normalize_booking_date("tomorrow"))
        self.assertEqual(normalize_booking_date(""), "")

    def test_booking_detail_extraction_and_required_fields(self):
        details = extract_booking_details("My name is Rahul Sharma and phone 9876543210")
        self.assertEqual(details.get("name"), "Rahul Sharma")
        self.assertEqual(details.get("phone"), "9876543210")
        self.assertEqual(set(missing_booking_fields({})), {"name", "phone", "date", "time", "reason"})


if __name__ == "__main__":
    unittest.main()
