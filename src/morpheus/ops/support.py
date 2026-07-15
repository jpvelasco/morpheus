from __future__ import annotations

import hashlib
import json
import os
import zipfile
from pathlib import Path
from typing import Any

from morpheus.core.redaction import redact


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, indent=2, sort_keys=True).encode() + b"\n"


class SupportBundleBuilder:
    def build(
        self,
        destination: Path,
        *,
        version: str,
        configuration: dict[str, Any],
        health: dict[str, Any],
        errors: list[dict[str, Any]],
    ) -> Path:
        safe_errors = [
            {
                key: value
                for key, value in error.items()
                if key in {"code", "safe_summary", "occurred_at", "request_id"}
            }
            for error in errors[-100:]
        ]
        files = {
            "configuration.json": _json_bytes(redact(configuration)),
            "errors.json": _json_bytes(redact(safe_errors)),
            "health.json": _json_bytes(redact(health)),
        }
        manifest = {
            "format": 1,
            "version": version,
            "files": {name: hashlib.sha256(content).hexdigest() for name, content in files.items()},
        }
        files["manifest.json"] = _json_bytes(manifest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.tmp")
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for name, content in sorted(files.items()):
                bundle.writestr(name, content)
        os.replace(temporary, destination)
        return destination
