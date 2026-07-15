from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

BASE_URL = os.environ.get("FIXTURE_BASE_URL", "http://openai:8000").rstrip("/")
AUTHORIZATION = "Bearer morpheus-fixture-key"
PARSED_BASE_URL = urlsplit(BASE_URL)
if PARSED_BASE_URL.scheme != "http" or PARSED_BASE_URL.hostname not in {
    "openai",
    "127.0.0.1",
    "localhost",
}:
    raise ValueError("FIXTURE_BASE_URL must use HTTP and an allowlisted fixture host")


def request(
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    authenticated: bool = False,
) -> tuple[int, bytes]:
    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if authenticated:
        headers["Authorization"] = AUTHORIZATION
    value = Request(  # noqa: S310 - BASE_URL is strictly allowlisted above.
        f"{BASE_URL}{path}", data=body, headers=headers, method=method
    )
    try:
        with urlopen(value, timeout=3) as response:  # noqa: S310
            return response.status, response.read()
    except HTTPError as error:
        return error.code, error.read()


def json_body(body: bytes) -> dict[str, Any]:
    value = json.loads(body)
    if not isinstance(value, dict):
        raise AssertionError("Fixture response must be an object")
    return value


def assert_http_contract() -> None:
    status, body = request("/healthz")
    assert status == 200 and json_body(body) == {"status": "ok"}

    status, body = request("/v1/models", authenticated=True)
    assert status == 200
    assert json_body(body)["data"][0]["id"] == "morpheus-fixture-model"

    chat_request = {
        "model": "morpheus-fixture-model",
        "messages": [{"role": "user", "content": "safe fixture canary"}],
    }
    status, body = request(
        "/v1/chat/completions",
        method="POST",
        payload=chat_request,
        authenticated=True,
    )
    assert status == 200
    assert json_body(body)["choices"][0]["message"]["content"] == "fixture-response"

    status, stream = request(
        "/v1/chat/completions",
        method="POST",
        payload={**chat_request, "stream": True},
        authenticated=True,
    )
    assert status == 200 and b"data: [DONE]" in stream

    status, metrics = request("/metrics")
    assert status == 200 and b"vllm:num_requests_running" in metrics

    status, slow = request("/fixture/slow?delay_ms=25")
    assert status == 200 and json_body(slow)["delay_ms"] == 25

    status, malformed = request("/fixture/malformed")
    assert status == 200
    try:
        json.loads(malformed)
    except json.JSONDecodeError:
        pass
    else:
        raise AssertionError("Malformed fixture returned valid JSON")

    status, unavailable = request("/fixture/unavailable")
    assert status == 503 and json_body(unavailable)["error"]["code"] == "fixture_unavailable"

    status, partial = request("/fixture/partial-stream")
    assert status == 200 and b"fixture-partial" in partial and b"[DONE]" not in partial


def assert_network_isolation() -> None:
    for hostname in ("qwopus-coder", "host.docker.internal"):
        try:
            socket.getaddrinfo(hostname, 8000)
        except socket.gaierror:
            continue
        raise AssertionError(f"Protected hostname unexpectedly resolved: {hostname}")

    try:
        connection = socket.create_connection(("1.1.1.1", 443), timeout=0.5)
    except OSError:
        pass
    else:
        connection.close()
        raise AssertionError("Internal fixture network unexpectedly has public egress")


def assert_read_only_root() -> None:
    try:
        Path("/fixture-write-probe").write_text("unexpected", encoding="utf-8")
    except OSError:
        return
    raise AssertionError("Probe container root filesystem is writable")


def main() -> None:
    assert_http_contract()
    assert_network_isolation()
    assert_read_only_root()
    sys.stdout.write("fixture_probe=passed\n")


if __name__ == "__main__":
    main()
