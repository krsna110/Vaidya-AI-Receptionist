import hashlib
import hmac
import os
import unittest

import httpx

os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test-verify")
os.environ.setdefault("WHATSAPP_APP_SECRET", "test-secret")

from whatsapp_app import app
from whatsapp_routes import _claim_whatsapp_message, _finish_whatsapp_message


class WhatsAppAppSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        )

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_health_endpoint_is_registered(self):
        response = await self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    async def test_meta_webhook_verification(self):
        response = await self.client.get(
            "/whatsapp/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "test-verify",
                "hub.challenge": "challenge-123",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "challenge-123")

    async def test_webhook_rejects_missing_signature(self):
        response = await self.client.post(
            "/whatsapp/webhook",
            json={"object": "whatsapp_business_account", "entry": []},
        )
        self.assertEqual(response.status_code, 401)

    async def test_duplicate_provider_message_is_not_claimed_twice(self):
        message_id = "ci-idempotency-regression-message"
        self.assertTrue(_claim_whatsapp_message(message_id))
        _finish_whatsapp_message(message_id, "processed")
        self.assertFalse(_claim_whatsapp_message(message_id))

    async def test_whatsapp_message_is_durably_queued(self):
        message_id = "ci-durable-queue-regression-message"
        message = {
            "id": message_id,
            "from": "919876543210",
            "type": "text",
            "text": {"body": "hello"},
        }
        self.assertTrue(_claim_whatsapp_message(message_id, message))
        self.assertFalse(_claim_whatsapp_message(message_id, message))
        import database
        import models
        db = database.SessionLocal()
        try:
            row = db.query(models.ProcessedWebhookMessage).filter_by(message_id=message_id).first()
            self.assertIsNotNone(row)
            self.assertEqual(row.status, "pending")
            self.assertIn("hello", row.payload)
        finally:
            db.close()
        _finish_whatsapp_message(message_id, "processed")

    async def test_webhook_accepts_valid_signature(self):
        body = b'{"object":"whatsapp_business_account","entry":[]}'
        signature = "sha256=" + hmac.new(
            b"test-secret", body, hashlib.sha256
        ).hexdigest()
        response = await self.client.post(
            "/whatsapp/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": signature,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "accepted")


if __name__ == "__main__":
    unittest.main()
