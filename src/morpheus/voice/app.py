from __future__ import annotations

import hmac
import json
import os
from typing import Annotated, Any

import httpx
import uvicorn
from fastapi import FastAPI, File, Header, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from morpheus.api.body_limit import BodyLimitMiddleware
from morpheus.core.concurrency import ConcurrencyLimiter, FixedWindowRateLimiter
from morpheus.core.voice_contract import (
    VoiceContractError,
    verify_speech_response,
    verify_stt_payload,
)


class SpeechRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(default="kokoro", min_length=1, max_length=128)
    input: str = Field(min_length=1, max_length=10_000)
    voice: str = Field(default="af_heart", min_length=1, max_length=128)
    response_format: str = Field(default="mp3", pattern=r"^(mp3|wav|opus|flac|pcm)$")
    speed: float = Field(default=1, ge=0.5, le=2)


def create_voice_app(
    *,
    api_key: str,
    stt_url: str,
    tts_url: str,
    max_audio_bytes: int = 25 * 1024 * 1024,
    timeout_seconds: float = 120,
    max_concurrent_requests: int = 4,
    max_requests_per_minute: int = 60,
) -> FastAPI:
    if not api_key:
        raise ValueError("voice gateway requires an API key")
    request_limiter = ConcurrencyLimiter(max_concurrent_requests)
    rate_limiter = FixedWindowRateLimiter(max_requests_per_minute)
    app = FastAPI(title="Morpheus Voice Gateway", docs_url=None, redoc_url=None)
    app.add_middleware(BodyLimitMiddleware, max_body_bytes=max_audio_bytes + 1_048_576)

    def authorized(header: str | None) -> bool:
        supplied = (header or "").removeprefix("Bearer ")
        return hmac.compare_digest(supplied, api_key)

    @app.middleware("http")
    async def validate_request_shape(request: Request, call_next: Any) -> Any:
        expected_content_type = {
            "/v1/audio/transcriptions": "multipart/form-data",
            "/v1/audio/speech": "application/json",
        }.get(request.url.path)
        if request.method == "POST" and expected_content_type is not None:
            client_key = request.client.host if request.client is not None else "local"
            if not await rate_limiter.allow(client_key):
                return JSONResponse(
                    status_code=429,
                    headers={"Retry-After": "60"},
                    content={"error": {"code": "request_rate_limited"}},
                )
            content_type = request.headers.get("Content-Type", "").split(";", 1)[0].lower()
            if content_type != expected_content_type:
                return JSONResponse(
                    status_code=415,
                    content={"error": {"code": "unsupported_content_type"}},
                )
            content_length = request.headers.get("Content-Length")
            if content_length:
                try:
                    declared_size = int(content_length)
                except ValueError:
                    return JSONResponse(
                        status_code=400,
                        content={"error": {"code": "invalid_content_length"}},
                    )
                if declared_size < 0:
                    return JSONResponse(
                        status_code=400,
                        content={"error": {"code": "invalid_content_length"}},
                    )
                if declared_size > max_audio_bytes + 1_048_576:
                    return JSONResponse(
                        status_code=413,
                        content={"error": {"code": "request_too_large"}},
                    )
        return await call_next(request)

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/audio/transcriptions")
    async def transcriptions(
        file: Annotated[UploadFile, File()], authorization: Annotated[str | None, Header()] = None
    ) -> Any:
        if not authorized(authorization):
            return JSONResponse(
                status_code=401, content={"error": {"code": "authentication_required"}}
            )
        audio = await file.read(max_audio_bytes + 1)
        await file.close()
        if len(audio) > max_audio_bytes:
            return JSONResponse(status_code=413, content={"error": {"code": "audio_too_large"}})
        if not await request_limiter.try_acquire():
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": "1"},
                content={"error": {"code": "request_capacity_exhausted"}},
            )
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{stt_url.rstrip('/')}/asr",
                    params={"output": "json", "task": "transcribe"},
                    files={"audio_file": (file.filename or "audio", audio, file.content_type)},
                    timeout=timeout_seconds,
                )
        except httpx.HTTPError:
            return JSONResponse(status_code=502, content={"error": {"code": "stt_unavailable"}})
        finally:
            await request_limiter.release()
        if response.status_code >= 400:
            return JSONResponse(status_code=502, content={"error": {"code": "stt_unavailable"}})
        try:
            payload = response.json()
            text = verify_stt_payload(payload)
        except (ValueError, json.JSONDecodeError):
            return JSONResponse(status_code=502, content={"error": {"code": "stt_incompatible"}})
        return {"text": text}

    @app.post("/v1/audio/speech")
    async def speech(
        body: SpeechRequest, authorization: Annotated[str | None, Header()] = None
    ) -> Response:
        if not authorized(authorization):
            return JSONResponse(
                status_code=401, content={"error": {"code": "authentication_required"}}
            )
        if not await request_limiter.try_acquire():
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": "1"},
                content={"error": {"code": "request_capacity_exhausted"}},
            )
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{tts_url.rstrip('/')}/v1/audio/speech",
                    json=body.model_dump(),
                    timeout=timeout_seconds,
                )
        except httpx.HTTPError:
            return JSONResponse(status_code=502, content={"error": {"code": "tts_unavailable"}})
        finally:
            await request_limiter.release()
        if response.status_code >= 400:
            return JSONResponse(status_code=502, content={"error": {"code": "tts_unavailable"}})
        try:
            content_type = verify_speech_response(
                content_type=response.headers.get("Content-Type", ""),
                content=response.content,
            )
        except VoiceContractError:
            return JSONResponse(status_code=502, content={"error": {"code": "tts_incompatible"}})
        return Response(content=response.content, media_type=content_type)

    return app


def run() -> None:
    app = create_voice_app(
        api_key=os.environ["MORPHEUS_API_KEY"],
        stt_url=os.environ.get("MORPHEUS_STT_URL", "http://stt:9000"),
        tts_url=os.environ.get("MORPHEUS_TTS_URL", "http://tts:8880"),
        max_concurrent_requests=int(os.environ.get("MORPHEUS_MAX_CONCURRENT_REQUESTS", "4")),
        max_requests_per_minute=int(os.environ.get("MORPHEUS_MAX_REQUESTS_PER_MINUTE", "60")),
    )
    host = os.environ.get("MORPHEUS_BIND_ADDRESS", "127.0.0.1")
    uvicorn.run(app, host=host, port=7420, access_log=False)
