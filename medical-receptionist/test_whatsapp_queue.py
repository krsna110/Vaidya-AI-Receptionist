"""Regression tests for durable WhatsApp queueing and duplicate suppression."""
import unittest
import uuid
from unittest.mock import AsyncMock, patch

import database
import models
from whatsapp_app import app  # Ensure development tables exist for the test database.
from whatsapp_routes import _enqueue_webhook_message, process_next_whatsapp_message


class WhatsAppQueueTests(unittest.IsolatedAsyncioTestCase):
    def test_duplicate_message_id_is_enqueued_once(self):
        message_id = "queue-test-" + uuid.uuid4().hex
        payload = {
            "id": message_id,
            "from": "15551234567",
            "type": "text",
            "text": {"body": "hello"},
        }
        try:
            self.assertTrue(_enqueue_webhook_message(message_id, payload))
            self.assertFalse(_enqueue_webhook_message(message_id, payload))
            db = database.SessionLocal()
            try:
                event = db.query(models.WebhookEvent).filter(
                    models.WebhookEvent.message_id == message_id
                ).first()
                self.assertIsNotNone(event)
                self.assertEqual(event.status, "queued")
                self.assertIn('"body":"hello"', event.payload_json)
            finally:
                db.close()
        finally:
            self._delete_event(message_id)

    async def test_worker_marks_success_and_clears_payload(self):
        message_id = "queue-worker-test-" + uuid.uuid4().hex
        payload = {
            "id": message_id,
            "from": "15551234567",
            "type": "text",
            "text": {"body": "hello"},
        }
        try:
            self.assertTrue(_enqueue_webhook_message(message_id, payload))
            with patch("whatsapp_routes._process_whatsapp_message", new=AsyncMock(return_value=True)):
                self.assertTrue(await process_next_whatsapp_message())
            db = database.SessionLocal()
            try:
                event = db.query(models.WebhookEvent).filter(
                    models.WebhookEvent.message_id == message_id
                ).first()
                self.assertEqual(event.status, "processed")
                self.assertIsNone(event.payload_json)
            finally:
                db.close()
        finally:
            self._delete_event(message_id)

    @staticmethod
    def _delete_event(message_id):
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


if __name__ == "__main__":
    unittest.main()
