# WhatsApp voice and image support for Vaidya AI

This integration is an opt-in Meta WhatsApp Cloud API adapter. It does not replace the existing /webhook, booking state machine, Gemini/Groq text fallback, database, authentication routes, or calendar integration.

## Behavior

- Incoming WhatsApp text is forwarded to the existing /webhook endpoint.
- Incoming audio is downloaded from Meta and transcribed by the configured Gemini multimodal model. The transcript is forwarded to /webhook, so existing booking and conversation logic is reused.
- Incoming images are analysed by Gemini. Image responses are saved to the existing conversations table. Medical-document explanations are informational only and do not diagnose or prescribe.
- Media bytes are processed in memory and are not written to disk.
- Webhook POSTs require Meta's X-Hub-Signature-256 HMAC signature.
- Media is downloaded only from HTTPS Meta media hosts, with a 12 MiB application limit.

## Configure

Add these variables to the backend environment (do not commit secrets):

    GEMINI_API_KEY=...
    GEMINI_MULTIMODAL_MODEL=gemini-2.0-flash
    WHATSAPP_ACCESS_TOKEN=...
    WHATSAPP_PHONE_NUMBER_ID=...
    WHATSAPP_VERIFY_TOKEN=use-a-long-random-value
    WHATSAPP_APP_SECRET=...
    WHATSAPP_API_VERSION=v23.0
    VAIDYA_INTERNAL_BASE_URL=http://127.0.0.1:8000

Set WHATSAPP_API_VERSION to a currently supported Graph API version in your Meta app. Configure the WhatsApp webhook callback URL as https://YOUR_DOMAIN/whatsapp/webhook, subscribe to the messages field, and use the same verify token.

The app secret is the Meta App Secret, not the access token. Keep both server-side.

## Run

From medical-receptionist/:

    pip install -r requirements.txt
    uvicorn whatsapp_app:app --host 0.0.0.0 --port 8000

If the existing deployment starts main:app, change only its ASGI target to whatsapp_app:app to register the extra routes. The existing routes remain on the same FastAPI app. Ensure VAIDYA_INTERNAL_BASE_URL points to that same running service.

## Important integration notes

1. This adapter targets the Meta WhatsApp Cloud API webhook schema. If the WhatsApp number is connected through AiSensy or Twilio, use that provider's webhook/media format or adapt the inbound payload; do not paste Meta credentials into a different provider.
2. The existing /webhook must be reachable at VAIDYA_INTERNAL_BASE_URL. The current repo's text webhook is not protected by JWT; keep it behind a trusted network or add provider authentication before exposing it publicly.
3. Existing repo login currently contains a hard-coded admin credential in main.py; this feature does not change it. Fix that separately before production.
4. Gemini multimodal requests need an enabled model and API quota. The existing Groq text fallback remains in use for text and transcribed audio through /webhook; the configured Groq model is not assumed to support image input.
5. Before production, add a durable queue and webhook idempotency keyed by WhatsApp message ID to avoid duplicate work on retries. Test provider verification, signature rejection, media downloads, Hindi/Hinglish audio, appointment booking by voice, and existing regression tests.
6. Medical images may contain sensitive personal data. Inform patients how data is processed, restrict logs, set retention rules, and get appropriate consent. This implementation does not persist raw media files.
