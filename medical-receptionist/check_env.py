"""Validate local Vaidya AI configuration without printing secret values.

Run from any directory with:
    python medical-receptionist/check_env.py

The .env file is always resolved relative to this script, not the shell's
current working directory.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"

# Do not overwrite values explicitly supplied by the current shell.
load_dotenv(ENV_FILE, override=False)


def configured(name: str) -> bool:
    value = os.getenv(name, "").strip()
    return bool(value) and not value.lower().startswith(("replace_", "your_", "change_me"))


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    print(f"Vaidya AI local configuration check")
    print(f".env file: {ENV_FILE}")
    print(f".env exists: {'yes' if ENV_FILE.is_file() else 'no'}")
    print()

    if not ENV_FILE.is_file():
        warnings.append("Create medical-receptionist/.env from .env.example.")

    # A JWT secret is needed for the authenticated admin API.
    if configured("JWT_SECRET") and len(os.getenv("JWT_SECRET", "")) >= 32:
        print("[OK] JWT_SECRET is configured.")
    else:
        errors.append("Set JWT_SECRET to a random value of at least 32 characters.")

    # Either provider is sufficient; both are recommended for fallback behavior.
    gemini_ready = configured("GEMINI_API_KEY")
    groq_ready = configured("GROQ_API_KEY")
    if gemini_ready or groq_ready:
        providers = ", ".join(
            name for name, ready in (("Gemini", gemini_ready), ("Groq", groq_ready)) if ready
        )
        print(f"[OK] AI provider configured: {providers}.")
        if not (gemini_ready and groq_ready):
            warnings.append("Only one AI provider is configured; provider fallback cannot be exercised.")
    else:
        errors.append("Configure at least one AI provider: GEMINI_API_KEY or GROQ_API_KEY.")

    # Calendar is required for real appointment confirmation, but not for
    # opening the chat UI or running isolated unit tests.
    service_account_ready = configured("GOOGLE_SERVICE_ACCOUNT_JSON")
    oauth_token_ready = (BASE_DIR / "token.json").is_file()
    oauth_flow_enabled = os.getenv("GOOGLE_CALENDAR_ALLOW_OAUTH_FLOW", "").strip().lower() == "true"
    if service_account_ready:
        print("[OK] Google Calendar service-account configuration is present.")
    elif oauth_token_ready:
        print("[OK] Google Calendar OAuth token file is present.")
    elif oauth_flow_enabled and (BASE_DIR / "client_secret.json").is_file():
        print("[OK] Google Calendar local OAuth flow is enabled.")
    else:
        warnings.append(
            "Google Calendar is not ready. For real local bookings, add client_secret.json "
            "and set GOOGLE_CALENDAR_ALLOW_OAUTH_FLOW=true, then authorize once; "
            "or configure GOOGLE_SERVICE_ACCOUNT_JSON."
        )

    # Admin bootstrap is optional for chat-only work, but the pair must be complete.
    admin_user = configured("ADMIN_USERNAME")
    admin_password = configured("ADMIN_PASSWORD")
    if admin_user != admin_password:
        errors.append("Set both ADMIN_USERNAME and ADMIN_PASSWORD, or leave both blank.")
    elif admin_user and len(os.getenv("ADMIN_PASSWORD", "")) < 12:
        errors.append("ADMIN_PASSWORD must contain at least 12 characters.")
    elif admin_user:
        print("[OK] Initial admin bootstrap credentials are configured.")
    else:
        warnings.append("Admin bootstrap is not configured; the admin dashboard cannot be logged into.")

    # WhatsApp is optional for core local development. Avoid partial credentials.
    whatsapp_keys = (
        "WHATSAPP_ACCESS_TOKEN",
        "WHATSAPP_PHONE_NUMBER_ID",
        "WHATSAPP_VERIFY_TOKEN",
        "WHATSAPP_APP_SECRET",
    )
    whatsapp_configured = [configured(key) for key in whatsapp_keys]
    if all(whatsapp_configured):
        print("[OK] WhatsApp credentials are present.")
    elif any(whatsapp_configured):
        missing = [key for key, ready in zip(whatsapp_keys, whatsapp_configured) if not ready]
        warnings.append("WhatsApp configuration is incomplete; missing: " + ", ".join(missing))
    else:
        warnings.append("WhatsApp is not configured; core chat and booking development can still run.")

    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        print(f"[OK] DATABASE_URL is set (scheme: {database_url.split(':', 1)[0]}).")
    else:
        print("[OK] DATABASE_URL is not set; the application default SQLite database will be used.")

    print()
    for warning in warnings:
        print(f"[WARN] {warning}")
    for error in errors:
        print(f"[ERROR] {error}")

    if errors:
        print("\nConfiguration check failed. Fix the errors above before testing AI/admin flows.")
        return 1

    print("\nConfiguration check passed. Warnings identify optional integrations not yet ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
