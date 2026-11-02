import hashlib
import hmac
import json
import os
import unittest
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

    async def test_patient_endpoints_require_authentication(self):
        response = await self.client.get("/patients")
        self.assertEqual(response.status_code, 401)

    async def test_webhook_rejects_oversized_message(self):
        response = await self.client.post(
            "/webhook",
            json={"session_id": "test-session", "message": "x" * 501},
        )
        self.assertEqual(response.status_code, 422)

    async def test_public_chat_webhook_is_rate_limited(self):
        statuses = []
        for index in range(11):
            response = await self.client.post(
                "/webhook",
                json={"session_id": f"rate-limit-ci-{index}", "message": "test"},
            )
            statuses.append(response.status_code)
        self.assertIn(429, statuses)

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
