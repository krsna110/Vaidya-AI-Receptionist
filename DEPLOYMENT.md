# Deployment Guide

The repository contains two separate services:

- `medical-receptionist`: FastAPI backend
- `vaidyai-web`: Next.js frontend

## Recommended deployment

Use a Python web service for the FastAPI backend, a Node web service for the Next.js frontend, and managed PostgreSQL for persistent application data. The backend is not a static site and should not be deployed as a Vercel-only frontend function.

### Backend service

Root directory:

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

Set these environment variables in the hosting provider's secret/configuration UI. Never commit real values:

| Variable | Requirement |
|---|---|
| `ENVIRONMENT` | Set to `production` |
| `JWT_SECRET` | Required; generate a unique random secret |
| `ADMIN_USERNAME` | Required for first admin bootstrap |
| `ADMIN_PASSWORD` | Required for first admin bootstrap; at least 12 characters |
| `DATABASE_URL` | Managed PostgreSQL connection string |
| `FRONTEND_ORIGINS` | Exact deployed frontend origin(s), comma-separated |
| `GEMINI_API_KEY` | Required for Gemini features |
| `GROQ_API_KEY` | Optional fallback provider |
| `CLINIC_TIMEZONE` | IANA timezone, e.g. `Asia/Kolkata` |
| `CLINIC_OPEN_HOUR` / `CLINIC_CLOSE_HOUR` | Clinic hours in 24-hour local time |
| `APPOINTMENT_DURATION_MINUTES` | Slot duration, default 30 |
| `GOOGLE_CALENDAR_ID` | Calendar ID shared with the service account |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Production service-account JSON stored as a secret |
| `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET` | Required only when enabling Meta WhatsApp |

Do not set `GOOGLE_CALENDAR_ALLOW_OAUTH_FLOW=true` in production. Create a Google Cloud service account, enable the Google Calendar API, share the clinic calendar with the service account's `client_email`, and store the full service-account JSON in `GOOGLE_SERVICE_ACCOUNT_JSON`. Set `GOOGLE_CALENDAR_ID` to the shared clinic calendar's ID. Local development can continue to use `client_secret.json` and `token.json`.

### Frontend service

Use Vercel or a Node web service. If using Render:

- Root directory: `vaidyai-web`
- Build command: `npm ci && npm run build`
- Start command: `npm run start -- -p $PORT`
- Set `NEXT_PUBLIC_BACKEND_URL` to the public backend URL.

After the frontend is deployed, set `FRONTEND_ORIGINS` on the backend to the exact frontend origin, then restart the backend.

## Smoke tests

1. `GET https://<backend-host>/health` should return JSON with `status: ok`.
2. Confirm the frontend can reach the backend from its configured origin.
3. Test admin login with the environment-bootstrapped account and verify protected patient/appointment endpoints reject requests without a bearer token.
4. Test booking, calendar failure handling, cancellation, and repeated WhatsApp webhook delivery in a staging calendar.
5. Confirm webhook signature validation works using Meta's real test app before enabling production traffic.
6. Send the same signed WhatsApp message twice and verify the queue processes it once.
7. Simulate a temporary provider/AI failure and verify the queue retries up to five attempts; inspect failed rows before retrying manually.

## Safety and rollback

- Do not deploy `.env`, `token.json`, `client_secret.json`, `sql_app.db`, `node_modules`, `.venv`, or `venv`.
- Take a database backup before migrations and retain the previous backend release for rollback. For a new empty database, the startup command applies all migrations automatically. For an existing database created before Alembic was added, take a backup, verify the schema, run `alembic stamp 0001_initial` from `medical-receptionist/`, then run `alembic upgrade head`; do not stamp an unverified database.
- Use staging credentials and synthetic patient data for tests. Do not use real patient records in CI.
- WhatsApp message payloads are persisted in the database queue for processing and retry. Completed and permanently failed queue rows are purged after 30 days; protect the database as it contains patient message content. The GitHub Actions suite does not verify live Meta delivery, real AI-provider quotas, or end-to-end Google Calendar writes; those require staging credentials and manual verification.
