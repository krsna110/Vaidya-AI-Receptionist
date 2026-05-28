import os
import httpx

BASE_URL = os.getenv("WEBHOOK_BASE_URL", "http://127.0.0.1:8123")

r = httpx.post(
    f"{BASE_URL}/webhook",
    json={'message': 'Hello', 'session_id': 'test123'}
)
print('Status:', r.status_code)
print('Body:', r.text)
