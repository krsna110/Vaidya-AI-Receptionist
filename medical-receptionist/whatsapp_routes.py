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
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.exc import IntegrityError
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)
router = APIRouter(tags=["WhatsApp"])

GRAPH_API_VERSION = os.getenv("WHATSAPP_API_VERSION") or "v26.0"
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
APP_SECRET = os.getenv("WHATSAPP_APP_SECRET", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
MULTIMODAL_MODEL = os.getenv("GEMINI_MULTIMODAL_MODEL", os.getenv("GEMINI_MODEL", "gemini-3.8-flash"))
INTERNAL_BASE_URL = (os.getenv("VAIDYA_INTERNAL_BASE_URL") or f"http://127.0.0.1:{os.getenv('PORT', '8000')}").rstrip("/")
MAX_MEDIA_BYTES = 12 * 1024 * 1024
MAX_WEBHOOK_BYTES = 1024 * 1024

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
        logger.error("Gemini multimodal request failed | error_type=%s", type(exc).__name__)
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


async def _forward_to_existing_receptionist(user_id: str, message: str) -> str:
    """Forward WhatsApp text through the authenticated internal booking boundary."""
    payload = {"user_id": user_id, "session_id": user_id, "message": message[:500]}
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    internal_secret = os.getenv("VAIDYA_INTERNAL_WEBHOOK_SECRET", "").strip()
    environment = os.getenv("ENVIRONMENT", "development").strip().lower()
    is_production = environment in {"production", "prod"}

    if internal_secret:
        timestamp = str(int(datetime.now(timezone.utc).timestamp()))
        signed_payload = timestamp.encode("ascii") + b"." + body
        headers["X-Vaidya-Timestamp"] = timestamp
        headers["X-Vaidya-Signature"] = "sha256=" + hmac.new(
            internal_secret.encode("utf-8"), signed_payload, hashlib.sha256
        ).hexdigest()
    elif is_production or os.getenv("ALLOW_UNAUTHENTICATED_WEBHOOK", "false").strip().lower() != "true":
        raise HTTPException(
            status_code=503,
            detail="Internal webhook authentication is not configured.",
        )

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(35.0, connect=5.0)) as client:
            response = await client.post(
                f"{INTERNAL_BASE_URL}/webhook", content=body, headers=headers
            )
            response.raise_for_status()
            data = response.json()
            return str(data.get("response") or "I couldn't process that message. Please try again.")[:3500]
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Forwarding WhatsApp text to internal receptionist failed | error_type=%s", type(exc).__name__)
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



_last_queue_cleanup = 0.0
MAX_QUEUE_ATTEMPTS = 5


def _claim_whatsapp_message(message_id: str, payload: dict | None = None) -> bool:
    """Persist a message for background processing, deduplicating provider retries."""
    if not message_id:
        return False
    import database
    import models

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db = database.SessionLocal()
    try:
        record = (
            db.query(models.ProcessedWebhookMessage)
            .filter_by(provider="meta_whatsapp", message_id=message_id)
            .first()
        )
        if record:
            if record.status in {"processed", "pending", "processing"}:
                return False
            if record.status == "failed" and record.attempts >= MAX_QUEUE_ATTEMPTS:
                return False
            record.status = "pending"
            record.payload = json.dumps(payload or {}, ensure_ascii=False)
            record.updated_at = now
        else:
            record = models.ProcessedWebhookMessage(
                provider="meta_whatsapp",
                message_id=message_id,
                status="pending",
                payload=json.dumps(payload or {}, ensure_ascii=False),
                attempts=0,
                received_at=now,
                updated_at=now,
            )
            db.add(record)
        try:
            db.commit()
            return True
        except IntegrityError:
            db.rollback()
            return False
    finally:
        db.close()


def _claim_next_whatsapp_message() -> tuple[str, dict, int] | None:
    """Atomically claim one pending row so multiple app workers do not process it twice."""
    import database
    import models

    global _last_queue_cleanup
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db = database.SessionLocal()
    try:
        loop_time = asyncio.get_running_loop().time()
        if loop_time - _last_queue_cleanup > 3600:
            cutoff = now - timedelta(days=30)
            db.query(models.ProcessedWebhookMessage).filter(
                models.ProcessedWebhookMessage.status.in_(["processed", "failed"]),
                models.ProcessedWebhookMessage.received_at < cutoff,
            ).delete(synchronize_session=False)
            db.commit()
            _last_queue_cleanup = loop_time

        stale_cutoff = now - timedelta(minutes=5)
        db.query(models.ProcessedWebhookMessage).filter(
            models.ProcessedWebhookMessage.provider == "meta_whatsapp",
            models.ProcessedWebhookMessage.status == "processing",
            models.ProcessedWebhookMessage.updated_at < stale_cutoff,
            models.ProcessedWebhookMessage.attempts < MAX_QUEUE_ATTEMPTS,
        ).update(
            {
                models.ProcessedWebhookMessage.status: "pending",
                models.ProcessedWebhookMessage.updated_at: now,
            },
            synchronize_session=False,
        )
        db.query(models.ProcessedWebhookMessage).filter(
            models.ProcessedWebhookMessage.provider == "meta_whatsapp",
            models.ProcessedWebhookMessage.status == "processing",
            models.ProcessedWebhookMessage.updated_at < stale_cutoff,
            models.ProcessedWebhookMessage.attempts >= MAX_QUEUE_ATTEMPTS,
        ).update(
            {
                models.ProcessedWebhookMessage.status: "failed",
                models.ProcessedWebhookMessage.updated_at: now,
            },
            synchronize_session=False,
        )
        db.commit()

        record = (
            db.query(models.ProcessedWebhookMessage)
            .filter_by(status="pending", provider="meta_whatsapp")
            .order_by(models.ProcessedWebhookMessage.received_at.asc())
            .first()
        )
        if not record:
            return None
        message_id = record.message_id
        payload_text = record.payload or "{}"
        next_attempt = int(record.attempts or 0) + 1
        changed = (
            db.query(models.ProcessedWebhookMessage)
            .filter_by(id=record.id, status="pending")
            .update(
                {
                    models.ProcessedWebhookMessage.status: "processing",
                    models.ProcessedWebhookMessage.attempts: next_attempt,
                    models.ProcessedWebhookMessage.updated_at: now,
                },
                synchronize_session=False,
            )
        )
        if changed != 1:
            db.rollback()
            return None
        db.commit()
        return message_id, json.loads(payload_text), next_attempt
    except Exception:
        db.rollback()
        logger.exception("Could not claim a queued WhatsApp message")
        return None
    finally:
        db.close()


def _finish_whatsapp_message(message_id: str, status: str) -> None:
    import database
    import models

    db = database.SessionLocal()
    try:
        record = (
            db.query(models.ProcessedWebhookMessage)
            .filter_by(provider="meta_whatsapp", message_id=message_id)
            .first()
        )
        if record:
            record.status = status
            record.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.commit()
    except Exception:
        db.rollback()
        logger.exception("Could not update WhatsApp message processing status")
    finally:
        db.close()


async def _process_whatsapp_message(message: dict) -> None:
    """Process one queued Meta message. Raise retryable failures to the queue worker."""
    sender = str(message.get("from") or "").strip()
    message_type = message.get("type")
    if message_type == "text":
        text_body = str((message.get("text") or {}).get("body") or "").strip()
        if text_body:
            answer = await _forward_to_existing_receptionist(sender, text_body)
            await _send_text(sender, answer)
        return

    if message_type == "image":
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
        return

    if message_type == "audio":
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
        return

    await _send_text(
        sender,
        "I can process text messages, voice notes, and images. Please send one of those formats.",
    )


async def process_pending_whatsapp_messages() -> None:
    """Long-running durable queue worker. Pending rows survive app restarts."""
    while True:
        claimed = _claim_next_whatsapp_message()
        if claimed is None:
            await asyncio.sleep(1)
            continue
        message_id, message, attempts = claimed
        try:
            await _process_whatsapp_message(message)
            _finish_whatsapp_message(message_id, "processed")
        except HTTPException as exc:
            logger.warning("Queued WhatsApp message failed | status=%s | attempt=%s", exc.status_code, attempts)
            if exc.status_code in {400, 413, 415}:
                # Invalid content is not going to become valid on a retry.
                try:
                    await _send_text(
                        str(message.get("from") or ""),
                        "Sorry, I couldn't process that media. Please send a supported file or a text message.",
                    )
                    _finish_whatsapp_message(message_id, "processed")
                except Exception:
                    _finish_whatsapp_message(
                        message_id, "pending" if attempts < MAX_QUEUE_ATTEMPTS else "failed"
                    )
            else:
                _finish_whatsapp_message(
                    message_id, "pending" if attempts < MAX_QUEUE_ATTEMPTS else "failed"
                )
        except Exception:
            logger.exception("Queued WhatsApp message failed | attempt=%s", attempts)
            _finish_whatsapp_message(
                message_id, "pending" if attempts < MAX_QUEUE_ATTEMPTS else "failed"
            )
        await asyncio.sleep(min(attempts, 5))


@router.get("/whatsapp/webhook", response_class=PlainTextResponse)
async def verify_whatsapp_webhook(request: Request):
    """Meta webhook verification endpoint."""
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    if mode == "subscribe" and VERIFY_TOKEN and hmac.compare_digest(token or "", VERIFY_TOKEN):
        return PlainTextResponse(challenge or "")
    raise HTTPException(status_code=403, detail="WhatsApp webhook verification failed.")


@router.post("/whatsapp/webhook")
async def receive_whatsapp_webhook(request: Request):
    """Verify and durably enqueue Meta messages, then acknowledge delivery."""
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > MAX_WEBHOOK_BYTES:
        raise HTTPException(status_code=413, detail="Webhook payload is too large.")
    chunks: list[bytes] = []
    body_size = 0
    async for chunk in request.stream():
        body_size += len(chunk)
        if body_size > MAX_WEBHOOK_BYTES:
            raise HTTPException(status_code=413, detail="Webhook payload is too large.")
        chunks.append(chunk)
    raw_body = b"".join(chunks)
    if not _valid_signature(raw_body, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status_code=401, detail="Invalid WhatsApp webhook signature.")

    try:
        payload = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.") from exc

    if (
        not isinstance(payload, dict)
        or payload.get("object") != "whatsapp_business_account"
        or not isinstance(payload.get("entry", []), list)
    ):
        raise HTTPException(status_code=400, detail="Invalid WhatsApp webhook structure.")

    queued = 0
    duplicates = 0
    for entry in payload.get("entry", []):
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes", []) or []:
            if not isinstance(change, dict):
                continue
            value = change.get("value") or {}
            if not isinstance(value, dict):
                continue
            for message in value.get("messages", []) or []:
                if not isinstance(message, dict):
                    continue
                sender = str(message.get("from") or "").strip()
                message_id = str(message.get("id") or "").strip()
                if not sender or not message_id:
                    logger.warning("Skipping WhatsApp message without sender or provider message ID")
                    continue
                if _claim_whatsapp_message(message_id, message):
                    queued += 1
                else:
                    duplicates += 1

    logger.info("WhatsApp webhook accepted | queued=%s duplicates=%s", queued, duplicates)
    return {"status": "accepted", "queued": queued, "duplicates": duplicates}
