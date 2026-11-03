import hashlib
import hmac
import json
import logging
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from datetime import datetime, timezone

import httpx

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("JWT_SECRET", "test-only-secret-for-unit-tests")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_ci.db")
os.environ.setdefault("FRONTEND_ORIGINS", "https://frontend.example.test")
os.environ.setdefault("ALLOW_UNAUTHENTICATED_WEBHOOK", "true")

from auth import create_access_token, hash_password, verify_password, verify_token
from fastapi import HTTPException
import main as main_module
from main import app
from database import SessionLocal
import models


class SecurityRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        )

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_password_hash_round_trip(self):
        hashed = hash_password("long-enough-test-password")
        self.assertNotEqual(hashed, "long-enough-test-password")
        self.assertTrue(verify_password("long-enough-test-password", hashed))
        self.assertFalse(verify_password("wrong-password", hashed))

    async def test_jwt_round_trip_and_invalid_token(self):
        token = create_access_token({"sub": "test-admin"})
        self.assertEqual(verify_token(token, HTTPException(status_code=401)).username, "test-admin")
        with self.assertRaises(HTTPException):
            verify_token("not-a-jwt", HTTPException(status_code=401))

    async def test_demo_admin_credentials_are_rejected(self):
        response = await self.client.post(
            "/auth/token",
            data={"username": "admin", "password": "password"},
        )
        self.assertEqual(response.status_code, 401)

    async def test_database_admin_can_login_and_cancel_appointment(self):
        db = SessionLocal()
        username = "ci-admin"
        password = "test-password-long-enough"
        try:
            user = db.query(models.User).filter_by(username=username).first()
            if user is None:
                db.add(models.User(
                    username=username,
                    email="ci-admin@localhost.invalid",
                    hashed_password=hash_password(password),
                ))
                db.commit()
            patient = models.Patient(name="CI Patient", phone_number="+919876543210")
            db.add(patient)
            db.commit()
            db.refresh(patient)
            appointment = models.Appointment(
                patient_id=patient.id,
                start_time=__import__("datetime").datetime.utcnow(),
                date="2099-01-01",
                time="10:00",
                reason="CI test",
                description="CI test",
                is_confirmed=True,
                booking_status="confirmed",
            )
            db.add(appointment)
            db.commit()
            db.refresh(appointment)
            appointment_id = appointment.id
        finally:
            db.close()

        login = await self.client.post(
            "/auth/token",
            data={"username": username, "password": password},
        )
        self.assertEqual(login.status_code, 200)
        token = login.json()["access_token"]
        response = await self.client.post(
            f"/appointments/{appointment_id}/cancel",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "cancelled")

    async def test_confirmation_with_incomplete_details_returns_to_collection(self):
        session_id = "incomplete-confirmation-regression"
        original_generate = main_module.agent.generate_response
        original_extract = main_module.agent.extract_patient_data
        original_limiter = main_module.limiter.enabled
        main_module.state_manager.set_state(session_id, "CONFIRM", {
            "name": "Incomplete Confirmation Patient",
            "date": "2099-03-05",
            "time": "11:00",
            "reason": "incomplete booking regression",
        })
        main_module.agent.generate_response = Mock(return_value={
            "intent": "BOOKING", "response": "model draft",
            "data": {}, "confidence": 0.9, "language": "en",
        })
        main_module.agent.extract_patient_data = Mock(return_value={})
        main_module.limiter.enabled = False
        try:
            response = await self.client.post(
                "/chat", json={"session_id": session_id, "message": "yes"}
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn("valid contact number", response.json()["response"])

            state = main_module.state_manager.get_state(session_id)
            self.assertEqual(state.state, "COLLECT_INFO")
        finally:
            main_module.agent.generate_response = original_generate
            main_module.agent.extract_patient_data = original_extract
            main_module.limiter.enabled = original_limiter
            main_module.state_manager.reset_state(session_id)

    async def test_cancelling_pending_booking_releases_slot_for_another_patient(self):
        db = SessionLocal()
        phone_one, phone_two = "+919876543241", "+919876543242"
        slot_date, slot_time = "2099-03-06", "11:30"
        appointment_id = None
        try:
            db.query(models.Appointment).filter_by(date=slot_date, time=slot_time).delete()
            db.query(models.Patient).filter(
                models.Patient.phone_number.in_([phone_one, phone_two])
            ).delete(synchronize_session=False)
            db.commit()
            patient = models.Patient(name="Slot Release Patient One", phone_number=phone_one)
            db.add(patient)
            db.commit()
            db.refresh(patient)
            appointment = models.Appointment(
                patient_id=patient.id,
                date=slot_date,
                time=slot_time,
                reason="slot release regression",
                description="slot release regression",
                is_confirmed=False,
                booking_status="pending",
            )
            db.add(appointment)
            db.commit()
            db.refresh(appointment)
            appointment_id = appointment.id
        finally:
            db.close()

        token = create_access_token({"sub": "test-admin"})
        response = await self.client.post(
            f"/appointments/{appointment_id}/cancel",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "cancelled")

        db = SessionLocal()
        try:
            cancelled = db.query(models.Appointment).filter_by(id=appointment_id).one()
            self.assertEqual(cancelled.booking_status, "cancelled")
            self.assertFalse(cancelled.is_confirmed)

            second_patient = models.Patient(name="Slot Release Patient Two", phone_number=phone_two)
            db.add(second_patient)
            db.commit()
            db.refresh(second_patient)
            replacement_id = main_module.create_appointment_from_booking_data(db, {
                "name": second_patient.name,
                "phone": phone_two,
                "date": slot_date,
                "time": slot_time,
                "reason": "replacement after cancellation",
            })
            self.assertIsNotNone(replacement_id)
            replacement = db.query(models.Appointment).filter_by(id=replacement_id).one()
            self.assertEqual(replacement.booking_status, "pending")
            self.assertEqual(replacement.patient_id, second_patient.id)
        finally:
            db.query(models.Appointment).filter_by(date=slot_date, time=slot_time).delete()
            db.query(models.Patient).filter(
                models.Patient.phone_number.in_([phone_one, phone_two])
            ).delete(synchronize_session=False)
            db.commit()
            db.close()

    async def test_calendar_cancellation_failure_keeps_appointment_active(self):
        db = SessionLocal()
        phone = "+919876543299"
        appointment_id = None
        try:
            db.query(models.Appointment).filter_by(date="2099-04-01", time="10:00").delete()
            db.query(models.Patient).filter_by(phone_number=phone).delete()
            patient = models.Patient(name="Calendar Failure Patient", phone_number=phone)
            db.add(patient)
            db.commit()
            db.refresh(patient)
            appointment = models.Appointment(
                patient_id=patient.id,
                date="2099-04-01",
                time="10:00",
                reason="calendar failure regression",
                description="calendar failure regression",
                is_confirmed=True,
                booking_status="confirmed",
                google_event_id="calendar-event-delete-failure",
            )
            db.add(appointment)
            db.commit()
            db.refresh(appointment)
            appointment_id = appointment.id
        finally:
            db.close()

        original_calendar = main_module.calendar_service
        calendar_mock = Mock()
        calendar_mock.cancel_appointment.return_value = False
        main_module.calendar_service = calendar_mock
        try:
            token = create_access_token({"sub": "test-admin"})
            response = await self.client.post(
                f"/appointments/{appointment_id}/cancel",
                headers={"Authorization": f"Bearer {token}"},
            )
            self.assertEqual(response.status_code, 502)

            db = SessionLocal()
            try:
                saved = db.query(models.Appointment).filter_by(id=appointment_id).one()
                self.assertEqual(saved.booking_status, "confirmed")
                self.assertTrue(saved.is_confirmed)
            finally:
                db.close()
        finally:
            main_module.calendar_service = original_calendar
            db = SessionLocal()
            db.query(models.Appointment).filter_by(id=appointment_id).delete()
            db.query(models.Patient).filter_by(phone_number=phone).delete()
            db.commit()
            db.close()

    async def test_pending_appointment_without_calendar_event_can_be_cancelled(self):
        db = SessionLocal()
        phone = "+919876543221"
        try:
            patient = models.Patient(name="Pending Cancel Patient", phone_number=phone)
            db.add(patient)
            db.commit()
            db.refresh(patient)
            appointment = models.Appointment(
                patient_id=patient.id,
                date="2099-02-01",
                time="11:00",
                reason="pending cancellation",
                description="pending cancellation",
                is_confirmed=False,
                booking_status="pending",
            )
            db.add(appointment)
            db.commit()
            db.refresh(appointment)
            appointment_id = appointment.id
        finally:
            db.close()

        token = create_access_token({"sub": "test-admin"})
        response = await self.client.post(
            f"/appointments/{appointment_id}/cancel",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "cancelled")

        db = SessionLocal()
        try:
            saved = db.query(models.Appointment).filter_by(id=appointment_id).one()
            self.assertEqual(saved.booking_status, "cancelled")
            self.assertFalse(saved.is_confirmed)
        finally:
            db.query(models.Appointment).filter_by(id=appointment_id).delete()
            db.query(models.Patient).filter_by(phone_number=phone).delete()
            db.commit()
            db.close()

    async def test_pending_appointment_with_calendar_event_cancels_external_event(self):
        db = SessionLocal()
        phone = "+919876543222"
        try:
            patient = models.Patient(name="Pending Calendar Cancel Patient", phone_number=phone)
            db.add(patient)
            db.commit()
            db.refresh(patient)
            appointment = models.Appointment(
                patient_id=patient.id,
                date="2099-02-02",
                time="11:30",
                reason="pending calendar cancellation",
                description="pending calendar cancellation",
                is_confirmed=False,
                booking_status="pending",
                google_event_id="orphaned-calendar-event",
            )
            db.add(appointment)
            db.commit()
            db.refresh(appointment)
            appointment_id = appointment.id
        finally:
            db.close()

        original_calendar = main_module.calendar_service
        calendar_mock = Mock()
        calendar_mock.cancel_appointment.return_value = True
        main_module.calendar_service = calendar_mock
        try:
            token = create_access_token({"sub": "test-admin"})
            response = await self.client.post(
                f"/appointments/{appointment_id}/cancel",
                headers={"Authorization": f"Bearer {token}"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "cancelled")
            calendar_mock.cancel_appointment.assert_called_once_with("orphaned-calendar-event")
        finally:
            main_module.calendar_service = original_calendar
            db = SessionLocal()
            db.query(models.Appointment).filter_by(id=appointment_id).delete()
            db.query(models.Patient).filter_by(phone_number=phone).delete()
            db.commit()
            db.close()

    async def test_pending_booking_cancels_orphaned_calendar_event_by_reference(self):
        db = SessionLocal()
        phone = "+919876543226"
        try:
            patient = models.Patient(name="Orphan Event Cancel Patient", phone_number=phone)
            db.add(patient)
            db.commit()
            db.refresh(patient)
            appointment = models.Appointment(
                patient_id=patient.id,
                date="2099-02-03",
                time="12:00",
                reason="orphan event cancellation",
                description="orphan event cancellation",
                is_confirmed=False,
                booking_status="pending",
                google_event_id=None,
            )
            db.add(appointment)
            db.commit()
            db.refresh(appointment)
            appointment_id = appointment.id
        finally:
            db.close()

        original_calendar = main_module.calendar_service
        calendar_mock = Mock()
        calendar_mock.cancel_appointment_by_reference.return_value = True
        main_module.calendar_service = calendar_mock
        try:
            token = create_access_token({"sub": "test-admin"})
            response = await self.client.post(
                f"/appointments/{appointment_id}/cancel",
                headers={"Authorization": f"Bearer {token}"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "cancelled")
            calendar_mock.cancel_appointment_by_reference.assert_called_once_with(str(appointment_id))
        finally:
            main_module.calendar_service = original_calendar
            db = SessionLocal()
            db.query(models.Appointment).filter_by(id=appointment_id).delete()
            db.query(models.Patient).filter_by(phone_number=phone).delete()
            db.commit()
            db.close()

    async def test_public_chat_does_not_claim_to_cancel_or_reschedule_appointments(self):
        session_id = "cancel-reschedule-safety-test"
        original_generate = main_module.agent.generate_response
        original_extract = main_module.agent.extract_patient_data
        original_limiter = main_module.limiter.enabled
        main_module.state_manager.set_state(session_id, "BOOKED", {"appointment_id": 123})
        main_module.agent.generate_response = Mock(return_value={
            "intent": "CANCEL", "response": "Your appointment has been cancelled.",
            "data": {}, "confidence": 0.9, "language": "en",
        })
        main_module.agent.extract_patient_data = Mock(return_value={})
        main_module.limiter.enabled = False
        try:
            for message in ("Please cancel my appointment", "Please reschedule my appointment"):
                response = await self.client.post(
                    "/chat", json={"session_id": session_id, "message": message}
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn("contact clinic staff directly", response.json()["response"])
                self.assertNotIn("has been cancelled", response.json()["response"])
        finally:
            main_module.agent.generate_response = original_generate
            main_module.agent.extract_patient_data = original_extract
            main_module.limiter.enabled = original_limiter
            main_module.state_manager.reset_state(session_id)

    async def test_booking_history_stores_the_final_confirmation_response(self):
        session_id = "final-response-history-test"
        phone = "+919876543239"
        slot_date, slot_time = "2099-03-04", "11:00"
        db = SessionLocal()
        try:
            db.query(models.Conversation).filter_by(session_id=session_id).delete()
            db.query(models.Appointment).filter_by(date=slot_date, time=slot_time).delete()
            db.query(models.Patient).filter_by(phone_number=phone).delete()
            patient = models.Patient(name="History Test Patient", phone_number=phone)
            db.add(patient)
            db.commit()
        finally:
            db.close()

        booking_data = {
            "name": "History Test Patient",
            "phone": phone,
            "date": slot_date,
            "time": slot_time,
            "reason": "history persistence test",
        }
        main_module.state_manager.set_state(session_id, "CONFIRM", booking_data)
        original_generate = main_module.agent.generate_response
        original_extract = main_module.agent.extract_patient_data
        original_calendar = main_module.calendar_service
        original_limiter = main_module.limiter.enabled
        main_module.agent.generate_response = Mock(return_value={
            "intent": "BOOKING", "response": "Intermediate model response",
            "data": {}, "confidence": 0.9, "language": "en",
        })
        main_module.agent.extract_patient_data = Mock(return_value={})
        calendar_mock = Mock()
        # The sync path checks for an orphaned event before checking slot availability.
        # This test exercises the new-booking path, so explicitly report no existing event.
        calendar_mock.find_appointment_event.return_value = None
        calendar_mock.get_available_slots.return_value = [slot_time]
        calendar_mock.book_appointment.return_value = "history-test-calendar-event"
        main_module.calendar_service = calendar_mock
        main_module.limiter.enabled = False
        try:
            response = await self.client.post(
                "/chat", json={"session_id": session_id, "message": "yes"}
            )
            self.assertEqual(response.status_code, 200)
            final_response = response.json()["response"]
            self.assertIn("Your appointment is confirmed", final_response)

            db = SessionLocal()
            try:
                saved_ai_message = (
                    db.query(models.Conversation)
                    .filter_by(session_id=session_id, sender_type="AI")
                    .order_by(models.Conversation.id.desc())
                    .first()
                )
                self.assertIsNotNone(saved_ai_message)
                self.assertEqual(saved_ai_message.message, final_response)
                self.assertNotEqual(saved_ai_message.message, "Intermediate model response")
            finally:
                db.close()
        finally:
            main_module.agent.generate_response = original_generate
            main_module.agent.extract_patient_data = original_extract
            main_module.calendar_service = original_calendar
            main_module.limiter.enabled = original_limiter
            main_module.state_manager.reset_state(session_id)
            db = SessionLocal()
            db.query(models.Conversation).filter_by(session_id=session_id).delete()
            db.query(models.Appointment).filter_by(date=slot_date, time=slot_time).delete()
            db.query(models.Patient).filter_by(phone_number=phone).delete()
            db.commit()
            db.close()

    async def test_patient_endpoints_require_authentication(self):
        response = await self.client.get("/patients")
        self.assertEqual(response.status_code, 401)

    async def test_chat_ui_uses_cryptographically_secure_session_ids(self):
        from pathlib import Path

        chat_source = Path("static/chat.html").read_text(encoding="utf-8-sig")
        generator_start = chat_source.index("function generateUUID()")
        generator_end = chat_source.index("function appendMessage", generator_start)
        generator = chat_source[generator_start:generator_end]
        self.assertIn("window.crypto.randomUUID()", generator)
        self.assertIn("window.crypto.getRandomValues(bytes)", generator)
        self.assertNotIn("Math.random()", generator)

    async def test_public_chat_rejects_oversized_message(self):
        limiter_enabled = main_module.limiter.enabled
        main_module.limiter.enabled = False
        try:
            response = await self.client.post(
                "/chat",
                json={"session_id": "test-session", "message": "x" * 501},
            )
            self.assertEqual(response.status_code, 422)
        finally:
            main_module.limiter.enabled = limiter_enabled

    async def test_production_chat_fails_closed_without_turnstile_configuration(self):
        original = {key: os.environ.get(key) for key in ("ENVIRONMENT", "TURNSTILE_SECRET_KEY", "TURNSTILE_SITE_KEY")}
        limiter_enabled = main_module.limiter.enabled
        main_module.limiter.enabled = False
        os.environ["ENVIRONMENT"] = "production"
        os.environ.pop("TURNSTILE_SECRET_KEY", None)
        try:
            response = await self.client.post(
                "/chat", json={"session_id": "turnstile-config-test", "message": "test"}
            )
            self.assertEqual(response.status_code, 503)
        finally:
            main_module.limiter.enabled = limiter_enabled
            for key, value in original.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    async def test_production_chat_rejects_missing_turnstile_token(self):
        original = {key: os.environ.get(key) for key in ("ENVIRONMENT", "TURNSTILE_SECRET_KEY")}
        limiter_enabled = main_module.limiter.enabled
        main_module.limiter.enabled = False
        os.environ["ENVIRONMENT"] = "production"
        os.environ["TURNSTILE_SECRET_KEY"] = "test-turnstile-secret"
        os.environ["TURNSTILE_SITE_KEY"] = "test-turnstile-site-key"
        try:
            response = await self.client.post(
                "/chat", json={"session_id": "turnstile-token-test", "message": "test"}
            )
            self.assertEqual(response.status_code, 403)
        finally:
            main_module.limiter.enabled = limiter_enabled
            for key, value in original.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    async def test_turnstile_success_response_is_accepted(self):
        from types import SimpleNamespace

        original = {key: os.environ.get(key) for key in ("ENVIRONMENT", "TURNSTILE_SECRET_KEY")}
        os.environ["ENVIRONMENT"] = "production"
        os.environ["TURNSTILE_SECRET_KEY"] = "test-turnstile-secret"
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"success": True}
        client = Mock()
        client.post = AsyncMock(return_value=response)
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=client)
        context.__aexit__ = AsyncMock(return_value=False)
        request = SimpleNamespace(
            headers={"X-Turnstile-Token": "valid-test-token"},
            client=SimpleNamespace(host="127.0.0.1"),
        )
        try:
            with patch.object(main_module.httpx, "AsyncClient", return_value=context):
                await main_module.verify_public_chat_challenge(request)
            client.post.assert_awaited_once()
        finally:
            for key, value in original.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    async def test_turnstile_failure_response_is_rejected(self):
        from types import SimpleNamespace
        from fastapi import HTTPException

        original = {key: os.environ.get(key) for key in ("ENVIRONMENT", "TURNSTILE_SECRET_KEY")}
        os.environ["ENVIRONMENT"] = "production"
        os.environ["TURNSTILE_SECRET_KEY"] = "test-turnstile-secret"
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"success": False}
        client = Mock()
        client.post = AsyncMock(return_value=response)
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=client)
        context.__aexit__ = AsyncMock(return_value=False)
        request = SimpleNamespace(
            headers={"X-Turnstile-Token": "invalid-test-token"},
            client=SimpleNamespace(host="127.0.0.1"),
        )
        try:
            with patch.object(main_module.httpx, "AsyncClient", return_value=context):
                with self.assertRaises(HTTPException) as raised:
                    await main_module.verify_public_chat_challenge(request)
            self.assertEqual(raised.exception.status_code, 403)
        finally:
            for key, value in original.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    async def test_public_chat_is_available_without_internal_hmac(self):
        response = await self.client.post(
            "/chat",
            json={"session_id": "public-chat-test", "message": "test"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["response"], "Test acknowledged.")

    async def test_public_chat_is_rate_limited(self):
        statuses = []
        main_module.limiter.enabled = True
        for index in range(11):
            response = await self.client.post(
                "/chat",
                json={"session_id": f"rate-limit-ci-{index}", "message": "test"},
            )
            statuses.append(response.status_code)
        self.assertIn(429, statuses)

    async def test_structured_logs_redact_phone_email_and_bearer_tokens(self):
        record = logging.LogRecord(
            name="security-test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="patient phone=%s email=%s Authorization: Bearer %s",
            args=("+919876543210", "patient@example.com", "sensitive-token-value"),
            exc_info=None,
        )
        rendered = main_module.JsonLogFormatter().format(record)
        payload = json.loads(rendered)
        self.assertNotIn("+919876543210", rendered)
        self.assertNotIn("patient@example.com", rendered)
        self.assertNotIn("sensitive-token-value", rendered)
        self.assertIn("[REDACTED_PHONE]", payload["message"])
        self.assertIn("[REDACTED_EMAIL]", payload["message"])
        self.assertIn("Bearer [REDACTED]", payload["message"])

    async def test_production_webhook_rejects_missing_and_invalid_internal_signatures(self):
        keys = ("ENVIRONMENT", "VAIDYA_INTERNAL_WEBHOOK_SECRET", "ALLOW_UNAUTHENTICATED_WEBHOOK")
        original = {key: os.environ.get(key) for key in keys}
        limiter_enabled = main_module.limiter.enabled
        main_module.limiter.enabled = False
        os.environ["ENVIRONMENT"] = "production"
        os.environ["VAIDYA_INTERNAL_WEBHOOK_SECRET"] = "test-internal-secret"
        # A development bypass must never override production authentication.
        os.environ["ALLOW_UNAUTHENTICATED_WEBHOOK"] = "true"
        payload = {"session_id": "signed-webhook-test", "message": "test"}
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        timestamp = str(int(datetime.now(timezone.utc).timestamp()))
        try:
            missing = await self.client.post("/webhook", content=body, headers={"Content-Type": "application/json"})
            self.assertEqual(missing.status_code, 401)

            invalid = await self.client.post(
                "/webhook",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Vaidya-Timestamp": timestamp,
                    "X-Vaidya-Signature": "sha256=" + ("0" * 64),
                },
            )
            self.assertEqual(invalid.status_code, 401)

            signed_payload = timestamp.encode("ascii") + b"." + body
            signature = "sha256=" + hmac.new(
                b"test-internal-secret", signed_payload, hashlib.sha256
            ).hexdigest()
            valid = await self.client.post(
                "/webhook",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Vaidya-Timestamp": timestamp,
                    "X-Vaidya-Signature": signature,
                },
            )
            self.assertEqual(valid.status_code, 200)
        finally:
            main_module.limiter.enabled = limiter_enabled
            for key, value in original.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    async def test_cors_does_not_reflect_unconfigured_origin(self):
        response = await self.client.options(
            "/health",
            headers={
                "Origin": "https://attacker.example",
                "Access-Control-Request-Method": "GET",
            },
        )
        self.assertNotEqual(response.headers.get("access-control-allow-origin"), "https://attacker.example")


if __name__ == "__main__":
    unittest.main()
