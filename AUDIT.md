# Vaidya AI Receptionist — MVP audit

## What exists

The repository contains two parallel deliverables. `medical-receptionist/` is the executable product: a FastAPI service, SQLite persistence, conversation state machine, optional Gemini/Groq providers, Google Calendar adapter, scheduler, and static chat/admin pages. `vaidyai-web/` contains static design exports and is not a runnable frontend application (there is no package manifest or Next.js source despite `render.yaml` attempting to build it as Node).

## End-to-end flow

Patient browser → `/chat` → `POST /webhook` → `StateManager` loads the session → `Agent` detects intent and extracts fields → deterministic extraction merges with model data → patient is upserted → booking states collect `name`, `phone`, `date`, `time`, and `reason` → confirmation creates an appointment in SQLite → optional Google Calendar sync.

## Findings and actions

- **P0 fixed:** without either API key, the agent returned a failure response, so the advertised prototype could not complete a conversation. Added a grounded deterministic fallback for greeting, booking, cancellation, FAQ, and unknown intents.
- **P0 fixed:** `asyncio.run()` was called from an async FastAPI request when Gemini was enabled, which raises an event-loop error. Agent execution now runs in a worker thread.
- **P0 fixed:** “my name is …” attempted `{**conversation_state.data}` even though `data` is stored as a JSON string. It now decodes state safely.
- **P0 fixed:** “what is my name?” called `.get()` on the same JSON string. It now decodes safely.
- **P1 fixed:** chat UI hardcoded admin credentials and depended on JWT auth for a public patient webhook that does not require auth. Removed the unnecessary browser login flow.
- **P1 fixed:** static file serving depended on the process working directory. `/chat`, `/admin`, and `/static` now resolve from the module directory.
- **P1 fixed:** empty fields extracted by the local parser could overwrite valid model/state fields with `null`; merges now discard empty values.

## Remaining risks before production

- Admin credentials are now required through `ADMIN_USERNAME` and `ADMIN_PASSWORD` environment variables.
- SQLite plus one long-lived `StateManager` session is suitable for a prototype, not multi-instance production. Use Postgres and request-scoped state sessions for deployment.
- Google Calendar is optional and requires OAuth files; booking still works locally without it.
- Render now deploys `medical-receptionist` directly as a Python web service.
- Cancellation is session-owned for patients and admin-owned through a protected endpoint; basic rescheduling is implemented with explicit confirmation.
- Booking validates Indian phone numbers, future dates, clinic hours, and active-slot conflicts; calendar failures are surfaced as non-successful local-only bookings.
- Medical safety is intentionally limited to receptionist tasks; the agent must not diagnose or provide treatment advice.

## Local run

```powershell
cd medical-receptionist
pip install -r requirements.txt
uvicorn main:app --reload
```

Open `http://127.0.0.1:8000/chat`. The booking flow works without API keys; setting `GEMINI_API_KEY` or `GROQ_API_KEY` enables model responses.
