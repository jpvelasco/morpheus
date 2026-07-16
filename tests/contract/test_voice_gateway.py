from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from morpheus.voice import app as voice_app
from morpheus.voice.app import create_voice_app

pytestmark = pytest.mark.contract
AUTH = {"Authorization": "Bearer voice-key"}


@dataclass
class FakeUpstream:
    responses: list[httpx.Response | httpx.HTTPError]
    requests: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    async def __aenter__(self) -> FakeUpstream:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        self.requests.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, httpx.HTTPError):
            raise response
        return response


def client(monkeypatch: pytest.MonkeyPatch, upstream: FakeUpstream, **kwargs: Any) -> TestClient:
    monkeypatch.setattr(voice_app.httpx, "AsyncClient", lambda: upstream)
    app = create_voice_app(
        api_key="voice-key",
        stt_url="http://stt.test/",
        tts_url="http://tts.test/",
        **kwargs,
    )
    return TestClient(app)


def test_VOICE_003_gateway_requires_a_configured_key() -> None:
    with pytest.raises(ValueError, match="API key"):
        create_voice_app(api_key="", stt_url="http://stt", tts_url="http://tts")


def test_VOICE_003_gateway_health_and_authentication(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream = FakeUpstream([])
    gateway = client(monkeypatch, upstream)
    assert gateway.get("/healthz").json() == {"status": "ok"}
    transcription = gateway.post(
        "/v1/audio/transcriptions",
        files={"file": ("sample.wav", b"RIFF", "audio/wav")},
    )
    speech = gateway.post(
        "/v1/audio/speech",
        json={"model": "kokoro", "input": "hello", "voice": "af_heart"},
    )
    assert transcription.status_code == 401
    assert speech.status_code == 401
    assert upstream.requests == []


def test_VOICE_001_gateway_forwards_transcription(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream = FakeUpstream([httpx.Response(200, json={"text": "hello"})])
    response = client(monkeypatch, upstream).post(
        "/v1/audio/transcriptions",
        headers=AUTH,
        files={"file": ("sample.wav", b"RIFF-safe", "audio/wav")},
    )
    assert response.json() == {"text": "hello"}
    url, request = upstream.requests[0]
    assert url == "http://stt.test/asr"
    assert request["params"] == {"output": "json", "task": "transcribe"}


def test_VOICE_004_gateway_bounds_audio_before_upstream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upstream = FakeUpstream([])
    response = client(monkeypatch, upstream, max_audio_bytes=4).post(
        "/v1/audio/transcriptions",
        headers=AUTH,
        files={"file": ("sample.wav", b"12345", "audio/wav")},
    )
    assert response.status_code == 413
    assert upstream.requests == []


@pytest.mark.parametrize(
    ("path", "content_type", "content"),
    [
        ("/v1/audio/transcriptions", "application/json", b"{}"),
        ("/v1/audio/speech", "text/plain", b"hello"),
    ],
)
def test_SEC_003_voice_gateway_rejects_wrong_content_type(
    monkeypatch: pytest.MonkeyPatch, path: str, content_type: str, content: bytes
) -> None:
    response = client(monkeypatch, FakeUpstream([])).post(
        path,
        headers={**AUTH, "Content-Type": content_type},
        content=content,
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_content_type"


@pytest.mark.parametrize(
    ("upstream", "code"),
    [
        (httpx.Response(503), "stt_unavailable"),
        (httpx.Response(200, json={"unexpected": True}), "stt_incompatible"),
    ],
)
def test_VOICE_001_gateway_normalizes_stt_failures(
    monkeypatch: pytest.MonkeyPatch, upstream: httpx.Response, code: str
) -> None:
    response = client(monkeypatch, FakeUpstream([upstream])).post(
        "/v1/audio/transcriptions",
        headers=AUTH,
        files={"file": ("sample.wav", b"RIFF", "audio/wav")},
    )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == code


def test_SEC_003_voice_gateway_normalizes_upstream_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = client(monkeypatch, FakeUpstream([httpx.ReadTimeout("timed out")])).post(
        "/v1/audio/speech",
        headers=AUTH,
        json={"model": "kokoro", "input": "hello", "voice": "af_heart"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "tts_unavailable"


def test_SEC_003_voice_gateway_rate_limits_before_upstream(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream = FakeUpstream(
        [httpx.Response(200, content=b"ID3audio", headers={"Content-Type": "audio/mpeg"})]
    )
    gateway = client(monkeypatch, upstream, max_requests_per_minute=1)
    payload = {"model": "kokoro", "input": "hello", "voice": "af_heart"}

    assert gateway.post("/v1/audio/speech", headers=AUTH, json=payload).status_code == 200
    limited = gateway.post("/v1/audio/speech", headers=AUTH, json=payload)
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "request_rate_limited"
    assert len(upstream.requests) == 1


def test_VOICE_002_gateway_forwards_speech(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream = FakeUpstream(
        [httpx.Response(200, content=b"ID3audio", headers={"Content-Type": "audio/mpeg"})]
    )
    response = client(monkeypatch, upstream).post(
        "/v1/audio/speech",
        headers=AUTH,
        json={"model": "kokoro", "input": "hello", "voice": "af_heart"},
    )
    assert response.status_code == 200
    assert response.content == b"ID3audio"
    assert response.headers["content-type"].startswith("audio/mpeg")
    assert upstream.requests[0][0] == "http://tts.test/v1/audio/speech"


@pytest.mark.parametrize(
    ("upstream", "code"),
    [
        (httpx.Response(503), "tts_unavailable"),
        (httpx.Response(200, json={}), "tts_incompatible"),
        (
            httpx.Response(200, content=b"", headers={"Content-Type": "audio/mpeg"}),
            "tts_incompatible",
        ),
    ],
)
def test_VOICE_002_gateway_normalizes_tts_failures(
    monkeypatch: pytest.MonkeyPatch, upstream: httpx.Response, code: str
) -> None:
    response = client(monkeypatch, FakeUpstream([upstream])).post(
        "/v1/audio/speech",
        headers=AUTH,
        json={"model": "kokoro", "input": "hello", "voice": "af_heart"},
    )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == code
