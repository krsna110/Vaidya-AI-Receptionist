# Deployment Guide

The current runnable application is the FastAPI service in `medical-receptionist`. The `vaidyai-web` directory contains static HTML design prototypes, not a runnable Next.js app (there is no root `package.json`).

## Recommended deployment

Use a Python web service for the FastAPI application and managed PostgreSQL for persistent application data. The existing chat and admin HTML pages are served by FastAPI; do not configure a Node/Next.js service until an actual frontend app with a package manifest exists.

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
alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port $PORT
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
| `CLINIC_NAME` / `CLINIC_ADDRESS` | Real clinic name and address; never leave a placeholder |
| `CLINIC_TIMEZONE` | IANA timezone, e.g. `Asia/Kolkata` |
| `CLINIC_OPEN_HOUR` / `CLINIC_CLOSE_HOUR` | Clinic hours in 24-hour local time |
| `CLINIC_WORKING_DAYS` | Comma-separated weekdays, Monday=0 through Sunday=6 |
| `CLINIC_HOLIDAYS` | Comma-separated closed dates in `YYYY-MM-DD` format |
| `CLINIC_BREAKS` | Optional comma-separated breaks, e.g. `13:00-14:00` |
| `APPOINTMENT_DURATION_MINUTES` | Slot duration, default 30 |
| `VAIDYA_INTERNAL_WEBHOOK_SECRET` | Required for signed internal calls to `/webhook`; generate a unique random secret |
| `ALLOW_UNAUTHENTICATED_WEBHOOK` | Set to `false` in production; the unsigned bypass is ignored in production |
| `TURNSTILE_SITE_KEY` | Required for production public chat; browser-visible Cloudflare Turnstile site key |
| `TURNSTILE_SECRET_KEY` | Required for production public chat; server-only Cloudflare Turnstile secret |
| `RATE_LIMIT_STORAGE_URI` | Redis URL for shared rate limits when running multiple workers |
| `ENABLE_SCHEDULER` | `true` for a single API worker; `false` on API replicas when using one separate scheduler process |
| `GOOGLE_CALENDAR_ID` | Calendar ID shared with the service account |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Production service-account JSON stored as a secret |

Do not set `GOOGLE_CALENDAR_ALLOW_OAUTH_FLOW=true` in production. Create a Google Cloud service account, enable the Google Calendar API, share the clinic calendar with the service account's `client_email`, and store the full service-account JSON in `GOOGLE_SERVICE_ACCOUNT_JSON`. Set `GOOGLE_CALENDAR_ID` to the shared clinic calendar's ID. Local development can continue to use `client_secret.json` and `token.json`.

### Existing web UI

The current UI files are `medical-receptionist/static/chat.html` and `medical-receptionist/static/admin.html`, served by FastAPI at `/chat` and `/admin`. The `vaidyai-web` directory currently contains HTML design prototypes only, so the Node deployment shown in older notes is not runnable. Do not deploy it as Next.js until a real app and `package.json` are added.

The browser chat uses the rate-limited `POST /chat` route and verifies Cloudflare Turnstile tokens server-side in production. Set both `TURNSTILE_SITE_KEY` and `TURNSTILE_SECRET_KEY`; production chat fails closed if the secret is missing. Add gateway/WAF controls as another layer. The server-to-server `POST /webhook` route requires HMAC in production. Use Redis via `RATE_LIMIT_STORAGE_URI` for shared limits when running multiple backend workers; the built-in IP limit is only a baseline, not bot protection. The APScheduler jobs must run in exactly one process: for a multi-worker API deployment set `ENABLE_SCHEDULER=false` on API workers and run `python scheduler.py` as one separate process after migrations. Do not run a scheduler in every API worker.

## Smoke tests

1. `GET https://<backend-host>/health` should return JSON with `status: ok` for liveness. `GET https://<backend-host>/ready` should return `status: ready` only when the database responds, Alembic migrations are applied, Google Calendar is configured, production security keys are present, at least one AI provider is configured, and an admin account has been bootstrapped.
2. Confirm the frontend can reach the backend from its configured origin.
3. Test admin login with the environment-bootstrapped account and verify protected patient/appointment endpoints reject requests without a bearer token.
4. Test booking, Calendar failure handling, admin cancellation, and duplicate booking requests in a staging calendar. Public chat must direct existing-booking cancellation/rescheduling to clinic staff until patient identity verification is implemented.
5. Verify the browser chat uses `/chat` and the internal `/webhook` rejects unsigned production requests.
## Safety and rollback

- Do not deploy `.env`, `token.json`, `client_secret.json`, `sql_app.db`, `node_modules`, `.venv`, or `venv`.
- Take a database backup before migrations and retain the previous backend release for rollback. For a new empty database, the startup command applies all migrations automatically. For an existing database created before Alembic was added, take a backup, verify the schema, run `alembic stamp 0001_initial` from `medical-receptionist/`, then run `alembic upgrade head`; do not stamp an unverified database.
- Use staging credentials and synthetic patient data for tests. Do not use real patient records in CI.
- The GitHub Actions suite does not verify real AI-provider quotas or end-to-end Google Calendar writes; those require staging credentials and manual verification.
