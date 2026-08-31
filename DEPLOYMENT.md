# Deployment Guide

The deployable MVP is the `medical-receptionist` FastAPI service. The `vaidyai-web`
directory contains static design exports and is not a Node application.

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

For Render, the checked-in `render.yaml` runs `alembic upgrade head` before
starting Uvicorn. Keep migrations as the only production schema change path.

Environment variables:

```text
SECRET_KEY=<long-random-secret>
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
GEMINI_API_KEY=<optional-gemini-key>
GROQ_API_KEY=<optional-groq-key>
DATABASE_URL=<managed-postgresql-url>
REDIS_URL=<managed-redis-url>
FRONTEND_ORIGINS=https://your-frontend-domain.vercel.app
GOOGLE_CALENDAR_ALLOW_OAUTH_FLOW=false
APP_ENV=production
ADMIN_USERNAME=<clinic-admin-username>
ADMIN_PASSWORD=<strong-random-password>
CLINIC_TIMEZONE=Asia/Kolkata
TRUSTED_HOSTS=<your-render-hostname>
SCHEDULER_ENABLED=false
VOICE_NOTES_ENABLED=false
STT_PROVIDER=disabled
LIVE_CALL_ENABLED=false
```

After backend deploys, test:

```text
https://your-backend-domain/health
```

It should return:

```json
{"status":"healthy"}
```

External verification (not run in this workspace): provision managed PostgreSQL
and Redis, set the production variables, run `alembic upgrade head`, then call
`/ready` and exercise booking/cancellation/rescheduling concurrently. Configure
Google OAuth in the provider secret store and repeat those flows with a mock
calendar first and the real calendar second; record API failures and confirm
appointments remain marked `calendar_sync_failed` rather than falsely confirmed.

## 2. First deployment tests

1. Open `https://your-backend-domain/health`.
2. Open `https://your-backend-domain/chat`.
3. Send `hello` in the chat.
4. Set `ADMIN_USERNAME` and `ADMIN_PASSWORD`, then obtain a token from `/auth/token` before opening `/admin`.

## Notes

- Do not deploy `.env`, `token.json`, `client_secret.json`, `sql_app.db`, `node_modules`, `.venv`, or `venv`.
- Gemini may return quota errors if the API key has no remaining quota. The backend falls back to Groq, then to local safe responses.
- SQLite works for demos, but use a managed database for real production usage.
- Production requires PostgreSQL and a shared Redis URL (`redis://` or
  `rediss://`). The in-memory rate limiter is only a local-development fallback.
- The patient UI is served by the same FastAPI service at `/chat`; no separate Node frontend deployment is required.
- In production, set `FRONTEND_ORIGINS` to the exact allowed origins (comma-separated); do not use `*`.
- Voice notes are optional. Local `faster-whisper` can be resource-heavy for Render; use a private hosted STT endpoint if needed and keep its token server-side.
- LiveKit browser voice requires LiveKit Cloud or a separately hosted LiveKit server. Real mobile/landline calling additionally requires paid SIP/telephony service.

## Recovery and rotation checklist

- Configure managed PostgreSQL point-in-time recovery and daily backups; verify a restore at least monthly with `alembic upgrade head` against a restored copy.
- Take a database backup before every migration. Roll back by restoring the backup or applying a reviewed Alembic downgrade; do not edit production tables manually.
- Rotate `SECRET_KEY` to invalidate existing JWTs and patient cookies, then restart all web instances.
- Rotate admin credentials, Redis credentials, and Google OAuth credentials through the hosting provider's secret store. Never commit replacement values.
- Keep at least one previous application release available so a migration rollback can be coordinated with code rollback.
