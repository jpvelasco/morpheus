from __future__ import annotations

import hmac
import json
import os
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

MODEL_ID = "morpheus-fixture-model"
FIXTURE_RESPONSE = "fixture-response"
MAX_BODY_BYTES = 1_048_576


class FixtureServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class FixtureHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "MorpheusFixture/1"

    def log_message(self, format_string: str, *args: object) -> None:
        del format_string, args

    def _send_bytes(
        self,
        status: HTTPStatus,
        body: bytes,
        *,
        content_type: str,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        self._send_bytes(status, body, content_type="application/json")

    def _send_error(self, status: HTTPStatus, code: str, message: str) -> None:
        self._send_json(status, {"error": {"code": code, "message": message}})

    def _authorized(self) -> bool:
        expected = os.environ.get("FIXTURE_API_KEY", "morpheus-fixture-key")
        supplied = self.headers.get("Authorization", "").removeprefix("Bearer ")
        return bool(expected) and hmac.compare_digest(supplied, expected)

    def _require_authentication(self) -> bool:
        if self._authorized():
            return True
        self._send_error(
            HTTPStatus.UNAUTHORIZED,
            "fixture_authentication_required",
            "Fixture authentication is required",
        )
        return False

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path == "/healthz":
            self._send_json(HTTPStatus.OK, {"status": "ok"})
            return
        if parsed.path == "/v1/models":
            if self._require_authentication():
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "object": "list",
                        "data": [
                            {
                                "id": MODEL_ID,
                                "object": "model",
                                "created": 0,
                                "owned_by": "morpheus-validation",
                                "root": "fixture/morpheus-model",
                                "max_model_len": 4096,
                                "aliases": ["fixture-model"],
                            }
                        ],
                    },
                )
            return
        if parsed.path == "/metrics":
            metrics = (
                "# HELP vllm:num_requests_running Number of requests currently running.\n"
                "# TYPE vllm:num_requests_running gauge\n"
                f'vllm:num_requests_running{{model_name="{MODEL_ID}"}} 0\n'
                "# HELP vllm:gpu_cache_usage_perc GPU KV-cache utilization.\n"
                "# TYPE vllm:gpu_cache_usage_perc gauge\n"
                f'vllm:gpu_cache_usage_perc{{model_name="{MODEL_ID}"}} 0.25\n'
            ).encode()
            self._send_bytes(HTTPStatus.OK, metrics, content_type="text/plain; version=0.0.4")
            return
        if parsed.path == "/fixture/slow":
            values = parse_qs(parsed.query).get("delay_ms", ["250"])
            try:
                delay_ms = max(0, min(int(values[0]), 2_000))
            except ValueError:
                self._send_error(
                    HTTPStatus.BAD_REQUEST, "invalid_delay", "delay_ms must be an integer"
                )
                return
            time.sleep(delay_ms / 1_000)
            self._send_json(HTTPStatus.OK, {"status": "slow", "delay_ms": delay_ms})
            return
        if parsed.path == "/fixture/malformed":
            self._send_bytes(HTTPStatus.OK, b'{"broken":', content_type="application/json")
            return
        if parsed.path == "/fixture/unavailable":
            self._send_error(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "fixture_unavailable",
                "Fixture dependency is unavailable",
            )
            return
        if parsed.path == "/fixture/partial-stream":
            event = self._stream_chunk({"content": "fixture-partial"})
            self._send_stream([event])
            return
        self._send_error(HTTPStatus.NOT_FOUND, "fixture_route_not_found", "Fixture route not found")

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/v1/chat/completions":
            self._send_error(
                HTTPStatus.NOT_FOUND, "fixture_route_not_found", "Fixture route not found"
            )
            return
        if not self._require_authentication():
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        if content_length < 1 or content_length > MAX_BODY_BYTES:
            self._send_error(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "invalid_body_size", "Invalid body size"
            )
            return
        try:
            request = json.loads(self.rfile.read(content_length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_error(HTTPStatus.BAD_REQUEST, "invalid_json", "Request body must be JSON")
            return
        if not isinstance(request, dict) or request.get("model") != MODEL_ID:
            self._send_error(
                HTTPStatus.BAD_REQUEST, "fixture_model_unknown", "Fixture model is unknown"
            )
            return
        if request.get("stream") is True:
            self._send_stream(
                [
                    self._stream_chunk({"role": "assistant", "content": ""}),
                    self._stream_chunk({"content": FIXTURE_RESPONSE}),
                    self._stream_chunk({}, finish_reason="stop"),
                    b"data: [DONE]\n\n",
                ]
            )
            return
        self._send_json(
            HTTPStatus.OK,
            {
                "id": "chatcmpl-morpheus-fixture",
                "object": "chat.completion",
                "created": 0,
                "model": MODEL_ID,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": FIXTURE_RESPONSE},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            },
        )

    @staticmethod
    def _stream_chunk(delta: dict[str, str], finish_reason: str | None = None) -> bytes:
        payload = {
            "id": "chatcmpl-morpheus-fixture",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": MODEL_ID,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        }
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        return f"data: {encoded}\n\n".encode()

    def _send_stream(self, events: list[bytes]) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        for event in events:
            self.wfile.write(event)
            self.wfile.flush()
        self.close_connection = True


def main() -> None:
    host = os.environ.get("FIXTURE_BIND_ADDRESS", "127.0.0.1")
    port = int(os.environ.get("FIXTURE_PORT", "8000"))
    FixtureServer((host, port), FixtureHandler).serve_forever()


if __name__ == "__main__":
    main()
