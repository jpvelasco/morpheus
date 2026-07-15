from __future__ import annotations

import hmac
import os
from typing import Annotated, Any

import httpx
import uvicorn
from fastapi import FastAPI, File, Header, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field


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
) -> FastAPI:
    if not api_key:
        raise ValueError("voice gateway requires an API key")
    app = FastAPI(title="Morpheus Voice Gateway", docs_url=None, redoc_url=None)

    def authorized(header: str | None) -> bool:
        supplied = (header or "").removeprefix("Bearer ")
        return hmac.compare_digest(supplied, api_key)

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
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{stt_url.rstrip('/')}/asr",
                params={"output": "json", "task": "transcribe"},
                files={"audio_file": (file.filename or "audio", audio, file.content_type)},
                timeout=timeout_seconds,
            )
        if response.status_code >= 400:
            return JSONResponse(status_code=502, content={"error": {"code": "stt_unavailable"}})
        payload = response.json()
        text = payload.get("text") if isinstance(payload, dict) else None
        if not isinstance(text, str):
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
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{tts_url.rstrip('/')}/v1/audio/speech",
                json=body.model_dump(),
                timeout=timeout_seconds,
            )
        if response.status_code >= 400:
            return JSONResponse(status_code=502, content={"error": {"code": "tts_unavailable"}})
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0]
        if not content_type.startswith("audio/") or not response.content:
            return JSONResponse(status_code=502, content={"error": {"code": "tts_incompatible"}})
        return Response(content=response.content, media_type=content_type)

    return app


def run() -> None:
    app = create_voice_app(
        api_key=os.environ["MORPHEUS_API_KEY"],
        stt_url=os.environ.get("MORPHEUS_STT_URL", "http://stt:9000"),
        tts_url=os.environ.get("MORPHEUS_TTS_URL", "http://tts:8880"),
    )
    host = os.environ.get("MORPHEUS_BIND_ADDRESS", "127.0.0.1")
    uvicorn.run(app, host=host, port=7420, access_log=False)
