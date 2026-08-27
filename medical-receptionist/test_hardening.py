"""Focused MVP hardening tests; run with `python -m unittest test_hardening`."""
import os
import uuid
import unittest

os.environ.setdefault("ADMIN_USERNAME", "test-admin")
os.environ.setdefault("ADMIN_PASSWORD", "test-password")
os.environ.setdefault("SECRET_KEY", "test-secret")

from fastapi.testclient import TestClient
from main import app, agent, is_within_clinic_hours, normalize_booking_date, normalize_booking_time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


class HardeningTests(unittest.TestCase):
    client = TestClient(app)

    def send(self, session, message):
        return self.client.post("/webhook", json={"session_id": session, "message": message})

    def test_health_chat_and_protected_endpoint(self):
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.assertEqual(self.client.get("/chat").status_code, 200)
        self.assertEqual(self.client.get("/appointments").status_code, 401)

    def test_booking_requires_confirmation_and_validates_phone(self):
        session = uuid.uuid4().hex
        for message in ("I want an appointment", "Ravi", "12345"):
            response = self.send(session, message)
        self.assertNotIn("confirmed", response.json()["response"].lower())

    def test_malformed_agent_is_safe(self):
        original = agent.generate_response
        agent.generate_response = lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("malformed"))
        try:
            response = self.send(uuid.uuid4().hex, "hello")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["intent"], "UNKNOWN")
        finally:
            agent.generate_response = original

    def test_date_time_rules_and_state_isolation(self):
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
        self.assertEqual(normalize_booking_date("tomorrow"), (today + timedelta(days=1)).isoformat())
        self.assertEqual(normalize_booking_time("10 am"), "10:00 AM")
        self.assertTrue(is_within_clinic_hours(datetime(2099, 7, 10, 10, 0)))
        self.assertFalse(is_within_clinic_hours(datetime(2099, 7, 12, 10, 0)))
        a, b = uuid.uuid4().hex, uuid.uuid4().hex
        with TestClient(app) as client_a, TestClient(app) as client_b:
            first = client_a.post("/webhook", json={"user_id": a, "message": "hello"})
            second = client_b.post("/webhook", json={"user_id": b, "message": "hello"})
        self.assertNotEqual(first.json()["session_id"], second.json()["session_id"])

    def test_cors_is_not_wildcard(self):
        response = self.client.options("/health", headers={"Origin": "https://untrusted.invalid", "Access-Control-Request-Method": "GET"})
        self.assertIsNone(response.headers.get("access-control-allow-origin"))

    def test_readiness_and_server_issued_patient_session(self):
        self.assertEqual(self.client.get("/ready").status_code, 200)
        with TestClient(app) as client:
            first = client.post("/webhook", json={"user_id": "client-choice", "message": "hello"})
            self.assertEqual(first.status_code, 200)
            self.assertTrue(client.cookies.get("vaidya_patient_session"))
            self.assertNotEqual(first.json()["session_id"], "client-choice")
            second = client.post("/webhook", json={"user_id": "another-client-choice", "message": "hello"})
            self.assertEqual(second.json()["session_id"], first.json()["session_id"])

    def test_voice_disabled_and_invalid_upload_rejected(self):
        response = self.client.post("/api/voice/transcribe?user_id=voice-test-123", files={"audio": ("note.webm", b"not-audio", "audio/webm")})
        self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
    unittest.main()
