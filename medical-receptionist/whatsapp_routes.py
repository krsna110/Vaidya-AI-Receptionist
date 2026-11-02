"""Meta WhatsApp Cloud API webhook for Vaidya AI voice and image messages.

Text messages and audio transcripts are forwarded to the existing /webhook handler so
its booking state machine, Gemini/Groq fallback, and database behavior remain in use.
Image questions use Gemini's multimodal input; no medical diagnosis is provided.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timedelta
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from google import genai
from google.genai import types
from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError

import database
import models

logger = logging.getLogger(__name__)
router = APIRouter(tags=["WhatsApp"])

GRAPH_API_VERSION = os.getenv("WHATSAPP_API_VERSION") or "v26.0"
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
APP_SECRET = os.getenv("WHATSAPP_APP_SECRET", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
MULTIMODAL_MODEL = os.getenv("GEMINI_MULTIMODAL_MODEL", os.getenv("GEMINI_MODEL", "gemini-3.8-flash"))
INTERNAL_BASE_URL = os.getenv("VAIDYA_INTERNAL_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
WEBHOOK_SHARED_SECRET = os.getenv("WEBHOOK_SHARED_SECRET", "")
MAX_MEDIA_BYTES = 12 * 1024 * 1024

IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
AUDIO_TYPES = {
    "audio/ogg", "audio/mpeg", "audio/mp3", "audio/mp4",
    "audio/aac", "audio/wav", "audio/amr", "audio/3gpp",
}
SAFE_MEDIA_HOSTS = ("facebook.com", "fbcdn.net", "fbsbx.com")


def _require_whatsapp_config() -> None:
    missing = [
        name for name, value in (
            ("WHATSAPP_ACCESS_TOKEN", ACCESS_TOKEN),
            ("WHATSAPP_PHONE_NUMBER_ID", PHONE_NUMBER_ID),
            ("WHATSAPP_VERIFY_TOKEN", VERIFY_TOKEN),
            ("WHATSAPP_APP_SECRET", APP_SECRET),
        ) if not value
    ]
    if missing:
        raise HTTPException(status_code=503, detail="WhatsApp integration is not configured.")


def _valid_signature(raw_body: bytes, signature_header: str | None) -> bool:
    if not APP_SECRET or not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        APP_SECRET.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def _mime_type(value: str | None) -> str:
    return (value or "").split(";", 1)[0].strip().lower()


def _is_allowed_media_url(value: str) -> bool:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(
        host == suffix or host.endswith("." + suffix) for suffix in SAFE_MEDIA_HOSTS
    )


async def _download_media(media_id: str) -> tuple[bytes, str]:
    """Resolve a WhatsApp media ID, then download only from Meta media hosts."""
    _require_whatsapp_config()
    if not media_id:
        raise HTTPException(status_code=400, detail="WhatsApp media ID is missing.")
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    base = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
    timeout = httpx.Timeout(25.0, connect=8.0)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        metadata_response = await client.get(f"{base}/{media_id}", headers=headers)
        metadata_response.raise_for_status()
        metadata = metadata_response.json()
        media_url = metadata.get("url")
        mime = _mime_type(metadata.get("mime_type"))
        if not media_url:
            raise HTTPException(status_code=502, detail="WhatsApp media URL was missing.")
        if not _is_allowed_media_url(media_url):
            raise HTTPException(status_code=502, detail="Unexpected WhatsApp media host.")
        if mime not in IMAGE_TYPES | AUDIO_TYPES:
            raise HTTPException(status_code=415, detail="This image/audio format is not supported.")

        async with client.stream("GET", media_url, headers=headers) as response:
            response.raise_for_status()
            content_length = response.headers.get("content-length")
            if content_length and content_length.isdigit() and int(content_length) > MAX_MEDIA_BYTES:
                raise HTTPException(status_code=413, detail="Media file is too large.")

            chunks: list[bytes] = []
            total_bytes = 0
            async for chunk in response.aiter_bytes():
                total_bytes += len(chunk)
                if total_bytes > MAX_MEDIA_BYTES:
                    raise HTTPException(status_code=413, detail="Media file is too large.")
                chunks.append(chunk)

            content = b"".join(chunks)
            if not content:
                raise HTTPException(status_code=400, detail="The received media file is empty.")
            return content, mime


async def _gemini_media_prompt(content: bytes, mime: str, prompt: str) -> str:
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=503, detail="Image/voice understanding is not configured.")
    client = genai.Client(api_key=GEMINI_API_KEY)
    part = types.Part.from_bytes(data=content, mime_type=mime)
    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=MULTIMODAL_MODEL,
            contents=[prompt, part],
        )
        answer = (getattr(response, "text", None) or "").strip()
        if not answer:
            raise ValueError("The model returned an empty answer.")
        return answer[:3500]
    except Exception as exc:
        logger.exception("Gemini multimodal request failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail="I could not process that media right now. Please try again or send a text message.",
        ) from exc


async def _send_text(to: str, text: str) -> None:
    _require_whatsapp_config()
    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"preview_url": False, "body": (text or "Please try again.").strip()[:4096]},
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=8.0)) as client:
        response = await client.post(
            url, headers={"Authorization": f"Bearer {ACCESS_TOKEN}"}, json=payload
        )
        if response.is_error:
            logger.error("WhatsApp send failed | status=%s", response.status_code)
            raise HTTPException(status_code=502, detail="Could not send a WhatsApp reply.")


def _claim_webhook_message(message_id: str) -> bool:
    """Claim a provider message ID; skip completed or recently claimed duplicates."""
    db = database.SessionLocal()
    now = datetime.utcnow()
    try:
        event = db.query(models.WebhookEvent).filter(
            models.WebhookEvent.message_id == message_id
        ).first()
        if event:
            if event.status == "processed":
                return False
            if (
                event.status == "processing"
                and event.updated_at
                and now - event.updated_at < timedelta(minutes=5)
            ):
                return False
            event.status = "processing"
            event.attempts = (event.attempts or 0) + 1
            event.updated_at = now
            event.last_error = None
        else:
            event = models.WebhookEvent(
                message_id=message_id,
                status="processing",
                attempts=1,
                received_at=now,
                updated_at=now,
            )
            db.add(event)
        try:
            db.commit()
            return True
        except IntegrityError:
            db.rollback()
            # Another worker claimed this unique message ID first.
            return False
    finally:
        db.close()


def _finish_webhook_message(message_id: str, status_value: str, error_code: str | None = None) -> None:
    db = database.SessionLocal()
    try:
        event = db.query(models.WebhookEvent).filter(
            models.WebhookEvent.message_id == message_id
        ).first()
        if event:
            event.status = status_value
            event.updated_at = datetime.utcnow()
            event.last_error = error_code
            if status_value in {"processed", "dead_letter"}:
                event.payload_json = None
            db.commit()
    except Exception:
        db.rollback()
        logger.exception("Could not update WhatsApp idempotency record")
    finally:
        db.close()


def _enqueue_webhook_message(message_id: str, message: dict) -> bool:
    """Persist a provider message for asynchronous processing."""
    db = database.SessionLocal()
    now = datetime.utcnow()
    try:
        existing = db.query(models.WebhookEvent).filter(
            models.WebhookEvent.message_id == message_id
        ).first()
        if existing:
            return False
        db.add(models.WebhookEvent(
            message_id=message_id,
            status="queued",
            attempts=0,
            payload_json=json.dumps(message, separators=(",", ":")),
            received_at=now,
            updated_at=now,
        ))
        try:
            db.commit()
            return True
        except IntegrityError:
            db.rollback()
            return False
    finally:
        db.close()


def _claim_next_queued_message() -> tuple[str, str, int] | None:
    """Atomically claim one queued, retryable, or stale processing event."""
    db = database.SessionLocal()
    now = datetime.utcnow()
    retry_before = now - timedelta(seconds=30)
    stale_before = now - timedelta(minutes=5)
    eligible = or_(
        models.WebhookEvent.status == "queued",
        and_(
            models.WebhookEvent.status == "failed",
            models.WebhookEvent.attempts < 5,
            models.WebhookEvent.updated_at <= retry_before,
        ),
        and_(
            models.WebhookEvent.status == "processing",
            models.WebhookEvent.updated_at <= stale_before,
        ),
    )
    try:
        event = (
            db.query(models.WebhookEvent)
            .filter(eligible)
            .order_by(models.WebhookEvent.received_at.asc())
            .first()
        )
        if not event:
            return None
        if not event.payload_json:
            event.status = "dead_letter"
            event.last_error = "missing_payload"
            event.updated_at = now
            db.commit()
            return None

        message_id = event.message_id
        previous_status = event.status
        previous_updated_at = event.updated_at
        payload_json = event.payload_json
        attempts = (event.attempts or 0) + 1
        updated = (
            db.query(models.WebhookEvent)
            .filter(
                models.WebhookEvent.message_id == message_id,
                models.WebhookEvent.status == previous_status,
                models.WebhookEvent.updated_at == previous_updated_at,
            )
            .update(
                {
                    "status": "processing",
                    "attempts": attempts,
                    "updated_at": now,
                    "last_error": None,
                },
                synchronize_session=False,
            )
        )
        db.commit()
        if updated != 1:
            return None
        return message_id, payload_json, attempts
    finally:
        db.close()


async def _forward_to_existing_receptionist(user_id: str, message: str) -> str:
    """Reuse the existing text webhook; this preserves booking and Gemini/Groq fallback."""
    payload = {"user_id": user_id, "session_id": user_id, "message": message[:500]}
    try:
        headers = {}
        if WEBHOOK_SHARED_SECRET:
            headers["X-Webhook-Secret"] = WEBHOOK_SHARED_SECRET
        async with httpx.AsyncClient(timeout=httpx.Timeout(35.0, connect=5.0)) as client:
            response = await client.post(
                f"{INTERNAL_BASE_URL}/webhook", json=payload, headers=headers
            )
            response.raise_for_status()
            data = response.json()
            return str(data.get("response") or "I couldn't process that message. Please try again.")[:3500]
    except Exception as exc:
        logger.exception("Forwarding WhatsApp text to existing /webhook failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail="Vaidya AI could not process the message. Please try again shortly.",
        ) from exc


async def _save_image_conversation(user_id: str, user_message: str, answer: str) -> None:
    """Save text metadata only; never persist the raw image."""
    try:
        import database
        import models

        db = database.SessionLocal()
        try:
            db.add(models.Conversation(
                session_id=user_id, sender_type="USER", speaker="patient",
                message=(user_message or "[Image sent]")[:500],
            ))
            db.add(models.Conversation(
                session_id=user_id, sender_type="AI", speaker="receptionist",
                message=answer[:3500],
            ))
            db.commit()
        finally:
            db.close()
    except Exception:
        logger.exception("Could not save image interaction to conversation history")


@router.get("/whatsapp/webhook", response_class=PlainTextResponse)
async def verify_whatsapp_webhook(request: Request):
    """Meta webhook verification endpoint."""
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    if mode == "subscribe" and VERIFY_TOKEN and hmac.compare_digest(token or "", VERIFY_TOKEN):
        return PlainTextResponse(challenge or "")
    raise HTTPException(status_code=403, detail="WhatsApp webhook verification failed.")


async def _process_whatsapp_message(message: dict, final_attempt: bool = False) -> bool:
    sender = str(message.get("from") or "").strip()
    if not sender:
        return True
    message_type = message.get("type")
    try:
        if message_type == "text":
            text_body = str((message.get("text") or {}).get("body") or "").strip()
            if text_body:
                answer = await _forward_to_existing_receptionist(sender, text_body)
                await _send_text(sender, answer)
        elif message_type == "image":
            media = message.get("image") or {}
            content, mime = await _download_media(str(media.get("id") or ""))
            caption = str(media.get("caption") or "").strip()
            prompt = (
                "You are Vaidya AI, a careful medical receptionist. Explain only what is visibly "
                "readable or observable in this image in plain language. Do not diagnose, prescribe, "
                "interpret a report as definitive medical advice, or recommend changing medication. "
                "If it is a medical document, mention that a clinician must interpret clinical meaning. "
                "If the image is unclear, say so. Respond in concise English, Hindi, or Hinglish based "
                f"on this user message: {caption or 'Please describe this image.'}"
            )
            answer = await _gemini_media_prompt(content, mime, prompt)
            await _save_image_conversation(sender, caption or "[Image sent]", answer)
            await _send_text(sender, answer)
        elif message_type == "audio":
            media = message.get("audio") or {}
            content, mime = await _download_media(str(media.get("id") or ""))
            if mime not in AUDIO_TYPES:
                raise HTTPException(status_code=415, detail="Unsupported audio format.")
            transcript = await _gemini_media_prompt(
                content, mime,
                "Transcribe the spoken words exactly, preserving the language used (Hindi, English, "
                "or Hinglish). Return only the transcript. Do not answer the speaker's question."
            )
            if not transcript.strip():
                await _send_text(sender, "I couldn't understand the voice message. Please send it again or type your message.")
            else:
                answer = await _forward_to_existing_receptionist(sender, transcript)
                await _send_text(sender, answer)
        else:
            await _send_text(
                sender,
                "I can process text messages, voice notes, and images. Please send one of those formats.",
            )
        return True
    except HTTPException as exc:
        logger.warning("WhatsApp message processing failed | error_type=%s", type(exc).__name__)
        if final_attempt:
            try:
                await _send_text(
                    sender,
                    "Sorry, I couldn't process that message. Please try again or send your question as text.",
                )
            except Exception:
                logger.error("Could not send WhatsApp error reply | error_type=%s", "send_failed")
        return False
    except Exception as exc:
        logger.error("Unexpected WhatsApp message processing error | error_type=%s", type(exc).__name__)
        if final_attempt:
            try:
                await _send_text(sender, "Sorry, something went wrong. Please try again shortly.")
            except Exception:
                logger.error("Could not send WhatsApp error reply | error_type=%s", "send_failed")
        return False


async def process_next_whatsapp_message() -> bool:
    """Process one durable queue item. Returns False when the queue is empty."""
    claimed = _claim_next_queued_message()
    if not claimed:
        return False
    message_id, payload_json, attempts = claimed
    try:
        message = json.loads(payload_json)
        succeeded = await _process_whatsapp_message(message, final_attempt=attempts >= 5)
        if succeeded:
            _finish_webhook_message(message_id, "processed")
        else:
            terminal = attempts >= 5
            _finish_webhook_message(
                message_id,
                "dead_letter" if terminal else "failed",
                "processing_error",
            )
    except Exception as exc:
        terminal = attempts >= 5
        logger.error("WhatsApp queue item failed | error_type=%s", type(exc).__name__)
        _finish_webhook_message(
            message_id,
            "dead_letter" if terminal else "failed",
            "processing_error",
        )
    return True


@router.post("/whatsapp/webhook")
async def receive_whatsapp_webhook(request: Request):
    """Validate Meta's signature, durably enqueue messages, and return quickly."""
    raw_body = await request.body()
    if not _valid_signature(raw_body, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status_code=401, detail="Invalid WhatsApp webhook signature.")

    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.") from exc

    queued = 0
    duplicates = 0
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value") or {}
            for message in value.get("messages", []) or []:
                sender = str(message.get("from") or "").strip()
                message_id = str(message.get("id") or "").strip()
                if not sender or not message_id:
                    continue
                if _enqueue_webhook_message(message_id, message):
                    queued += 1
                else:
                    duplicates += 1

    return {"status": "accepted", "queued": queued, "duplicates": duplicates}
