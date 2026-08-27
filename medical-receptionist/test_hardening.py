"""Focused MVP hardening tests; run with `python -m unittest test_hardening`."""
import os
import uuid
import unittest

os.environ.setdefault("ADMIN_USERNAME", "test-admin")
os.environ.setdefault("ADMIN_PASSWORD", "test-password")
os.environ.setdefault("SECRET_KEY", "test-secret")

from fastapi.testclient import TestClient
from main import app, agent


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
        self.assertIn("contact", response.json()["response"].lower())

    def test_malformed_agent_is_safe(self):
        original = agent.generate_response
        agent.generate_response = lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("malformed"))
        try:
            response = self.send(uuid.uuid4().hex, "hello")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["intent"], "UNKNOWN")
        finally:
            agent.generate_response = original


if __name__ == "__main__":
    unittest.main()
