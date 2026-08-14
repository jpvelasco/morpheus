from __future__ import annotations

import hashlib
import shutil
import subprocess
import time
from pathlib import Path

import httpx

from morpheus.core.records import DeploymentPlan
from validation.vslice.harness import VSliceError, render_command

ENGINE_SOURCE = (
    "https://github.com/ggml-org/llama.cpp/releases/download/b10400/"
    "llama-b10400-bin-ubuntu-x64.tar.gz"
)
MODEL_SOURCE = (
    "https://huggingface.co/bartowski/SmolLM2-135M-Instruct-GGUF/resolve/"
    "f0a2b81d63eb57be0e90e82e327e03a7fc66a7dc/SmolLM2-135M-Instruct-Q4_K_M.gguf"
)
MODEL_DIGEST = "2e8040ceae7815abe0dcb3540b9995eaa1fa0d2ca9e797d0a635ae4433c68c2d"

IMAGE_REF = (
    "morpheus/vslice-runtime@"
    "sha256:64a2f90ec51d971f13b1fdb0f735e18bc78c4b40cfe17b404041224e33a101b8"
)
CACHE_MOUNT = "/opt/morpheus-cache"
MODEL_MOUNT = f"{CACHE_MOUNT}/model.gguf"
ENGINE_MOUNT = f"{CACHE_MOUNT}/engine/llama-b10400/llama-server"
OWNED_LABEL = "morpheus.vslice=owned"

MOUNT_SOURCE = "cache"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class DockerEnvironment:
    """Disposable Ubuntu container lane for the real CPU walking slice."""

    def __init__(self, cache_root: Path, docker: str = "docker") -> None:
        self.cache_root = cache_root
        self.docker = docker
        self._ports: dict[str, int] = {}
        self._containers: list[str] = []
        self._check_docker()

    def _run(
        self, *args: str, check: bool = True, timeout: int = 120
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(  # noqa: S603  # fixed arg lists only; never a shell
            [self.docker, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if check and result.returncode != 0:
            raise VSliceError(
                f"docker {' '.join(args)} failed: {result.stderr.strip() or result.stdout.strip()}"
            )
        return result

    def image_present(self, reference: str) -> bool:
        return (
            self._run("image", "inspect", "--format", "{{.Id}}", reference, check=False).returncode
            == 0
        )

    def _check_docker(self) -> None:
        self._run("version", "--format", "{{.Server.Version}}")

    def artifact_digest(self, path: Path) -> str:
        if not path.exists():
            raise VSliceError(f"artifact {path} is missing")
        return sha256_of(path)

    def download_artifact(self, source: str, digest: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".part")
        with httpx.stream("GET", source, follow_redirects=True, timeout=600) as response:
            response.raise_for_status()
            with temporary.open("wb") as handle:
                for chunk in response.iter_bytes():
                    handle.write(chunk)
        if digest and sha256_of(temporary) != digest:
            temporary.unlink(missing_ok=True)
            raise VSliceError(f"downloaded artifact digest mismatch for {source}")
        temporary.replace(destination)

    def disk_free_bytes(self, root: Path) -> int:
        return shutil.disk_usage(root).free

    def start_server(
        self, plan: DeploymentPlan, workdir: Path, ready_url: str, timeout_s: float
    ) -> str:
        port = plan.ports[0]
        name = f"morpheus-vslice-{plan.plan_id}"
        command = list(render_command(plan))
        command[0] = ENGINE_MOUNT
        if "--host" in command:
            # Container-internal bind only; host exposure is loopback-only via -p.
            command[command.index("--host") + 1] = "0.0.0.0"  # noqa: S104
        self._run(
            "run",
            "-d",
            "--name",
            name,
            "--label",
            OWNED_LABEL,
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--read-only",
            "--tmpfs",
            "/tmp:size=64m",  # noqa: S108  # bounded disposable tmpfs inside the slice container
            "-p",
            f"127.0.0.1:{port}:{port}",
            "-v",
            f"{self.cache_root / MOUNT_SOURCE}:{CACHE_MOUNT}:ro",
            IMAGE_REF,
            *command,
        )
        self._containers.append(name)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                if httpx.get(ready_url, timeout=2).status_code == 200:
                    self._ports[name] = port
                    return name
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        self.stop_server(name)
        raise VSliceError("server did not become ready within the startup timeout")

    def stop_server(self, handle: object) -> None:
        name = str(handle)
        for _ in range(3):
            self._run("rm", "-f", name, check=False)
            if not self._run("container", "inspect", name, check=False, timeout=30).stdout:
                break
            time.sleep(1)
        self._ports.pop(name, None)
        if name in self._containers:
            self._containers.remove(name)

    def http_health(self, handle: object) -> bool:
        name = str(handle)
        port = self._ports.get(name)
        if port is None:
            return False
        try:
            return httpx.get(f"http://127.0.0.1:{port}/health", timeout=2).status_code == 200
        except httpx.HTTPError:
            return False

    def chat_completion(self, handle: object, prompt: str, max_tokens: int) -> tuple[str, float]:
        name = str(handle)
        port = self._ports.get(name)
        if port is None:
            raise VSliceError(f"no published port for container {name}")
        started = time.monotonic()
        response = httpx.post(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            json={
                "model": "libri-1",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
            },
            timeout=120,
        )
        elapsed = time.monotonic() - started
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return content, elapsed

    def list_owned_processes(self, marker: str) -> tuple[str, ...]:
        result = self._run("ps", "--filter", f"label={OWNED_LABEL}", "--format", "{{.Names}}")
        return tuple(name for name in result.stdout.splitlines() if name)

    def snapshot_external(self) -> str:
        result = self._run("ps", "-aq", "--format", "{{.ID}} {{.Names}}", check=False)
        return hashlib.sha256(result.stdout.encode()).hexdigest()
