from __future__ import annotations

import json
from dataclasses import dataclass

import httpx


class VoiceContractError(ValueError):
    """A voice sidecar returned an incompatible OpenAI audio contract."""


@dataclass(frozen=True, slots=True)
class SpeechAudio:
    audio: bytes
    content_type: str


class VoiceClient:
    def __init__(
        self,
        *,
        base_url: str,
        client: httpx.AsyncClient,
        timeout_seconds: float = 120,
        max_audio_bytes: int = 25 * 1024 * 1024,
    ) -> None:
        self._base_url = base_url.rstrip("/")
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
        if content_type not in {"audio/wav", "audio/mpeg", "audio/webm", "audio/ogg", "audio/mp4"}:
            raise ValueError("unsupported audio content type")
        response = await self._client.post(
            f"{self._base_url}/audio/transcriptions",
            files={"file": (filename, audio, content_type)},
            data={"model": model},
            timeout=self._timeout,
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except json.JSONDecodeError as error:
            raise VoiceContractError("transcription response is not JSON") from error
        if not isinstance(payload, dict):
            raise VoiceContractError("transcription response does not contain text")
        text = payload.get("text")
        if not isinstance(text, str):
            raise VoiceContractError("transcription response does not contain text")
        return text

    async def speak(self, *, text: str, voice: str, model: str) -> SpeechAudio:
        if not 1 <= len(text) <= 10_000:
            raise ValueError("speech text length must be between 1 and 10000 characters")
        response = await self._client.post(
            f"{self._base_url}/audio/speech",
            json={"input": text, "voice": voice, "model": model},
            timeout=self._timeout,
        )
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
        if not content_type.startswith("audio/") or not response.content:
            raise VoiceContractError("speech response is not non-empty audio")
        return SpeechAudio(audio=response.content, content_type=content_type)
