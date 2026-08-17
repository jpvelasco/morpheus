from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from morpheus.core.voice_contract import (
    VoiceContractError,
    VoiceEndpointContract,
    documented_stt_url,
    documented_tts_url,
    validate_audio_content_type,
    verify_speech_response,
    verify_stt_payload,
)

__all__ = ["SpeechAudio", "VoiceClient", "VoiceContractError"]


@dataclass(frozen=True, slots=True)
class SpeechAudio:
    audio: bytes
    content_type: str


def _service_root(base_url: str) -> str:
    parsed = urlsplit(base_url)
    if parsed.path not in ("", "/", "/v1"):
        raise ValueError("voice base_url must be a service root or end in /v1")
    return base_url.rstrip("/").removesuffix("/v1") or "/"


class VoiceClient:
    def __init__(
        self,
        *,
        base_url: str,
        client: httpx.AsyncClient,
        timeout_seconds: float = 120,
        max_audio_bytes: int = 25 * 1024 * 1024,
    ) -> None:
        self._contract = VoiceEndpointContract(base_url=_service_root(base_url))
        self._client = client
        self._timeout = timeout_seconds
        self._max_audio_bytes = max_audio_bytes

    async def transcribe(
        self,
        *,
        filename: str,
        audio: bytes,
        content_type: str,
        model: str = "whisper-1",
    ) -> str:
        if len(audio) > self._max_audio_bytes:
            raise ValueError("audio exceeds the configured upload limit")
        validate_audio_content_type(self._contract, content_type)
        response = await self._client.post(
            documented_stt_url(self._contract),
            files={"file": (filename, audio, content_type)},
            data={"model": model},
            timeout=self._timeout,
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except json.JSONDecodeError as error:
            raise VoiceContractError("transcription response is not JSON") from error
        return verify_stt_payload(payload)

    async def speak(self, *, text: str, voice: str, model: str) -> SpeechAudio:
        if not 1 <= len(text) <= 10_000:
            raise ValueError("speech text length must be between 1 and 10000 characters")
        response = await self._client.post(
            documented_tts_url(self._contract),
            json={"input": text, "voice": voice, "model": model},
            timeout=self._timeout,
        )
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "")
        return SpeechAudio(
            audio=response.content,
            content_type=verify_speech_response(
                content_type=content_type, content=response.content
            ),
        )
