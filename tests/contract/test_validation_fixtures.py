from __future__ import annotations

import importlib.util
import json
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
import yaml

pytestmark = pytest.mark.contract
ROOT = Path(__file__).resolve().parents[2]
AUTH = {"Authorization": "Bearer morpheus-fixture-key"}

SERVER_PATH = ROOT / "validation" / "fixtures" / "server.py"
SERVER_SPEC = importlib.util.spec_from_file_location("morpheus_fixture_server", SERVER_PATH)
assert SERVER_SPEC is not None and SERVER_SPEC.loader is not None
SERVER_MODULE = importlib.util.module_from_spec(SERVER_SPEC)
SERVER_SPEC.loader.exec_module(SERVER_MODULE)
FixtureHandler = SERVER_MODULE.FixtureHandler
FixtureServer = SERVER_MODULE.FixtureServer


@contextmanager
def running_fixture() -> Iterator[str]:
    server = FixtureServer(("127.0.0.1", 0), FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_models_and_chat_are_authenticated_and_deterministic() -> None:
    with running_fixture() as base_url:
        unauthorized = httpx.get(f"{base_url}/v1/models")
        models = httpx.get(f"{base_url}/v1/models", headers=AUTH)
        chat = httpx.post(
            f"{base_url}/v1/chat/completions",
            headers=AUTH,
            json={
                "model": "morpheus-fixture-model",
                "messages": [{"role": "user", "content": "safe canary prompt"}],
            },
        )

    assert unauthorized.status_code == 401
    assert unauthorized.json()["error"]["code"] == "fixture_authentication_required"
    assert models.status_code == 200
    assert models.json() == {
        "object": "list",
        "data": [
            {
                "id": "morpheus-fixture-model",
                "object": "model",
                "created": 0,
                "owned_by": "morpheus-validation",
                "root": "fixture/morpheus-model",
                "max_model_len": 4096,
                "aliases": ["fixture-model"],
            }
        ],
    }
    assert chat.status_code == 200
    assert chat.json() == {
        "id": "chatcmpl-morpheus-fixture",
        "object": "chat.completion",
        "created": 0,
        "model": "morpheus-fixture-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "fixture-response"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
    }


def test_streaming_and_metrics_are_stable() -> None:
    with running_fixture() as base_url:
        response = httpx.post(
            f"{base_url}/v1/chat/completions",
            headers=AUTH,
            json={
                "model": "morpheus-fixture-model",
                "messages": [{"role": "user", "content": "stream"}],
                "stream": True,
            },
        )
        metrics = httpx.get(f"{base_url}/metrics")

    events = [line.removeprefix("data: ") for line in response.text.splitlines() if line]
    assert response.status_code == 200
    assert events[-1] == "[DONE]"
    chunks = [json.loads(event) for event in events[:-1]]
    assert [chunk["choices"][0]["delta"] for chunk in chunks] == [
        {"role": "assistant", "content": ""},
        {"content": "fixture-response"},
        {},
    ]
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
    assert metrics.status_code == 200
    assert 'vllm:num_requests_running{model_name="morpheus-fixture-model"} 0' in metrics.text
    assert 'vllm:gpu_cache_usage_perc{model_name="morpheus-fixture-model"} 0.25' in metrics.text


def test_fault_fixtures_cover_slow_malformed_unavailable_and_partial_stream() -> None:
    with running_fixture() as base_url:
        started = time.monotonic()
        slow = httpx.get(f"{base_url}/fixture/slow?delay_ms=50")
        elapsed = time.monotonic() - started
        malformed = httpx.get(f"{base_url}/fixture/malformed")
        unavailable = httpx.get(f"{base_url}/fixture/unavailable")
        partial = httpx.get(f"{base_url}/fixture/partial-stream")

    assert slow.json() == {"status": "slow", "delay_ms": 50}
    assert elapsed >= 0.04
    assert malformed.status_code == 200
    with pytest.raises(json.JSONDecodeError):
        malformed.json()
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "fixture_unavailable"
    assert partial.status_code == 200
    assert "fixture-partial" in partial.text
    assert "[DONE]" not in partial.text


def test_fixture_compose_is_hardened_internal_and_loopback_only() -> None:
    compose = yaml.safe_load(
        (ROOT / "validation" / "fixtures" / "compose.yaml").read_text(encoding="utf-8")
    )
    service = compose["services"]["openai"]

    assert compose["name"] == "morpheus-validation-fixtures"
    assert "ports" not in service
    assert service["expose"] == ["8000"]
    assert service["networks"] == ["fixture_external"]
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert service["tmpfs"] == ["/tmp:size=16m,mode=1777"]  # noqa: S108
    assert service["environment"]["FIXTURE_API_KEY"] == "morpheus-fixture-key"
    assert service["logging"]["options"] == {
        "max-size": "1m",
        "max-file": "1",
        "compress": "false",
    }
    assert compose["networks"]["fixture_external"]["internal"] is True
    rendered = json.dumps(compose)
    assert "ai_default" not in rendered
    assert "history-coder" not in rendered
    assert "host.docker.internal" not in rendered


def test_fixture_image_is_pinned_and_non_root() -> None:
    expected_base = (
        "python:3.12.11-slim@"
        "sha256:47ae396f09c1303b8653019811a8498470603d7ffefc29cb07c88f1f8cb3d19f"
    )
    dockerfiles = [
        ROOT / "deploy" / "Dockerfile",
        ROOT / "web" / "Dockerfile",
        ROOT / "validation" / "fixtures" / "Dockerfile",
    ]
    for path in dockerfiles:
        assert expected_base in path.read_text(encoding="utf-8")

    lock = json.loads((ROOT / "deploy" / "images.lock.json").read_text(encoding="utf-8"))
    python_image = next(image for image in lock["images"] if image["name"] == "python-runtime")
    assert python_image["version"] == "3.12.11-slim"
    assert python_image["digest"] == expected_base.rsplit("@", 1)[1]
    assert python_image["platform"] == "linux/amd64"
    assert python_image["status"] == "pull-and-build-verified"

    dockerfile = dockerfiles[-1].read_text(encoding="utf-8")
    assert "USER fixture" in dockerfile
    assert "COPY --chown=fixture:fixture server.py /app/server.py" in dockerfile


def test_fixture_probe_checks_contracts_and_network_isolation() -> None:
    probe = (ROOT / "validation" / "fixtures" / "probe.py").read_text(encoding="utf-8")

    for path in (
        "/v1/models",
        "/v1/chat/completions",
        "/metrics",
        "/fixture/slow",
        "/fixture/malformed",
        "/fixture/unavailable",
        "/fixture/partial-stream",
    ):
        assert path in probe
    assert "history-coder" in probe
    assert "host.docker.internal" in probe
    assert "1.1.1.1" in probe
    assert "fixture_probe=passed" in probe
