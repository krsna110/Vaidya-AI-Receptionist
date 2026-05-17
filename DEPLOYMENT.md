# Deployment Guide

This project has two deployable apps:

- `medical-receptionist`: FastAPI backend
- `vaidyai-web`: Next.js frontend

## 1. Deploy Backend

Use a Python host such as Render, Railway, Fly.io, or a VPS.

Backend root directory:

```text
medical-receptionist
```

Build command:

```bash
pip install -r requirements.txt
```

Start command:

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

Environment variables:

```text
SECRET_KEY=<long-random-secret>
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
GEMINI_API_KEY=<optional-gemini-key>
GROQ_API_KEY=<optional-groq-key>
DATABASE_URL=<optional-production-db-url>
FRONTEND_ORIGINS=https://your-frontend-domain.vercel.app
GOOGLE_CALENDAR_ALLOW_OAUTH_FLOW=false
```

After backend deploys, test:

```text
https://your-backend-domain/health
```

It should return:

```json
{"status":"healthy"}
```

## 2. Deploy Frontend

Use Vercel for the Next.js app.

Frontend root directory:

```text
vaidyai-web
```

Build command:

```bash
npm run build
```

Environment variables:

```text
NEXT_PUBLIC_BACKEND_URL=https://your-backend-domain
```

## 3. Connect Both Apps

After the frontend URL is live, update the backend environment variable:

```text
FRONTEND_ORIGINS=https://your-frontend-domain.vercel.app
```

Redeploy/restart the backend.

## 4. First Production Tests

1. Open `https://your-backend-domain/health`.
2. Open `https://your-frontend-domain.vercel.app/chat`.
3. Send `hello` in the chat.
4. Open `https://your-frontend-domain.vercel.app/admin`.

## Notes

- Do not deploy `.env`, `token.json`, `client_secret.json`, `sql_app.db`, `node_modules`, `.venv`, or `venv`.
- Gemini may return quota errors if the API key has no remaining quota. The backend falls back to Groq, then to local safe responses.
- SQLite works for demos, but use a managed database for real production usage.
