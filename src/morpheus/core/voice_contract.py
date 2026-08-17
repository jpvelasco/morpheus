"""Documented voice (STT/TTS) contract for the existing Open WebUI (VOICE-003).

The voice gateway exposes an OpenAI-compatible audio surface that the
existing Open WebUI can use. This module is the canonical source of that
contract: the exact STT and TTS URLs, the documented model names, voices,
and request formats, and the verification rules applied to live responses.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

DEFAULT_VOICES: tuple[str, ...] = (
    "af_heart",
    "af_bella",
    "af_nicole",
    "af_aoede",
    "am_michael",
    "am_fenrir",
    "bf_emma",
    "bm_george",
)

ALLOWED_AUDIO_CONTENT_TYPES: frozenset[str] = frozenset(
    {"audio/wav", "audio/mpeg", "audio/webm", "audio/ogg", "audio/mp4"}
)


class VoiceContractError(ValueError):
    """A voice endpoint returned an incompatible audio contract."""


@dataclass(frozen=True, slots=True)
class VoiceEndpointContract:
    base_url: str
    stt_path: str = "/v1/audio/transcriptions"
    tts_path: str = "/v1/audio/speech"
    stt_model: str = "whisper-1"
    tts_model: str = "kokoro"
    voices: tuple[str, ...] = DEFAULT_VOICES
    allowed_content_types: frozenset[str] = ALLOWED_AUDIO_CONTENT_TYPES

    def __post_init__(self) -> None:
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("voice base_url must use http or https and have a host")
        if parsed.username or parsed.password:
            raise ValueError("voice base_url must not contain embedded credentials")
        if parsed.query or parsed.fragment or parsed.path not in ("", "/"):
            raise ValueError("voice base_url must not contain a path, query, or fragment")


def documented_stt_url(contract: VoiceEndpointContract) -> str:
    """Return the exact STT URL the existing Open WebUI can use."""
    return f"{contract.base_url.rstrip('/')}{contract.stt_path}"


def documented_tts_url(contract: VoiceEndpointContract) -> str:
    """Return the exact TTS URL the existing Open WebUI can use."""
    return f"{contract.base_url.rstrip('/')}{contract.tts_path}"


def documented_voices(contract: VoiceEndpointContract) -> tuple[str, ...]:
    """Return the documented voice names the TTS endpoint accepts."""
    return contract.voices


def validate_audio_content_type(contract: VoiceEndpointContract, content_type: str) -> None:
    """Reject audio uploads whose content type is not in the documented set."""
    normalized = content_type.split(";", 1)[0].strip().lower()
    if normalized not in contract.allowed_content_types:
        raise ValueError("unsupported audio content type")


def verify_stt_payload(payload: object) -> str:
    """Verify a transcription response against the documented STT contract."""
    if not isinstance(payload, dict):
        raise VoiceContractError("transcription response is not JSON")
    text = payload.get("text")
    if not isinstance(text, str):
        raise VoiceContractError("transcription response does not contain text")
    return text


def verify_speech_response(*, content_type: str, content: bytes) -> str:
    """Verify a speech response is non-empty audio; return its normalized type."""
    normalized = content_type.split(";", 1)[0].strip().lower()
    if not normalized.startswith("audio/") or not content:
        raise VoiceContractError("speech response is not non-empty audio")
    return normalized
