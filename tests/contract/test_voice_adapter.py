from __future__ import annotations

import httpx
import pytest

from morpheus.adapters.services.voice import VoiceClient, VoiceContractError

MORPHEUS_OWNED_REQUIREMENTS = frozenset({"VOICE-001", "VOICE-002"})
pytestmark = pytest.mark.contract


@pytest.mark.asyncio
async def test_VOICE_001_transcription_uses_openai_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/audio/transcriptions"
        assert request.headers["content-type"].startswith("multipart/form-data")
        return httpx.Response(200, json={"text": "fixture transcription"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        text = await VoiceClient(base_url="http://voice.test/v1", client=http).transcribe(
            filename="sample.wav", audio=b"RIFF-safe-fixture", content_type="audio/wav"
        )
    assert text == "fixture transcription"


@pytest.mark.asyncio
async def test_VOICE_002_speech_validates_playable_audio_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/audio/speech"
        return httpx.Response(200, content=b"ID3audio", headers={"Content-Type": "audio/mpeg"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await VoiceClient(base_url="http://voice.test/v1", client=http).speak(
            text="hello", voice="af_heart", model="kokoro"
        )
    assert result.content_type == "audio/mpeg"
    assert result.audio == b"ID3audio"


@pytest.mark.asyncio
async def test_VOICE_004_rejects_oversized_audio_before_network() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(ValueError, match="audio exceeds"):
            await VoiceClient(
                base_url="http://voice.test/v1", client=http, max_audio_bytes=4
            ).transcribe(filename="sample.wav", audio=b"12345", content_type="audio/wav")
    assert calls == 0


@pytest.mark.asyncio
async def test_VOICE_003_adapter_uses_the_documented_urls() -> None:
    from morpheus.core.voice_contract import (
        VoiceEndpointContract,
        documented_stt_url,
        documented_tts_url,
    )

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path == "/v1/audio/transcriptions":
            return httpx.Response(200, json={"text": "fixture"})
        return httpx.Response(200, content=b"ID3audio", headers={"Content-Type": "audio/mpeg"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = VoiceClient(base_url="http://voice.test/v1", client=http)
        await client.transcribe(filename="s.wav", audio=b"RIFF", content_type="audio/wav")
        await client.speak(text="hello", voice="af_heart", model="kokoro")
    contract = VoiceEndpointContract(base_url="http://voice.test")
    assert seen[0] == documented_stt_url(contract)
    assert seen[1] == documented_tts_url(contract)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content_type", "body"),
    [("application/json", b"{}"), ("audio/mpeg", b"")],
)
async def test_VOICE_002_rejects_invalid_speech_response(content_type: str, body: bytes) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=body, headers={"Content-Type": content_type})
    )
    async with httpx.AsyncClient(transport=transport) as http:
        with pytest.raises(VoiceContractError):
            await VoiceClient(base_url="http://voice.test/v1", client=http).speak(
                text="hello", voice="af_heart", model="kokoro"
            )
