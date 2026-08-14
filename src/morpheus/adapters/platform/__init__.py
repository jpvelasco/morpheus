"""Native platform adapter selection for PLAT-002."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from morpheus.adapters.platform.base import bounded_service_name  # noqa: F401
from morpheus.adapters.platform.darwin import (
    DarwinDurableReplacement,
    DarwinHardwareTelemetry,
    DarwinOwnedPath,
    DarwinProcessSupervision,
    DarwinSecretStore,
    DarwinServiceLifecycle,
)
from morpheus.adapters.platform.posix import (
    PosixDurableReplacement,
    PosixHardwareTelemetry,
    PosixOwnedPath,
    PosixProcessSupervision,
    PosixSecretStore,
    PosixServiceLifecycle,
)
from morpheus.adapters.platform.windows import (
    WindowsDurableReplacement,
    WindowsHardwareTelemetry,
    WindowsOwnedPath,
    WindowsProcessSupervision,
    WindowsSecretStore,
    WindowsServiceLifecycle,
)
from morpheus.ports.platform import (
    DurableReplacementPort,
    HardwareTelemetryPort,
    OwnedPathPort,
    ProcessSupervisionPort,
    SecretStorePort,
    ServiceLifecyclePort,
)


@dataclass(frozen=True)
class PlatformPorts:
    """Bundled native adapters behind the typed PLAT-002 ports."""

    owned_path: OwnedPathPort
    secret_store: Callable[[Path], SecretStorePort]
    process_supervision: ProcessSupervisionPort
    service_lifecycle: ServiceLifecyclePort
    durable_replacement: DurableReplacementPort
    telemetry: HardwareTelemetryPort


def platform_ports(platform: str = sys.platform) -> PlatformPorts:
    """Select the native adapter bundle for the running platform."""
    if platform == "win32":
        return PlatformPorts(
            owned_path=WindowsOwnedPath(),
            secret_store=WindowsSecretStore,
            process_supervision=WindowsProcessSupervision(),
            service_lifecycle=WindowsServiceLifecycle(),
            durable_replacement=WindowsDurableReplacement(),
            telemetry=WindowsHardwareTelemetry(),
        )
    if platform == "darwin":
        return PlatformPorts(
            owned_path=DarwinOwnedPath(),
            secret_store=DarwinSecretStore,
            process_supervision=DarwinProcessSupervision(),
            service_lifecycle=DarwinServiceLifecycle(),
            durable_replacement=DarwinDurableReplacement(),
            telemetry=DarwinHardwareTelemetry(),
        )
    return PlatformPorts(
        owned_path=PosixOwnedPath(),
        secret_store=PosixSecretStore,
        process_supervision=PosixProcessSupervision(),
        service_lifecycle=PosixServiceLifecycle(),
        durable_replacement=PosixDurableReplacement(),
        telemetry=PosixHardwareTelemetry(),
    )
