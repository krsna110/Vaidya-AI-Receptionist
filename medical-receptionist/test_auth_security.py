"""Regression tests for authentication and webhook access controls."""
import os
import unittest
from urllib.parse import urlencode

import httpx

os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test-verify")
os.environ.setdefault("WHATSAPP_APP_SECRET", "test-secret")

import auth
import database
import models
from whatsapp_app import app


class AuthHelperTests(unittest.TestCase):
    def test_password_hash_is_not_plaintext_and_verifies(self):
        hashed = auth.hash_password("test-password-123")
        self.assertNotEqual(hashed, "test-password-123")
        self.assertTrue(auth.verify_password("test-password-123", hashed))
        self.assertFalse(auth.verify_password("wrong-password", hashed))

    def test_access_token_round_trip(self):
        token = auth.create_access_token({"sub": "test-user"})
        credentials_error = Exception("invalid credentials")
        data = auth.verify_token(token, credentials_error)
        self.assertEqual(data.username, "test-user")


class AuthEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        )

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_webhook_rejects_unauthenticated_request(self):
        response = await self.client.post(
            "/webhook",
            json={"user_id": "security-test", "message": "test"},
        )
        self.assertEqual(response.status_code, 401)

    async def test_login_uses_database_credentials(self):
        username = "auth-regression-test"
        db = database.SessionLocal()
        try:
            old_user = db.query(models.User).filter(models.User.username == username).first()
            if old_user:
                db.delete(old_user)
                db.commit()
            db.add(models.User(
                username=username,
                email="auth-regression-test@example.invalid",
                hashed_password=auth.hash_password("test-password-123"),
            ))
            db.commit()
        finally:
            db.close()

        try:
            response = await self.client.post(
                "/auth/token",
                data={"username": username, "password": "test-password-123"},
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(response.json().get("access_token"))

            wrong_password = await self.client.post(
                "/auth/token",
                data={"username": username, "password": "wrong-password"},
            )
            self.assertEqual(wrong_password.status_code, 401)
        finally:
            db = database.SessionLocal()
            try:
                user = db.query(models.User).filter(models.User.username == username).first()
                if user:
                    db.delete(user)
                    db.commit()
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
