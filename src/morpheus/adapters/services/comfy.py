from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

import httpx


class ComfyContractError(ValueError):
    """ComfyUI returned an incompatible or unsafe API contract."""


@dataclass(frozen=True, slots=True)
class ComfyOutput:
    filename: str
    subfolder: str
    kind: str


_IDENTIFIER = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _safe_relative(value: str, *, allow_empty: bool) -> bool:
    if not value:
        return allow_empty
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts and "\x00" not in value


class ComfyClient:
    def __init__(
        self,
        *,
        base_url: str,
        client: httpx.AsyncClient,
        timeout_seconds: float = 120,
        max_image_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client
        self._timeout = timeout_seconds
        self._max_image_bytes = max_image_bytes

    async def queue(self, workflow: dict[str, Any]) -> str:
        if not workflow:
            raise ValueError("ComfyUI workflow cannot be empty")
        response = await self._client.post(
            f"{self._base_url}/prompt",
            json={"prompt": workflow},
            timeout=self._timeout,
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except json.JSONDecodeError as error:
            raise ComfyContractError("queue response is not JSON") from error
        prompt_id = payload.get("prompt_id") if isinstance(payload, dict) else None
        if not isinstance(prompt_id, str) or not _IDENTIFIER.fullmatch(prompt_id):
            raise ComfyContractError("queue response does not contain a safe prompt_id")
        return prompt_id

    async def outputs(self, prompt_id: str) -> tuple[ComfyOutput, ...]:
        if not _IDENTIFIER.fullmatch(prompt_id):
            raise ValueError("prompt_id is invalid")
        response = await self._client.get(
            f"{self._base_url}/history/{prompt_id}", timeout=self._timeout
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except json.JSONDecodeError as error:
            raise ComfyContractError("history response is not JSON") from error
        try:
            nodes = payload[prompt_id]["outputs"]
        except (KeyError, TypeError) as error:
            raise ComfyContractError("history response has no outputs") from error
        if not isinstance(nodes, dict):
            raise ComfyContractError("history outputs must be an object")
        result: list[ComfyOutput] = []
        for node in nodes.values():
            if not isinstance(node, dict):
                continue
            images = node.get("images", [])
            if not isinstance(images, list):
                raise ComfyContractError("history images must be a list")
            for image in images:
                if not isinstance(image, dict):
                    raise ComfyContractError("history image must be an object")
                filename = image.get("filename")
                subfolder = image.get("subfolder", "")
                kind = image.get("type", "output")
                if (
                    not isinstance(filename, str)
                    or not isinstance(subfolder, str)
                    or not isinstance(kind, str)
                ):
                    raise ComfyContractError("history image fields are incompatible")
                if not _safe_relative(filename, allow_empty=False) or "/" in filename:
                    raise ComfyContractError("unsafe output filename")
                if not _safe_relative(subfolder, allow_empty=True):
                    raise ComfyContractError("unsafe output subfolder")
                result.append(ComfyOutput(filename=filename, subfolder=subfolder, kind=kind))
        return tuple(result)

    async def image(self, output: ComfyOutput) -> bytes:
        response = await self._client.get(
            f"{self._base_url}/view",
            params={
                "filename": output.filename,
                "subfolder": output.subfolder,
                "type": output.kind,
            },
            timeout=self._timeout,
        )
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0]
        if not content_type.startswith("image/") or not response.content:
            raise ComfyContractError("ComfyUI output is not an image")
        if len(response.content) > self._max_image_bytes:
            raise ComfyContractError("ComfyUI output exceeds the configured limit")
        return response.content
