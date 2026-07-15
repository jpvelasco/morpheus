from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from morpheus.adapters.services.comfy import ComfyClient, ComfyContractError, ComfyOutput

pytestmark = pytest.mark.contract
ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = json.loads(
    (ROOT / "tests/fixtures/comfy-smoke-workflow.json").read_text(encoding="utf-8")
)


@pytest.mark.asyncio
async def test_IMG_001_submits_versioned_workflow_and_returns_prompt_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/prompt"
        assert json.loads(request.content)["prompt"] == WORKFLOW
        return httpx.Response(200, json={"prompt_id": "prompt-123", "number": 1})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        prompt_id = await ComfyClient(base_url="http://comfy.test", client=http).queue(WORKFLOW)
    assert prompt_id == "prompt-123"


@pytest.mark.asyncio
async def test_IMG_001_reads_history_and_downloads_safe_output() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/history/prompt-123":
            return httpx.Response(
                200,
                json={
                    "prompt-123": {
                        "outputs": {
                            "9": {
                                "images": [
                                    {"filename": "smoke.png", "subfolder": "", "type": "output"}
                                ]
                            }
                        }
                    }
                },
            )
        assert request.url.params["filename"] == "smoke.png"
        return httpx.Response(200, content=b"\x89PNGfixture", headers={"Content-Type": "image/png"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = ComfyClient(base_url="http://comfy.test", client=http)
        outputs = await client.outputs("prompt-123")
        image = await client.image(outputs[0])
    assert calls == ["/history/prompt-123", "/view"]
    assert image == b"\x89PNGfixture"


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", ["../escape.png", "/etc/passwd", "folder/escape.png"])
async def test_SEC_006_rejects_unsafe_comfy_output_name(filename: str) -> None:
    payload = {
        "prompt": {
            "outputs": {
                "9": {"images": [{"filename": filename, "subfolder": "", "type": "output"}]}
            }
        }
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    async with httpx.AsyncClient(transport=transport) as http:
        with pytest.raises(ComfyContractError, match="unsafe output filename"):
            await ComfyClient(base_url="http://comfy.test", client=http).outputs("prompt")


@pytest.mark.asyncio
async def test_IMG_001_rejects_malformed_queue_contract() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"prompt_id": 7}))
    async with httpx.AsyncClient(transport=transport) as http:
        with pytest.raises(ComfyContractError):
            await ComfyClient(base_url="http://comfy.test", client=http).queue(WORKFLOW)


@pytest.mark.asyncio
async def test_IMG_001_rejects_empty_workflow_before_network() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(ValueError, match="cannot be empty"):
            await ComfyClient(base_url="http://comfy.test", client=http).queue({})
    assert calls == 0


@pytest.mark.asyncio
async def test_IMG_001_rejects_non_json_queue_and_history() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"{"))
    async with httpx.AsyncClient(transport=transport) as http:
        client = ComfyClient(base_url="http://comfy.test", client=http)
        with pytest.raises(ComfyContractError, match="queue response is not JSON"):
            await client.queue(WORKFLOW)
        with pytest.raises(ComfyContractError, match="history response is not JSON"):
            await client.outputs("prompt")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({}, "no outputs"),
        ({"prompt": {"outputs": []}}, "must be an object"),
        ({"prompt": {"outputs": {"1": {"images": {}}}}}, "must be a list"),
        ({"prompt": {"outputs": {"1": {"images": [1]}}}}, "must be an object"),
        (
            {"prompt": {"outputs": {"1": {"images": [{"filename": 4}]}}}},
            "fields are incompatible",
        ),
        (
            {
                "prompt": {
                    "outputs": {
                        "1": {
                            "images": [
                                {"filename": "safe.png", "subfolder": "../escape", "type": "output"}
                            ]
                        }
                    }
                }
            },
            "unsafe output subfolder",
        ),
    ],
)
async def test_IMG_001_rejects_malformed_history_nodes(payload: object, message: str) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    async with httpx.AsyncClient(transport=transport) as http:
        with pytest.raises(ComfyContractError, match=message):
            await ComfyClient(base_url="http://comfy.test", client=http).outputs("prompt")


@pytest.mark.asyncio
async def test_IMG_001_history_ignores_nodes_without_objects() -> None:
    payload = {"prompt": {"outputs": {"ignored": [], "empty": {}}}}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    async with httpx.AsyncClient(transport=transport) as http:
        assert await ComfyClient(base_url="http://comfy.test", client=http).outputs("prompt") == ()


@pytest.mark.asyncio
async def test_IMG_001_rejects_invalid_prompt_id_before_network() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200))
    ) as http:
        with pytest.raises(ValueError, match="prompt_id"):
            await ComfyClient(base_url="http://comfy.test", client=http).outputs("../escape")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "content_type", "limit", "message"),
    [
        (b"{}", "application/json", 100, "not an image"),
        (b"12345", "image/png", 4, "configured limit"),
    ],
)
async def test_IMG_001_rejects_invalid_or_oversized_image(
    content: bytes, content_type: str, limit: int, message: str
) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=content, headers={"Content-Type": content_type})
    )
    async with httpx.AsyncClient(transport=transport) as http:
        client = ComfyClient(base_url="http://comfy.test", client=http, max_image_bytes=limit)
        with pytest.raises(ComfyContractError, match=message):
            await client.image(ComfyOutput(filename="safe.png", subfolder="", kind="output"))
