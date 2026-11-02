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
alembic upgrade head && uvicorn whatsapp_app:app --host 0.0.0.0 --port $PORT
```

Environment variables:

```text
APP_ENV=production
JWT_SECRET=<long-random-secret>
ADMIN_USERNAME=<admin-username>
ADMIN_PASSWORD=<strong-admin-password>
WEBHOOK_SHARED_SECRET=<different-long-random-secret>
GEMINI_API_KEY=<gemini-key>
GROQ_API_KEY=<groq-key>
DATABASE_URL=<managed-postgresql-url>
FRONTEND_ORIGINS=https://your-frontend-domain.vercel.app
CLINIC_TIMEZONE=Asia/Kolkata
CLINIC_OPEN_TIME=09:00
CLINIC_CLOSE_TIME=18:00
APPOINTMENT_DURATION_MINUTES=30
GOOGLE_CALENDAR_ALLOW_OAUTH_FLOW=false
WHATSAPP_ACCESS_TOKEN=<optional-meta-token>
WHATSAPP_PHONE_NUMBER_ID=<optional-meta-phone-number-id>
WHATSAPP_VERIFY_TOKEN=<optional-meta-verify-token>
WHATSAPP_APP_SECRET=<optional-meta-app-secret>
```

After backend deploys, test:

```text
https://your-backend-domain/health
```

It should return:

```json
{"status":"ok","service":"Vaidya AI","version":"2.0"}
```

## 2. Deploy Frontend

Use Render as a Node web service or use Vercel for the Next.js app.

Frontend root directory:

```text
vaidyai-web
```

Render settings:

```text
Root Directory: vaidyai-web
Runtime: Node
Build Command: npm ci && npm run build
Start Command: npm run start -- -p $PORT
```

Build command:

```bash
npm run build
```

Environment variables:

```text
NEXT_PUBLIC_BACKEND_URL=https://your-backend-domain
```

Do not deploy this Next.js app as a Render Static Site unless you remove the Next API routes. Use a Render Web Service so `/api/*`, `/admin`, and `next start` work correctly.

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
- SQLite works for demos, but use a managed PostgreSQL database for production. The backend normalizes common \`postgres://\` and \`postgresql://\` URLs to the installed psycopg driver.
- Never commit the production \`.env\` or paste secret values into GitHub issues. Set secrets in the hosting provider dashboard.
- The first startup creates the configured admin account only if that username does not already exist. Changing \`ADMIN_PASSWORD\` later does not reset an existing database password.
- The WhatsApp adapter uses Meta WhatsApp Cloud API. Add the public callback \`https://YOUR_BACKEND/whatsapp/webhook\` and subscribe to the \`messages\` field. Configure \`WEBHOOK_SHARED_SECRET\` identically for the backend and its internal adapter.
- Google Calendar is not ready for production until valid OAuth/service-account credentials are provided securely. Do not enable interactive browser OAuth on a hosted server.
