from __future__ import annotations

import argparse
import stat
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from morpheus.config import load_settings

CHAT_PATH = "/v1/chat/completions"
MODEL = "morpheus-fixture-model"


def _verify_secret_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise AssertionError("lab environment must be a regular non-symlink file")
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise AssertionError("lab environment must not be accessible by group or other")


def _error_code(response: httpx.Response) -> str:
    payload = response.json()
    if not isinstance(payload, dict):
        raise AssertionError("error response must be a JSON object")
    error = payload.get("error")
    if not isinstance(error, dict) or not isinstance(error.get("code"), str):
        raise AssertionError("error response must contain a stable code")
    return error["code"]


def _chat(*, stream: bool = False, mode: str | None = None, delay_ms: int = 0) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": MODEL,
        "messages": [
            {"role": "user", "content": "morpheus-private-prompt-canary-opt-tel-001"}
        ],
    }
    if stream:
        payload["stream"] = True
    if mode is not None:
        payload["morpheus_fixture_mode"] = mode
    if delay_ms:
        payload["morpheus_fixture_delay_ms"] = delay_ms
    return payload


def _post(
    client: httpx.Client,
    *,
    base_url: str,
    api_key: str,
    payload: dict[str, Any],
) -> httpx.Response:
    return client.post(
        f"{base_url}{CHAT_PATH}",
        headers={"Authorization": f"Bearer {api_key}"},
        json=payload,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe the disposable telemetry profile")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--fixture-port", type=int, default=18000)
    parser.add_argument("--container-mode", action="store_true")
    args = parser.parse_args()
    if args.container_mode:
        if args.env_file is not None:
            raise AssertionError("container mode uses only the container environment")
        settings = load_settings()
        direct = settings.llm_base_url.removesuffix("/v1")
    else:
        env_file = args.env_file or Path(".env")
        _verify_secret_file(env_file)
        if not 1 <= args.fixture_port <= 65_535:
            raise AssertionError("fixture port must be valid")
        settings = load_settings(env_file=env_file)
        direct = f"http://127.0.0.1:{args.fixture_port}"
    api_key = settings.api_key.get_secret_value()
    upstream_api_key = settings.upstream_api_key.get_secret_value()
    if not api_key or not upstream_api_key or api_key == upstream_api_key:
        raise AssertionError("distinct proxy and upstream lab credentials are required")
    if not settings.enable_telemetry:
        raise AssertionError("telemetry must be enabled for this validation lane")
    if settings.request_timeout_seconds > 1.5:
        raise AssertionError("lab upstream timeout must be at most 1.5 seconds")

    proxy = f"http://127.0.0.1:{settings.telemetry_port}"
    timeout_delay_ms = min(2_000, int(settings.request_timeout_seconds * 1_000) + 300)
    cancel_delay_ms = min(2_000, int(settings.request_timeout_seconds * 1_000) + 500)

    with (
        httpx.Client(timeout=5, trust_env=False) as direct_client,
        httpx.Client(timeout=5, trust_env=False) as proxy_client,
    ):
        unauthorized = proxy_client.post(f"{proxy}{CHAT_PATH}", json=_chat())
        assert unauthorized.status_code == 401
        assert _error_code(unauthorized) == "authentication_required"

        direct_nonstream = _post(
            direct_client,
            base_url=direct,
            api_key=upstream_api_key,
            payload=_chat(),
        )
        proxied_nonstream = _post(
            proxy_client,
            base_url=proxy,
            api_key=api_key,
            payload=_chat(),
        )
        assert direct_nonstream.status_code == proxied_nonstream.status_code == 200
        assert direct_nonstream.content == proxied_nonstream.content
        usage = proxied_nonstream.json()["usage"]
        assert usage == {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}

        direct_stream = _post(
            direct_client,
            base_url=direct,
            api_key=upstream_api_key,
            payload=_chat(stream=True),
        )
        proxied_stream = _post(
            proxy_client,
            base_url=proxy,
            api_key=api_key,
            payload=_chat(stream=True),
        )
        assert direct_stream.status_code == proxied_stream.status_code == 200
        assert direct_stream.content == proxied_stream.content
        assert b"data: [DONE]" in proxied_stream.content

        direct_unavailable = _post(
            direct_client,
            base_url=direct,
            api_key=upstream_api_key,
            payload=_chat(mode="unavailable"),
        )
        proxied_unavailable = _post(
            proxy_client,
            base_url=proxy,
            api_key=api_key,
            payload=_chat(mode="unavailable"),
        )
        assert direct_unavailable.status_code == 503
        assert _error_code(direct_unavailable) == "fixture_unavailable"
        assert proxied_unavailable.status_code == 502
        assert _error_code(proxied_unavailable) == "upstream_http_error"

        direct_empty = _post(
            direct_client,
            base_url=direct,
            api_key=upstream_api_key,
            payload=_chat(stream=True, mode="empty_stream"),
        )
        proxied_empty = _post(
            proxy_client,
            base_url=proxy,
            api_key=api_key,
            payload=_chat(stream=True, mode="empty_stream"),
        )
        assert direct_empty.status_code == 200 and direct_empty.content == b""
        assert proxied_empty.status_code == 502
        assert _error_code(proxied_empty) == "upstream_contract_error"

        direct_slow = _post(
            direct_client,
            base_url=direct,
            api_key=upstream_api_key,
            payload=_chat(mode="slow", delay_ms=timeout_delay_ms),
        )
        proxied_slow = _post(
            proxy_client,
            base_url=proxy,
            api_key=api_key,
            payload=_chat(mode="slow", delay_ms=timeout_delay_ms),
        )
        assert direct_slow.status_code == 200
        assert proxied_slow.status_code == 504
        assert _error_code(proxied_slow) == "upstream_timeout"

        with proxy_client.stream(
            "POST",
            f"{proxy}{CHAT_PATH}",
            headers={"Authorization": f"Bearer {api_key}"},
            json=_chat(stream=True, mode="slow_stream", delay_ms=cancel_delay_ms),
        ) as canceled:
            assert canceled.status_code == 200
            first_chunk = next(canceled.iter_raw())
            assert b"fixture-partial" in first_chunk

        deadline = time.monotonic() + settings.request_timeout_seconds + 2
        while True:
            after_cancel = _post(
                proxy_client,
                base_url=proxy,
                api_key=api_key,
                payload=_chat(),
            )
            if after_cancel.status_code == 200:
                break
            assert after_cancel.status_code == 429
            assert _error_code(after_cancel) == "request_capacity_exhausted"
            if time.monotonic() >= deadline:
                raise AssertionError("canceled stream did not release its request slot")
            time.sleep(0.05)

        bypass = _post(
            direct_client,
            base_url=direct,
            api_key=upstream_api_key,
            payload=_chat(),
        )
        assert bypass.status_code == 200
        assert bypass.content == direct_nonstream.content

    sys.stdout.write("telemetry_smoke=passed\n")


if __name__ == "__main__":
    main()
