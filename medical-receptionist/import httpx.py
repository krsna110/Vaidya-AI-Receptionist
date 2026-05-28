import httpx

r = httpx.post(
    'http://127.0.0.1:8000/webhook',
    json={'message': 'Hello', 'session_id': 'test123'}
)
print('Status:', r.status_code)
print('Body:', r.text)