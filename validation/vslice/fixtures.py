from __future__ import annotations

import time
from pathlib import Path

from morpheus.core.records import DeploymentPlan
from validation.vslice.harness import VSliceError

FIXTURE_TEXT = "tcp establishes a reliable ordered connection between two hosts."


class FakeServerHandle:
    def __init__(self, plan_id: str, name: str, ordinal: int) -> None:
        self.plan_id = plan_id
        self.name = name
        self.ordinal = ordinal
        self.children: tuple[str, ...] = ()


class FakeVSliceEnvironment:
    """Deterministic offline environment; the fixture lane never touches Docker."""

    def __init__(
        self,
        *,
        artifact_digest_override: str | None = None,
        fail_download_after_bytes: int | None = None,
        disk_free_bytes_value: int | None = None,
        startup_healthy: bool = True,
        startup_slow: bool = False,
        fail_health_on_b: bool = False,
        slow_decode: bool = False,
        fail_restore: bool = False,
        spawn_extra_processes: int = 0,
    ) -> None:
        self._digest_override = artifact_digest_override
        self._fail_download_after_bytes = fail_download_after_bytes
        self._disk_free = disk_free_bytes_value
        self._startup_healthy = startup_healthy
        self._startup_slow = startup_slow
        self._fail_health_on_b = fail_health_on_b
        self._slow_decode = slow_decode
        self._fail_restore = fail_restore
        self._extra_processes = spawn_extra_processes
        self.downloaded = 0
        self.started = 0
        self.stopped = 0
        self._handles: list[FakeServerHandle] = []
        self._start_counts: dict[str, int] = {}

    def artifact_digest(self, path: Path) -> str:
        if not path.exists():
            raise VSliceError(f"artifact {path} is missing")
        if self._digest_override is not None:
            return self._digest_override
        return "1" * 64 if path.name == "model.gguf" else "2" * 64

    def download_artifact(self, source: str, digest: str, destination: Path) -> None:
        self.downloaded += 1
        if self._fail_download_after_bytes is not None and self.downloaded == 1:
            destination.unlink(missing_ok=True)
            raise VSliceError("download interrupted mid-transfer")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"x" * 32)

    def disk_free_bytes(self, root: Path) -> int:
        if self._disk_free is not None:
            return self._disk_free
        return 2 * 1024**3

    def start_server(
        self, plan: DeploymentPlan, workdir: Path, ready_url: str, timeout_s: float
    ) -> FakeServerHandle:
        if self._startup_slow:
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                time.sleep(0.05)
            raise VSliceError("server did not become ready within the startup timeout")
        self.started += 1
        ordinal = self._start_counts.get(plan.plan_id, 0) + 1
        self._start_counts[plan.plan_id] = ordinal
        handle = FakeServerHandle(
            plan_id=plan.plan_id, name=f"morpheus-vslice-{self.started}", ordinal=ordinal
        )
        handle.children = tuple(
            f"{handle.name}-child-{index}" for index in range(self._extra_processes)
        )
        self._handles.append(handle)
        return handle

    def stop_server(self, handle: object) -> None:
        self.stopped += 1
        if isinstance(handle, FakeServerHandle):
            self._handles = [item for item in self._handles if item is not handle]

    def http_health(self, handle: object) -> bool:
        assert isinstance(handle, FakeServerHandle)
        if not self._startup_healthy:
            return False
        if self._fail_restore:
            return not (handle.plan_id == "plan-vslice-libri-q4-a" and handle.ordinal == 2)
        if self._fail_health_on_b:
            return handle.plan_id != "plan-vslice-libri-q4-b"
        return True

    def chat_completion(self, handle: object, prompt: str, max_tokens: int) -> tuple[str, float]:
        assert isinstance(handle, FakeServerHandle)
        time.sleep(0.1)
        if self._slow_decode:
            time.sleep(1.5)
            return FIXTURE_TEXT, 1.6
        return FIXTURE_TEXT, 0.25

    def list_owned_processes(self, marker: str) -> tuple[str, ...]:
        names: list[str] = []
        for handle in self._handles:
            names.extend(handle.children)
        return tuple(names)

    def owned_processes(self) -> tuple[str, ...]:
        names: list[str] = []
        for handle in self._handles:
            names.append(handle.name)
            names.extend(handle.children)
        return tuple(names)

    def snapshot_external(self) -> str:
        return "external-state:unchanged"
