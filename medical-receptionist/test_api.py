"""Deterministic unit tests for booking helpers; no live server or AI keys required."""
import os
import unittest
from sqlalchemy.exc import IntegrityError

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
    create_appointment_from_booking_data,
    get_recent_conversation_history,
    parse_conversation_state_data,
)
from database import SessionLocal
import models
from state import StateManager, ConversationState


class BookingHelperTests(unittest.TestCase):
    def test_booking_state_survives_state_manager_restart(self):
        user_id = "state-restart-regression-test"
        first_manager = StateManager()
        try:
            first_manager.reset_state(user_id)
            first_manager.set_state(user_id, "CONFIRM", {
                "name": "Rahul Sharma",
                "phone": "+919876543210",
                "date": "2098-12-31",
                "time": "11:00",
                "reason": "routine checkup",
            })
        finally:
            first_manager.close()

        # A new manager/session simulates a fresh application process after restart.
        second_manager = StateManager()
        try:
            restored = second_manager.get_state(user_id)
            self.assertEqual(restored.state, "CONFIRM")
            self.assertEqual(__import__("json").loads(restored.data), {
                "name": "Rahul Sharma",
                "phone": "+919876543210",
                "date": "2098-12-31",
                "time": "11:00",
                "reason": "routine checkup",
            })
        finally:
            second_manager.reset_state(user_id)
            second_manager.db.query(ConversationState).filter_by(user_id=user_id).delete()
            second_manager.db.commit()
            second_manager.close()

    def test_state_manager_recovers_from_malformed_persisted_json(self):
        user_id = "malformed-state-recovery-test"
        manager = StateManager()
        db = SessionLocal()
        try:
            existing = manager.get_state(user_id)
            row = db.query(ConversationState).filter_by(user_id=user_id).one()
            row.data = "not-json"
            db.commit()
            updated = manager.set_state(user_id, "COLLECT_INFO", {"name": "Rahul"})
            self.assertEqual(__import__("json").loads(updated.data), {
                "unknown_count": 0,
                "name": "Rahul",
            })
        finally:
            db.query(ConversationState).filter_by(user_id=user_id).delete()
            db.commit()
            db.close()
            manager.close()

    def test_conversation_state_json_is_decoded_safely(self):
        self.assertEqual(parse_conversation_state_data('{"name": "Rahul"}'), {"name": "Rahul"})
        self.assertEqual(parse_conversation_state_data({"name": "Rahul"}), {"name": "Rahul"})
        self.assertEqual(parse_conversation_state_data("not-json"), {})
        self.assertEqual(parse_conversation_state_data('["not", "an", "object"]'), {})

    def test_conversation_history_uses_latest_six_messages_in_chronological_order(self):
        db = SessionLocal()
        session_id = "history-regression-test"
        try:
            db.query(models.Conversation).filter_by(session_id=session_id).delete()
            base_time = __import__("datetime").datetime(2098, 1, 1, 9, 0, 0)
            for index in range(8):
                db.add(models.Conversation(
                    session_id=session_id,
                    timestamp=base_time + __import__("datetime").timedelta(minutes=index),
                    sender_type="USER" if index % 2 == 0 else "AI",
                    speaker="patient" if index % 2 == 0 else "receptionist",
                    message=f"message-{index}",
                ))
            db.commit()
            history = get_recent_conversation_history(db, session_id, limit=6)
            self.assertEqual([item["content"] for item in history], [
                "message-2", "message-3", "message-4",
                "message-5", "message-6", "message-7",
            ])
            self.assertEqual([item["role"] for item in history], [
                "user", "ai", "user", "ai", "user", "ai",
            ])
        finally:
            db.query(models.Conversation).filter_by(session_id=session_id).delete()
            db.commit()
            db.close()

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

    def test_date_normalization_uses_clinic_local_today_and_tomorrow(self):
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        today = datetime.now(ZoneInfo(os.getenv("CLINIC_TIMEZONE", "Asia/Kolkata"))).date()
        self.assertEqual(normalize_booking_date(today.isoformat()), today.isoformat())
        self.assertEqual(normalize_booking_date("today"), today.isoformat())
        self.assertEqual(normalize_booking_date("tomorrow"), (today + timedelta(days=1)).isoformat())
        self.assertEqual(normalize_booking_date(""), "")

    def test_empty_extractor_values_do_not_overwrite_known_booking_details(self):
        from main import merge_non_empty_booking_data

        deterministic = {
            "name": "Rahul Sharma",
            "phone": "9876543210",
            "date": "2026-11-10",
            "time": "10:30",
            "reason": "dental checkup",
        }
        extractor = {
            "name": None,
            "phone": "",
            "date": None,
            "time": " ",
            "reason": None,
        }
        merged = merge_non_empty_booking_data(deterministic, extractor)
        self.assertEqual(merged, deterministic)

    def test_non_empty_extractor_values_can_refine_booking_details(self):
        from main import merge_non_empty_booking_data

        merged = merge_non_empty_booking_data(
            {"name": "Rahul", "phone": "9876543210"},
            {"name": "Rahul Sharma", "phone": None},
        )
        self.assertEqual(merged["name"], "Rahul Sharma")
        self.assertEqual(merged["phone"], "9876543210")

    def test_database_rejects_duplicate_confirmed_slots(self):
        db = SessionLocal()
        try:
            first_patient = models.Patient(name="Slot Test One", phone_number="+919876543211")
            second_patient = models.Patient(name="Slot Test Two", phone_number="+919876543212")
            db.add_all([first_patient, second_patient])
            db.commit()
            db.refresh(first_patient)
            db.refresh(second_patient)
            first = models.Appointment(
                patient_id=first_patient.id, date="2098-12-30", time="11:00",
                reason="test", description="test", is_confirmed=True, booking_status="confirmed",
            )
            second = models.Appointment(
                patient_id=second_patient.id, date="2098-12-30", time="11:00",
                reason="test", description="test", is_confirmed=True, booking_status="confirmed",
            )
            db.add(first)
            db.commit()
            db.add(second)
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()
        finally:
            db.close()

    def test_booking_detail_extraction_and_required_fields(self):
        details = extract_booking_details("My name is Rahul Sharma and phone 9876543210")
        self.assertEqual(details.get("name"), "Rahul Sharma")
        self.assertEqual(details.get("phone"), "9876543210")
        self.assertEqual(set(missing_booking_fields({})), {"name", "phone", "date", "time", "reason"})

    def test_replaying_booking_request_reuses_pending_reservation(self):
        db = SessionLocal()
        phone = "+919876543298"
        slot_date = "2098-12-29"
        try:
            # Keep the test repeatable when run more than once against a local DB.
            old_patient = db.query(models.Patient).filter_by(phone_number=phone).first()
            if old_patient:
                db.query(models.Appointment).filter_by(patient_id=old_patient.id).delete()
                db.delete(old_patient)
                db.commit()

            patient = models.Patient(name="Idempotency Test", phone_number=phone)
            db.add(patient)
            db.commit()
            first_id = create_appointment_from_booking_data(db, {
                "name": "Idempotency Test",
                "phone": phone,
                "date": slot_date,
                "time": "11:30",
                "reason": "idempotency regression test",
            })
            second_id = create_appointment_from_booking_data(db, {
                "name": "Idempotency Test",
                "phone": phone,
                "date": slot_date,
                "time": "11:30",
                "reason": "idempotency regression test",
            })
            self.assertIsNotNone(first_id)
            self.assertEqual(first_id, second_id)
            count = db.query(models.Appointment).filter_by(
                patient_id=patient.id, date=slot_date, time="11:30"
            ).count()
            self.assertEqual(count, 1)
            reservation = db.query(models.Appointment).filter_by(id=first_id).one()
            self.assertEqual(reservation.booking_status, "pending")
            self.assertFalse(reservation.is_confirmed)
        finally:
            db.close()

    def test_retry_reactivates_failed_reservation_when_slot_is_free(self):
        db = SessionLocal()
        phone = "+919876543223"
        slot_date, slot_time = "2098-12-28", "13:00"
        try:
            patient = models.Patient(name="Failed Retry Patient", phone_number=phone)
            db.add(patient)
            db.commit()
            db.refresh(patient)
            failed = models.Appointment(
                patient_id=patient.id,
                date=slot_date,
                time=slot_time,
                reason="retry after calendar outage",
                description="retry after calendar outage",
                is_confirmed=False,
                booking_status="failed",
            )
            db.add(failed)
            db.commit()
            db.refresh(failed)

            retried_id = create_appointment_from_booking_data(db, {
                "name": patient.name,
                "phone": phone,
                "date": slot_date,
                "time": slot_time,
                "reason": "retry after calendar outage",
            })
            self.assertEqual(retried_id, failed.id)
            db.refresh(failed)
            self.assertEqual(failed.booking_status, "pending")
            self.assertFalse(failed.is_confirmed)
        finally:
            db.query(models.Appointment).filter_by(date=slot_date, time=slot_time).delete()
            db.query(models.Patient).filter_by(phone_number=phone).delete()
            db.commit()
            db.close()

    def test_retry_cannot_reactivate_failed_reservation_over_another_patient(self):
        db = SessionLocal()
        slot_date, slot_time = "2098-12-27", "13:30"
        patient_phone, other_phone = "+919876543224", "+919876543225"
        try:
            db.query(models.Appointment).filter_by(date=slot_date, time=slot_time).delete()
            db.query(models.Patient).filter(
                models.Patient.phone_number.in_([patient_phone, other_phone])
            ).delete(synchronize_session=False)
            db.commit()
            patient = models.Patient(name="Failed Retry Owner", phone_number=patient_phone)
            other = models.Patient(name="New Slot Owner", phone_number=other_phone)
            db.add_all([patient, other])
            db.commit()
            db.refresh(patient)
            db.refresh(other)
            failed = models.Appointment(
                patient_id=patient.id,
                date=slot_date,
                time=slot_time,
                reason="failed retry conflict",
                description="failed retry conflict",
                is_confirmed=False,
                booking_status="failed",
            )
            active = models.Appointment(
                patient_id=other.id,
                date=slot_date,
                time=slot_time,
                reason="new patient reservation",
                description="new patient reservation",
                is_confirmed=False,
                booking_status="pending",
            )
            db.add_all([failed, active])
            db.commit()

            retried_id = create_appointment_from_booking_data(db, {
                "name": patient.name,
                "phone": patient_phone,
                "date": slot_date,
                "time": slot_time,
                "reason": "failed retry conflict",
            })
            self.assertIsNone(retried_id)
            db.refresh(failed)
            self.assertEqual(failed.booking_status, "failed")
            self.assertEqual(
                db.query(models.Appointment).filter_by(date=slot_date, time=slot_time).count(),
                2,
            )
        finally:
            db.query(models.Appointment).filter_by(date=slot_date, time=slot_time).delete()
            db.query(models.Patient).filter(
                models.Patient.phone_number.in_([patient_phone, other_phone])
            ).delete(synchronize_session=False)
            db.commit()
            db.close()

    def test_pending_reservation_blocks_a_second_patient(self):
        db = SessionLocal()
        slot_date, slot_time = "2098-12-29", "12:00"
        patients = [
            ("Slot Guard One", "+919876543297"),
            ("Slot Guard Two", "+919876543296"),
        ]
        try:
            for _, phone in patients:
                old_patient = db.query(models.Patient).filter_by(phone_number=phone).first()
                if old_patient:
                    db.query(models.Appointment).filter_by(patient_id=old_patient.id).delete()
                    db.delete(old_patient)
            db.query(models.Appointment).filter_by(date=slot_date, time=slot_time).delete()
            db.commit()
            db.add_all([
                models.Patient(name=name, phone_number=phone)
                for name, phone in patients
            ])
            db.commit()

            first = create_appointment_from_booking_data(db, {
                "name": patients[0][0], "phone": patients[0][1],
                "date": slot_date, "time": slot_time, "reason": "first patient",
            })
            second = create_appointment_from_booking_data(db, {
                "name": patients[1][0], "phone": patients[1][1],
                "date": slot_date, "time": slot_time, "reason": "second patient",
            })
            self.assertIsNotNone(first)
            self.assertIsNone(second)
            reserved = db.query(models.Appointment).filter_by(id=first).one()
            self.assertEqual(reserved.booking_status, "pending")
            self.assertFalse(reserved.is_confirmed)
        finally:
            db.query(models.Appointment).filter_by(date=slot_date, time=slot_time).delete()
            for _, phone in patients:
                old_patient = db.query(models.Patient).filter_by(phone_number=phone).first()
                if old_patient:
                    db.query(models.Appointment).filter_by(patient_id=old_patient.id).delete()
                    db.delete(old_patient)
            db.commit()
            db.close()


if __name__ == "__main__":
    unittest.main()
