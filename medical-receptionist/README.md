# Medical AI Receptionist

This project implements an AI-powered medical receptionist system designed to assist patients with appointment booking, answering frequently asked questions, and managing cancellations for a dental/medical clinic.

## Tech Stack

- **FastAPI**: Web framework for building the API.
- **Gemini 2.0 Flash (google.ai.generativelanguage SDK)**: Primary Large Language Model for intent detection and response generation.
- **Groq (Python SDK)**: Fallback Large Language Model when Gemini is unavailable or rate-limited.
- **langdetect**: Library for automatic language detection (English, Hindi, Hinglish).
- **Google Calendar API (google-api-python-client + google-auth-oauthlib)**: For managing appointments.
- **SQLite**: Database for storing conversation states and appointment details.
- **APScheduler**: For scheduling reminder and follow-up jobs.
- **Python-dotenv**: For managing environment variables.

## Project Structure

- `main.py`: Main FastAPI application, defines API routes, handles webhook, and integrates with other components.
- `agent.py`: Contains the AI agent logic for language detection, intent recognition, and response generation using Gemini and Groq.
- `state.py`: Manages conversation states for each user, persisting them in the SQLite database.
- `calendar_service.py`: Handles integration with the Google Calendar API for appointment management.
- `scheduler.py`: Implements scheduled jobs for sending appointment reminders and follow-ups.
- `database.py`: Configures the SQLAlchemy engine and session for database interaction.
- `models.py`: Defines SQLAlchemy models for Patient, Appointment, and ConversationState.
- `auth.py`: Handles JWT token generation and authentication.
- `data/clinic_info.json`: Stores static clinic information, services, and FAQs.
- `static/chat.html`: A simple, dark-themed, mobile-responsive chat UI for interacting with the AI receptionist.
- `.env.example`: Example file for environment variables.
- `.env`: Environment variables (should not be committed to Git).
- `requirements.txt`: Lists all Python dependencies.

## Setup Instructions

Follow these steps to set up and run the project locally.

### 1. Clone the repository

```bash
git clone <repository_url>
cd medical-ai-receptionist
```

### 2. Create a Python Virtual Environment

It's recommended to use a virtual environment to manage dependencies.

```bash
python -m venv venv
```

### 3. Activate the Virtual Environment

- **On Windows:**
  ```bash
  .\venv\Scripts\activate
  ```
- **On macOS/Linux:**
  ```bash
  source venv/bin/activate
  ```

### 4. Install Dependencies

```bash
pip install -r medical-receptionist/requirements.txt
```

### 5. Google Calendar API Credentials (OAuth2)

To use the Google Calendar API, you need to set up OAuth2 credentials:

1.  Go to the [Google Cloud Console](https://console.cloud.google.com/).
2.  Create a new project or select an existing one.
3.  Navigate to "APIs & Services" > "Library" and enable the "Google Calendar API".
4.  Go to "APIs & Services" > "Credentials".
5.  Click "+ Create Credentials" and choose "OAuth client ID".
6.  Select "Desktop app" as the application type and give it a name.
7.  After creating, download the `client_secret.json` file. **Rename it to `client_secret.json` and place it in the root directory of your project (alongside `main.py`, `agent.py`, etc.).**
8.  The first time `calendar_service.py` runs, it will open a browser window for you to authenticate with your Google account and grant permissions. After successful authentication, a `token.json` file will be created, storing your refresh token for future use.

### 6. Set up Environment Variables

Copy the `.env.example` file to `.env` and fill in your API keys:

```bash
cp medical-receptionist/.env.example medical-receptionist/.env
```

Edit the `.env` file:

```
GEMINI_API_KEY="YOUR_GEMINI_API_KEY"
GROQ_API_KEY="YOUR_GROQ_API_KEY"
DATABASE_URL="sqlite:///./medical-receptionist/sql_app.db"
```

-   **GEMINI_API_KEY**: Obtain this from the [Google AI Studio](https://makersuite.google.com/key).
-   **GROQ_API_KEY**: Obtain this from the [Groq Console](https://console.groq.com/keys).
-   **DATABASE_URL**: The default SQLite path is already provided. You generally don't need to change this unless you're using a different database.

### 7. Run the FastAPI Server

```bash
uvicorn medical-receptionist.main:app --reload
```

This will start the development server. You should see output indicating that the server is running, typically at `http://127.0.0.1:8000`.

### 8. Access the Chat UI

Open your web browser and navigate to:

```
http://127.0.0.1:8000/chat
```

The chat UI will automatically authenticate and start a conversation with the AI receptionist.

### 9. Test with Swagger UI (API Documentation)

You can access the interactive API documentation (Swagger UI) at:

```
http://127.0.0.1:8000/docs
```

Here you can test the `/auth/token` and `/webhook` endpoints, among others.

## API Endpoints Reference

-   **GET `/health`**
    -   Description: Health check endpoint to verify the API is running.
    -   Status Code: 200 OK

-   **POST `/auth/token`**
    -   Description: Authenticates a user and returns an access token.
    -   Request Body (Form Data):
        -   `username`: `admin`
        -   `password`: `password`
    -   Response: `{"access_token": "<JWT_TOKEN>", "token_type": "bearer"}`

-   **POST `/webhook` (JWT Protected)**
    -   Description: Receives incoming webhook events (e.g., from a messaging platform) and processes them through the AI agent.
    -   Request Body (JSON):
        ```json
        {
            "user_id": "string (UUID)",
            "message": "string"
        }
        ```
    -   Response: `{"response": "string", "intent": "string", "state": "string"}`

-   **GET `/chat`**
    -   Description: Serves the static chat.html page.

-   **GET `/appointments` (JWT Protected)**
    -   Description: Returns all appointments from the database.
    -   Response: `List[Appointment]`

-   **GET `/slots?date=YYYY-MM-DD`**
    -   Description: Returns available appointment slots for a given date from the Google Calendar API.
    -   Query Parameter:
        -   `date`: Date in YYYY-MM-DD format (e.g., `2026-05-20`)
    -   Response: `List[str]` (e.g., `["09:00", "09:30", "10:00"]`)

## Scheduler Jobs

The application includes scheduled jobs:

-   **Reminder Job**: Runs daily at 9 AM to find appointments for the next day and prepare reminder messages (currently logs to console).
-   **Follow-up Job**: Runs daily at 6 PM to find appointments that occurred today and prepare follow-up messages (currently logs to console).
