from __future__ import annotations

import argparse
import json
import stat
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from morpheus.config import load_settings


def _request(
    url: str,
    *,
    api_key: str = "",
    payload: dict[str, Any] | None = None,
) -> tuple[int, Mapping[str, str], bytes]:
    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(  # noqa: S310 - caller supplies fixed loopback URLs.
        url, data=body, headers=headers, method="POST" if body else "GET"
    )
    try:
        with urlopen(request, timeout=5) as response:  # noqa: S310 - fixed loopback URLs.
            return response.status, response.headers, response.read()
    except HTTPError as error:
        return error.code, error.headers, error.read()


def _json(body: bytes) -> dict[str, Any]:
    value = json.loads(body)
    if not isinstance(value, dict):
        raise AssertionError("response must be a JSON object")
    return value


def _verify_secret_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise AssertionError("lab environment must be a regular non-symlink file")
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise AssertionError("lab environment must not be accessible by group or other")


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe the isolated Morpheus core stack")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    args = parser.parse_args()
    _verify_secret_file(args.env_file)
    settings = load_settings(env_file=args.env_file)
    api_key = settings.api_key.get_secret_value()
    if not api_key:
        raise AssertionError("lab API key must be configured")

    api = f"http://127.0.0.1:{settings.api_port}"
    dashboard = f"http://127.0.0.1:{settings.dashboard_port}"
    telemetry = "http://127.0.0.1:7410"

    status, _, body = _request(f"{api}/healthz")
    assert status == 200 and _json(body) == {"status": "ok"}

    status, _, body = _request(f"{api}/api/v1/models")
    assert status == 401
    assert _json(body)["error"]["code"] == "authentication_required"

    status, _, body = _request(f"{api}/api/v1/health", api_key=api_key)
    assert status == 200 and _json(body)["health"]["state"] == "ready"

    status, _, body = _request(f"{api}/api/v1/models", api_key=api_key)
    models = _json(body)["models"]
    assert status == 200 and len(models) == 1
    assert models[0]["root"] == "fixture/morpheus-model"
    assert models[0]["aliases"] == ["morpheus-fixture-model"]
    assert models[0]["context_window"] == 4096

    status, headers, body = _request(f"{dashboard}/")
    assert status == 200 and b'<div id="root"></div>' in body
    assert headers.get("X-Frame-Options") == "DENY"
    assert "frame-ancestors 'none'" in headers.get("Content-Security-Policy", "")

    chat = {
        "model": "morpheus-fixture-model",
        "messages": [{"role": "user", "content": "safe validation prompt"}],
    }
    status, _, body = _request(f"{telemetry}/v1/chat/completions", payload=chat)
    assert status == 401
    assert _json(body)["error"]["code"] == "authentication_required"

    status, _, body = _request(f"{telemetry}/v1/chat/completions", api_key=api_key, payload=chat)
    response = _json(body)
    assert status == 200
    assert response["choices"][0]["message"]["content"] == "fixture-response"

    status, headers, body = _request(
        f"{telemetry}/v1/chat/completions",
        api_key=api_key,
        payload={**chat, "stream": True},
    )
    assert status == 200
    assert headers.get_content_type() == "text/event-stream"
    assert b"fixture-response" in body and b"data: [DONE]" in body

    sys.stdout.write("core_smoke=passed\n")


if __name__ == "__main__":
    main()
