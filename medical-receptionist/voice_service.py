"""Optional speech-to-text and realtime voice provider adapters.

Voice is deliberately fail-closed: no provider is configured by default, raw
audio is processed from a temporary private file and deleted immediately.
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

ALLOWED_AUDIO_TYPES = {
    "audio/webm", "audio/ogg", "audio/wav", "audio/x-wav", "audio/mp4", "audio/mpeg", "video/webm"
}
MAX_AUDIO_BYTES = int(os.getenv("VOICE_MAX_UPLOAD_BYTES", str(8 * 1024 * 1024)))


class VoiceProviderError(RuntimeError):
    pass


class SpeechToTextService:
    def __init__(self) -> None:
        self.provider = os.getenv("STT_PROVIDER", "disabled").strip().lower()
        self.model_name = os.getenv("STT_MODEL", "small")
        self._model = None

    @property
    def enabled(self) -> bool:
        return (
            os.getenv("VOICE_NOTES_ENABLED", "false").lower() == "true"
            and self.provider in {"local", "faster-whisper", "huggingface", "hf"}
        )

    def transcribe(self, audio_bytes: bytes, content_type: str | None, filename: str | None) -> str:
        if not audio_bytes:
            raise VoiceProviderError("Audio is empty")
        if len(audio_bytes) > MAX_AUDIO_BYTES:
            raise VoiceProviderError("Audio file is too large")
        media_type = (content_type or "").split(";", 1)[0].lower()
        if media_type not in ALLOWED_AUDIO_TYPES:
            raise VoiceProviderError("Unsupported audio format")
        if not self._looks_like_audio(audio_bytes, media_type):
            raise VoiceProviderError("Audio content is invalid")
        if self.provider in {"local", "faster-whisper"}:
            return self._transcribe_local(audio_bytes, filename)
        if self.provider in {"huggingface", "hf"}:
            return self._transcribe_huggingface(audio_bytes, media_type)
        raise VoiceProviderError("Speech-to-text is not configured")

    @staticmethod
    def _looks_like_audio(audio_bytes: bytes, media_type: str) -> bool:
        # Lightweight signature checks reject renamed text/executable files.
        if media_type in {"audio/ogg"}:
            return audio_bytes.startswith(b"OggS")
        if media_type in {"audio/wav", "audio/x-wav"}:
            return audio_bytes.startswith(b"RIFF") and audio_bytes[8:12] == b"WAVE"
        if media_type in {"audio/mp4", "audio/mpeg"}:
            return (len(audio_bytes) > 8 and audio_bytes[4:8] == b"ftyp") or audio_bytes.startswith(b"ID3")
        # WebM/Matroska EBML header.
        if media_type in {"audio/webm", "video/webm"}:
            return audio_bytes.startswith(b"\x1a\x45\xdf\xa3")
        return False

    def _transcribe_local(self, audio_bytes: bytes, filename: str | None) -> str:
        try:
            from faster_whisper import WhisperModel  # optional heavy dependency
        except ImportError as exc:
            raise VoiceProviderError("Local Whisper is not installed") from exc
        suffix = Path(filename or "audio.webm").suffix or ".webm"
        temp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(prefix="vaidya-audio-", suffix=suffix, delete=False) as handle:
                handle.write(audio_bytes)
                temp_path = handle.name
            if self._model is None:
                self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
            segments, _ = self._model.transcribe(temp_path, language=os.getenv("STT_LANGUAGE") or None)
            transcript = " ".join(segment.text.strip() for segment in segments).strip()
            if not transcript:
                raise VoiceProviderError("No speech detected")
            return transcript[:500]
        except VoiceProviderError:
            raise
        except Exception as exc:
            logger.warning("Local speech transcription failed: %s", type(exc).__name__)
            raise VoiceProviderError("Speech-to-text provider failed") from exc
        finally:
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

    def _transcribe_huggingface(self, audio_bytes: bytes, media_type: str) -> str:
        endpoint = os.getenv("HF_STT_ENDPOINT") or os.getenv("HF_STT_SPACE")
        token = os.getenv("HF_TOKEN")
        if not endpoint:
            raise VoiceProviderError("Hugging Face speech endpoint is not configured")
        headers = {"Content-Type": media_type}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            response = httpx.post(endpoint, content=audio_bytes, headers=headers, timeout=30)
            response.raise_for_status()
            payload = response.json()
            transcript = payload.get("text") if isinstance(payload, dict) else None
            if not isinstance(transcript, str) or not transcript.strip():
                raise VoiceProviderError("Speech-to-text returned no transcript")
            return transcript.strip()[:500]
        except VoiceProviderError:
            raise
        except Exception as exc:
            logger.warning("Hosted speech transcription failed: %s", type(exc).__name__)
            raise VoiceProviderError("Speech-to-text provider failed") from exc


def create_livekit_session(user_id: str) -> dict:
    """Return a short-lived room token, never provider secrets."""
    if os.getenv("LIVE_CALL_ENABLED", "false").lower() != "true":
        raise VoiceProviderError("Live voice calling is not enabled")
    url = os.getenv("LIVEKIT_URL")
    api_key = os.getenv("LIVEKIT_API_KEY")
    api_secret = os.getenv("LIVEKIT_API_SECRET")
    if not (url and api_key and api_secret):
        raise VoiceProviderError("LiveKit is not configured")
    try:
        from livekit import api  # optional dependency
        import secrets
        room = f"vaidya-{secrets.token_urlsafe(18)}"
        identity = f"patient-{secrets.token_urlsafe(12)}"
        token = (
            api.AccessToken(api_key, api_secret)
            .with_identity(identity)
            .with_name("Vaidya patient")
            .with_ttl(600)
            .with_grants(api.VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True))
            .to_jwt()
        )
        logger.info("Live voice session created")
        return {"url": url, "room": room, "token": token, "expires_in": 600}
    except ImportError as exc:
        raise VoiceProviderError("LiveKit SDK is not installed") from exc
    except Exception as exc:
        logger.warning("Live voice session creation failed: %s", type(exc).__name__)
        raise VoiceProviderError("Live voice provider failed") from exc
