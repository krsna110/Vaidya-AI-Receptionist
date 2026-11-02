"""Deterministic FastAPI smoke tests; no live server or external AI keys required."""
import os
import unittest

import httpx

os.environ["WHATSAPP_VERIFY_TOKEN"] = "test-verify"
os.environ["WHATSAPP_APP_SECRET"] = "test-secret"

from whatsapp_app import app


class BackendApiSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        )

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_health_endpoint(self):
        response = await self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get("status"), "ok")

    async def test_openapi_document_is_available(self):
        response = await self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("/auth/token", response.json()["paths"])

    async def test_receptionist_webhook_requires_authentication(self):
        response = await self.client.post(
            "/webhook", json={"session_id": "api-smoke", "message": "test"}
        )
        self.assertEqual(response.status_code, 401)

    async def test_demo_credentials_are_not_accepted(self):
        response = await self.client.post(
            "/auth/token", data={"username": "admin", "password": "password"}
        )
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
