import hashlib
import hmac
import json
import os
import unittest
import uuid

import httpx

os.environ["WHATSAPP_VERIFY_TOKEN"] = "test-verify"
os.environ["WHATSAPP_APP_SECRET"] = "test-secret"

import database
import models
from whatsapp_app import app


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

    async def test_signed_webhook_enqueues_and_deduplicates_message(self):
        message_id = "wamid-test-" + uuid.uuid4().hex
        body = json.dumps({
            "object": "whatsapp_business_account",
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "id": message_id,
                            "from": "15551234567",
                            "type": "text",
                            "text": {"body": "hello"},
                        }]
                    }
                }]
            }],
        }, separators=(",", ":")).encode()
        signature = "sha256=" + hmac.new(
            b"test-secret", body, hashlib.sha256
        ).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "X-Hub-Signature-256": signature,
        }
        try:
            first = await self.client.post("/whatsapp/webhook", content=body, headers=headers)
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(first.json()["queued"], 1)
            second = await self.client.post("/whatsapp/webhook", content=body, headers=headers)
            self.assertEqual(second.status_code, 200, second.text)
            self.assertEqual(second.json()["duplicates"], 1)
        finally:
            db = database.SessionLocal()
            try:
                event = db.query(models.WebhookEvent).filter(
                    models.WebhookEvent.message_id == message_id
                ).first()
                if event:
                    db.delete(event)
                    db.commit()
            finally:
                db.close()

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
