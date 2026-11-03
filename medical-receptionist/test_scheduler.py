"""Scheduler regression tests: only confirmed appointments may be processed."""
import os
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("JWT_SECRET", "test-only-secret-for-unit-tests")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_ci.db")
os.environ.setdefault("CLINIC_TIMEZONE", "Asia/Kolkata")

from database import SessionLocal
import models
from scheduler import Scheduler


class SchedulerAppointmentFilterTests(unittest.IsolatedAsyncioTestCase):
    async def _run_job_with_status_pair(self, job_name: str, appointment_date: str, status_field: str, pending_value: str):
        phone_cancelled = "+919876543281"
        phone_confirmed = "+919876543282"
        cancelled_time = "10:00"
        confirmed_time = "10:30"
        db = SessionLocal()
        try:
            db.query(models.Appointment).filter(
                models.Appointment.date == appointment_date,
                models.Appointment.time.in_([cancelled_time, confirmed_time]),
            ).delete(synchronize_session=False)
            db.query(models.Patient).filter(
                models.Patient.phone_number.in_([phone_cancelled, phone_confirmed])
            ).delete(synchronize_session=False)
            db.commit()

            cancelled_patient = models.Patient(name="Cancelled Scheduler Patient", phone_number=phone_cancelled)
            confirmed_patient = models.Patient(name="Confirmed Scheduler Patient", phone_number=phone_confirmed)
            db.add_all([cancelled_patient, confirmed_patient])
            db.commit()
            db.refresh(cancelled_patient)
            db.refresh(confirmed_patient)

            cancelled = models.Appointment(
                patient_id=cancelled_patient.id,
                date=appointment_date,
                time=cancelled_time,
                reason="scheduler cancellation filter",
                description="scheduler cancellation filter",
                is_confirmed=False,
                booking_status="cancelled",
            )
            confirmed = models.Appointment(
                patient_id=confirmed_patient.id,
                date=appointment_date,
                time=confirmed_time,
                reason="scheduler confirmed filter",
                description="scheduler confirmed filter",
                is_confirmed=True,
                booking_status="confirmed",
            )
            db.add_all([cancelled, confirmed])
            db.commit()
            cancelled_id, confirmed_id = cancelled.id, confirmed.id
        finally:
            db.close()

        scheduler = Scheduler.__new__(Scheduler)
        scheduler.timezone = ZoneInfo(os.getenv("CLINIC_TIMEZONE", "Asia/Kolkata"))
        try:
            await getattr(scheduler, job_name)()
            db = SessionLocal()
            try:
                cancelled_saved = db.query(models.Appointment).filter_by(id=cancelled_id).one()
                confirmed_saved = db.query(models.Appointment).filter_by(id=confirmed_id).one()
                self.assertIsNone(getattr(cancelled_saved, status_field))
                self.assertEqual(getattr(confirmed_saved, status_field), pending_value)
            finally:
                db.close()
        finally:
            db = SessionLocal()
            db.query(models.Appointment).filter(
                models.Appointment.date == appointment_date,
                models.Appointment.time.in_([cancelled_time, confirmed_time]),
            ).delete(synchronize_session=False)
            db.query(models.Patient).filter(
                models.Patient.phone_number.in_([phone_cancelled, phone_confirmed])
            ).delete(synchronize_session=False)
            db.commit()
            db.close()

    async def test_reminder_job_skips_cancelled_appointments(self):
        tomorrow = datetime.now(ZoneInfo(os.getenv("CLINIC_TIMEZONE", "Asia/Kolkata"))).date() + timedelta(days=1)
        await self._run_job_with_status_pair(
            "reminder_job", tomorrow.isoformat(), "reminder_status", "pending_reminder"
        )

    async def test_followup_job_skips_cancelled_appointments(self):
        today = datetime.now(ZoneInfo(os.getenv("CLINIC_TIMEZONE", "Asia/Kolkata"))).date()
        await self._run_job_with_status_pair(
            "followup_job", today.isoformat(), "followup_status", "pending_followup"
        )


if __name__ == "__main__":
    unittest.main()
