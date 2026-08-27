# Vaidya AI Receptionist

![Vaidya AI Receptionist thumbnail](docs/thumbnail.svg)

An end-to-end medical receptionist MVP: a patient chat UI backed by a FastAPI service that detects intent, collects appointment details, validates clinic rules, and requires explicit confirmation before booking. It also supports authenticated admin views, cancellation, basic rescheduling, SQLite persistence, and optional Google Calendar/LLM integrations.

> **Prototype safety:** This is an administrative scheduling assistant. It does not diagnose, prescribe, or replace a clinician. Do not use it for emergencies; contact local emergency services.

## What is in this repository?

- `medical-receptionist/` — the executable Python FastAPI application.
  - `main.py` — routes and deterministic booking/cancellation/rescheduling workflow.
  - `agent.py` — LLM integration with safe local fallback.
  - `state.py`, `models.py`, `database.py` — conversation and appointment persistence.
  - `static/chat.html` and `static/admin.html` — patient and admin UIs.
- `vaidyai-web/` — static design exports/reference screens; it is not the deployable backend.
- `render.yaml` — Render configuration for the FastAPI service.
- `AUDIT.md` and `DEPLOYMENT.md` — implementation and deployment notes.

## Run locally (Windows PowerShell)

```powershell
git clone https://github.com/krsna110/Vaidya-AI-Receptionist.git
cd Vaidya-AI-Receptionist\medical-receptionist
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create `medical-receptionist/.env` locally (never commit it):

```env
APP_ENV=development
SECRET_KEY=replace-with-a-long-random-value
ADMIN_USERNAME=my-admin
ADMIN_PASSWORD=use-a-strong-password
ACCESS_TOKEN_EXPIRE_MINUTES=30
DATABASE_URL=sqlite:///./sql_app.db
FRONTEND_ORIGINS=http://127.0.0.1:8000,http://localhost:8000
TRUSTED_HOSTS=localhost,127.0.0.1,testserver
REDIS_URL=memory://
GOOGLE_CALENDAR_ALLOW_OAUTH_FLOW=false
# Optional; without these keys the deterministic fallback is used:
# GEMINI_API_KEY=...
# GROQ_API_KEY=...
```

Start from the `medical-receptionist` directory:

```powershell
python -m uvicorn main:app --reload
```

For a fresh production-style database, run migrations before starting the service:

```powershell
python -m alembic upgrade head
```

If migrating an existing database that already contains the baseline tables, back it up and mark the baseline once with `python -m alembic stamp 0001_initial`; subsequent schema changes should use `upgrade`, never `create_all`. Production requires PostgreSQL and a shared `REDIS_URL`; `memory://` is only for local development.

Open:

- Patient chat: <http://127.0.0.1:8000/chat>
- Admin dashboard: <http://127.0.0.1:8000/admin>
- Health: <http://127.0.0.1:8000/health>
- Interactive API docs: <http://127.0.0.1:8000/docs>

The chat flow is: choose a language (English, Hindi, or Hinglish) → request an appointment → provide name, Indian phone number, date, time, and reason → review available slot → explicitly reply `confirm`.

## Optional voice capabilities

The chat microphone supports voice notes without creating a second booking flow. A recording is uploaded to `POST /api/voice/transcribe`, transcribed, and passed into the same `/webhook` receptionist pipeline; raw audio is temporary and deleted after processing. Voice notes are disabled unless configured:

```env
VOICE_NOTES_ENABLED=true
STT_PROVIDER=local                 # disabled (default), local, or huggingface
STT_LANGUAGE=auto
# STT_MODEL=small                  # faster-whisper model when using local
# HF_STT_ENDPOINT=https://...      # hosted Whisper-compatible endpoint
# HF_TOKEN=                        # server-side only, if required
```

`local` requires the optional `faster-whisper` package and a suitable machine; it may be too large for a small Render instance. Hosted STT endpoints can have quotas and may require credentials. If unavailable, text chat continues normally.

Realtime browser voice is an optional LiveKit room extension. It is disabled by default and requires a separately running LiveKit server or LiveKit Cloud plus the optional Python SDK. The backend generates short-lived tokens; LiveKit secrets never go to the browser. Browser WebRTC is not PSTN: calling a real phone number requires a paid SIP/telephony provider and is not implemented here.

```env
LIVE_CALL_ENABLED=false
# LIVEKIT_URL=wss://...
# LIVEKIT_API_KEY=...
# LIVEKIT_API_SECRET=...
```

## Test the API and workflows

From the repository root:

```powershell
python -m pytest medical-receptionist -q
```

Get an admin token for protected endpoints:

```powershell
$login = Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/auth/token `
  -ContentType 'application/x-www-form-urlencoded' `
  -Body @{ username='my-admin'; password='use-a-strong-password' }
$token = $login.access_token
Invoke-RestMethod -Uri http://127.0.0.1:8000/appointments `
  -Headers @{ Authorization="Bearer $token" }
```

Patient `/webhook` requests use a caller-supplied `user_id` to isolate conversation state. Admin endpoints require a valid bearer token. Appointment ownership is checked before patient cancellation/rescheduling.

The server signs the patient session into an HttpOnly, SameSite cookie after the first valid message. A changed session identifier is rejected, and cookies become `Secure` in production.

## Optional integrations

- **Gemini/Groq:** set the corresponding API key in the environment. The app remains usable without either key.
- **Google Calendar:** configure OAuth credentials outside Git and enable the flow only when deploying with a secure credential store. Never commit `client_secret.json` or `token.json`.
- **SQLite:** suitable for a demo or single instance. Use a managed database for production multi-instance deployments.
- **PostgreSQL:** supported for production with `postgresql+psycopg://...`; run `alembic upgrade head` before starting the web process.

## Deploy to Render

The Render service deploys `medical-receptionist/`, not `vaidyai-web/`:

- Root directory: `medical-receptionist`
- Build: `pip install -r requirements.txt`
- Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`

Configure `APP_ENV=production`, a long random `SECRET_KEY`, strong `ADMIN_USERNAME`/`ADMIN_PASSWORD`, and exact comma-separated `FRONTEND_ORIGINS` in Render's secret environment settings. API keys are optional. Verify after deployment with `GET /health` and `GET /chat`; Render deployment itself must be verified in the Render dashboard.

## Security notes

- Secrets belong in environment variables or a secret manager, never source control.
- Production startup fails if required authentication secrets are missing.
- Logs intentionally omit authorization headers, tokens, API keys, passwords, and patient message contents.
- Business-critical validation and confirmation remain deterministic and server-side; an LLM cannot create appointments directly.

## License

Prototype for evaluation and development. Add your organization’s license before distributing commercially.
