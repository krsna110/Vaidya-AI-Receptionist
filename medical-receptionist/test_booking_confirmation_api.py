"""API-level booking confirmation tests with AI and Calendar providers mocked.

These tests exercise the real /webhook state machine and database writes without
requiring live API credentials or a Google Calendar account.
"""
import os
import uuid
import unittest
from datetime import date, timedelta
from unittest.mock import Mock, patch

import httpx

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("JWT_SECRET", "test-only-secret-for-unit-tests")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_ci.db")
os.environ.setdefault("ALLOW_UNAUTHENTICATED_WEBHOOK", "true")

import main as main_module
import models
from database import SessionLocal


class BookingConfirmationApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main_module.app),
            base_url="http://testserver",
        )
        suffix = uuid.uuid4().hex
        self.session_id = f"booking-confirm-{suffix}"
        self.phone = "9" + str(uuid.uuid4().int)[:9]
        self.booking = {
            "name": "Local Test Patient",
            "phone": self.phone,
            "date": (date(2090, 1, 1) + timedelta(days=int(suffix[:8], 16) % 2500)).isoformat(),
            "time": "11:00",
            "reason": "routine consultation",
        }
        main_module.state_manager.reset_state(self.session_id)
        main_module.state_manager.set_state(self.session_id, "CONFIRM", self.booking)

    async def asyncTearDown(self):
        await self.client.aclose()
        main_module.state_manager.reset_state(self.session_id)
        db = SessionLocal()
        try:
            patient = db.query(models.Patient).filter_by(phone_number=self.phone).first()
            if patient:
                db.query(models.Appointment).filter_by(patient_id=patient.id).delete()
                db.delete(patient)
            db.query(models.Conversation).filter_by(session_id=self.session_id).delete()
            db.commit()
        finally:
            db.close()

    def mocked_agent(self):
        return (
            patch.object(
                main_module.agent,
                "generate_response",
                return_value={
                    "intent": "BOOKING",
                    "response": "I can confirm that appointment.",
                    "data": {},
                    "confidence": 0.99,
                    "language": "en",
                },
            ),
            patch.object(main_module.agent, "extract_patient_data", return_value={}),
        )

    async def test_explicit_confirmation_books_and_persists_calendar_event(self):
        calendar = Mock()
        calendar.find_appointment_event.return_value = None
        calendar.get_available_slots.return_value = ["11:00"]
        calendar.book_appointment.return_value = "calendar-event-local-test"

        generate_patch, extract_patch = self.mocked_agent()
        with generate_patch, extract_patch, patch.object(main_module, "calendar_service", calendar):
            response = await self.client.post(
                "/webhook",
                json={"user_id": self.session_id, "message": "yes confirm"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("appointment is confirmed", response.json()["response"].lower())
        self.assertEqual(response.json()["state"], "BOOKED")

        db = SessionLocal()
        try:
            patient = db.query(models.Patient).filter_by(phone_number=self.phone).first()
            self.assertIsNotNone(patient)
            appointment = db.query(models.Appointment).filter_by(patient_id=patient.id).one()
            self.assertEqual(appointment.booking_status, "confirmed")
            self.assertTrue(appointment.is_confirmed)
            self.assertEqual(appointment.google_event_id, "calendar-event-local-test")
        finally:
            db.close()

        calendar.find_appointment_event.assert_called_once()
        calendar.get_available_slots.assert_called_once()
        calendar.book_appointment.assert_called_once()

    async def test_calendar_failure_does_not_claim_booking_is_confirmed(self):
        calendar = Mock()
        calendar.find_appointment_event.return_value = None
        calendar.get_available_slots.return_value = ["11:00"]
        calendar.book_appointment.return_value = None

        generate_patch, extract_patch = self.mocked_agent()
        with generate_patch, extract_patch, patch.object(main_module, "calendar_service", calendar):
            response = await self.client.post(
                "/webhook",
                json={"user_id": self.session_id, "message": "yes"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("appointment is confirmed", response.json()["response"].lower())

        db = SessionLocal()
        try:
            patient = db.query(models.Patient).filter_by(phone_number=self.phone).first()
            appointment = db.query(models.Appointment).filter_by(patient_id=patient.id).one()
            self.assertEqual(appointment.booking_status, "failed")
            self.assertFalse(appointment.is_confirmed)
            self.assertIsNone(appointment.google_event_id)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
