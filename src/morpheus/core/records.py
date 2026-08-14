from __future__ import annotations

import json
import re
from dataclasses import dataclass, fields, is_dataclass
from typing import Any, get_args, get_origin, get_type_hints

CURRENT_SCHEMA_VERSION = 1

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DISPLAY_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._+-]{0,127}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ABSOLUTE_PATH = re.compile(r"^/[^;$\n]{1,511}$")
_SETTING_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SETTING_TEXT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_QUANTIZATION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")


class UnknownRecordTypeError(ValueError):
    pass


class SchemaVersionError(ValueError):
    pass


def _bounded(value: str, pattern: re.Pattern[str], field: str) -> str:
    if not pattern.fullmatch(value):
        raise ValueError(f"{field} must be a bounded identifier")
    return value


def _digest(value: str, field: str) -> str:
    if not _DIGEST.fullmatch(value):
        raise ValueError(f"{field} must be a sha256 digest")
    return value


def _path(value: str, field: str) -> str:
    if not _ABSOLUTE_PATH.fullmatch(value):
        raise ValueError(f"{field} must be an absolute path without shell metacharacters")
    return value


@dataclass(frozen=True, slots=True)
class MachineProfile:
    machine_id: str
    platform: str
    architecture: str
    accelerator: str
    memory_bytes: int
    disk_bytes: int
    schema_version: int = CURRENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _bounded(self.machine_id, _IDENTIFIER, "machine_id")
        _bounded(self.platform, _IDENTIFIER, "platform")
        _bounded(self.architecture, _IDENTIFIER, "architecture")
        _bounded(self.accelerator, _IDENTIFIER, "accelerator")
        if self.memory_bytes < 0 or self.disk_bytes < 0:
            raise ValueError("capacity estimates cannot be negative")

    @property
    def record_id(self) -> str:
        return self.machine_id

    def public_dict(self) -> dict[str, Any]:
        return {
            "machine_id": self.machine_id,
            "platform": self.platform,
            "architecture": self.architecture,
            "accelerator": self.accelerator,
            "memory_bytes": self.memory_bytes,
            "disk_bytes": self.disk_bytes,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class ModelIdentity:
    model_id: str
    revision: str
    artifact_digest: str
    model_format: str
    quantization: str
    license_id: str
    source: str
    schema_version: int = CURRENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _bounded(self.model_id, _IDENTIFIER, "model_id")
        _bounded(self.revision, _IDENTIFIER, "revision")
        _digest(self.artifact_digest, "artifact_digest")
        _bounded(self.model_format, _IDENTIFIER, "model_format")
        _bounded(self.quantization, _QUANTIZATION, "quantization")
        _bounded(self.license_id, _IDENTIFIER, "license_id")
        _bounded(self.source, _IDENTIFIER, "source")

    @property
    def record_id(self) -> str:
        return self.model_id

    def public_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "revision": self.revision,
            "artifact_digest": self.artifact_digest,
            "model_format": self.model_format,
            "quantization": self.quantization,
            "license_id": self.license_id,
            "source": self.source,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class EngineIdentity:
    engine_id: str
    kind: str
    artifact_digest: str
    platforms: tuple[str, ...]
    schema_version: int = CURRENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _bounded(self.engine_id, _IDENTIFIER, "engine_id")
        _bounded(self.kind, _IDENTIFIER, "kind")
        _digest(self.artifact_digest, "artifact_digest")
        if not self.platforms:
            raise ValueError("platforms must name at least one supported platform")
        for platform in self.platforms:
            _bounded(platform, _IDENTIFIER, "platforms")

    @property
    def record_id(self) -> str:
        return self.engine_id

    def public_dict(self) -> dict[str, Any]:
        return {
            "engine_id": self.engine_id,
            "kind": self.kind,
            "artifact_digest": self.artifact_digest,
            "platforms": list(self.platforms),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class WorkloadProfile:
    workload_id: str
    developer_profile: str
    context_tokens: int
    max_concurrency: int
    required_features: tuple[str, ...]
    schema_version: int = CURRENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _bounded(self.workload_id, _IDENTIFIER, "workload_id")
        _bounded(self.developer_profile, _IDENTIFIER, "developer_profile")
        if self.context_tokens < 0 or self.max_concurrency < 1:
            raise ValueError("workload limits must be positive")
        for feature in self.required_features:
            _bounded(feature, _IDENTIFIER, "required_features")

    @property
    def record_id(self) -> str:
        return self.workload_id

    def public_dict(self) -> dict[str, Any]:
        return {
            "workload_id": self.workload_id,
            "developer_profile": self.developer_profile,
            "context_tokens": self.context_tokens,
            "max_concurrency": self.max_concurrency,
            "required_features": list(self.required_features),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class DeploymentPlan:
    plan_id: str
    model: ModelIdentity
    engine: EngineIdentity
    workload: WorkloadProfile
    settings: tuple[tuple[str, str | int | float | bool], ...]
    served_aliases: tuple[str, ...]
    context_tokens: int
    max_concurrency: int
    cache_policy: str
    memory_estimate_bytes: int
    disk_estimate_bytes: int
    owned_paths: tuple[str, ...]
    ports: tuple[int, ...]
    health_contract_id: str
    benchmark_gate_id: str
    rollback_target_plan_id: str | None
    source_evidence_digest: str
    schema_version: int = CURRENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _bounded(self.plan_id, _IDENTIFIER, "plan_id")
        if not isinstance(self.model, ModelIdentity) or not isinstance(self.engine, EngineIdentity):
            raise ValueError("plan must bind exact model and engine identities")
        if not isinstance(self.workload, WorkloadProfile):
            raise ValueError("plan must bind an exact workload profile")
        if not self.settings:
            raise ValueError("plan settings cannot be empty")
        seen: set[str] = set()
        for key, value in self.settings:
            if not _SETTING_NAME.fullmatch(key):
                raise ValueError(f"setting name {key!r} is not bounded")
            if key in seen:
                raise ValueError("plan settings cannot contain duplicate keys")
            seen.add(key)
            if isinstance(value, str):
                if not _SETTING_TEXT.fullmatch(value):
                    raise ValueError(f"setting value for {key!r} is not bounded")
            elif not isinstance(value, int | float | bool):
                raise ValueError(f"setting value for {key!r} must be a typed scalar")
        if not self.served_aliases:
            raise ValueError("plan must serve at least one alias")
        for alias in self.served_aliases:
            _bounded(alias, _IDENTIFIER, "served_aliases")
        if self.context_tokens < 0 or self.max_concurrency < 1:
            raise ValueError("plan limits must be positive")
        _bounded(self.cache_policy, _IDENTIFIER, "cache_policy")
        if self.memory_estimate_bytes < 0 or self.disk_estimate_bytes < 0:
            raise ValueError("plan estimates cannot be negative")
        if not self.owned_paths:
            raise ValueError("plan must declare owned paths")
        for path in self.owned_paths:
            _path(path, "owned_paths")
        for port in self.ports:
            if not 0 < port < 65_536:
                raise ValueError("ports must be within the bounded range")
        _bounded(self.health_contract_id, _IDENTIFIER, "health_contract_id")
        _bounded(self.benchmark_gate_id, _IDENTIFIER, "benchmark_gate_id")
        if self.rollback_target_plan_id is not None:
            _bounded(self.rollback_target_plan_id, _IDENTIFIER, "rollback_target_plan_id")
        _digest(self.source_evidence_digest, "source_evidence_digest")

    @property
    def record_id(self) -> str:
        return self.plan_id

    def public_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "model": self.model.public_dict(),
            "engine": self.engine.public_dict(),
            "workload": self.workload.public_dict(),
            "settings": [list(pair) for pair in self.settings],
            "served_aliases": list(self.served_aliases),
            "context_tokens": self.context_tokens,
            "max_concurrency": self.max_concurrency,
            "cache_policy": self.cache_policy,
            "memory_estimate_bytes": self.memory_estimate_bytes,
            "disk_estimate_bytes": self.disk_estimate_bytes,
            "owned_paths": list(self.owned_paths),
            "ports": list(self.ports),
            "health_contract_id": self.health_contract_id,
            "benchmark_gate_id": self.benchmark_gate_id,
            "rollback_target_plan_id": self.rollback_target_plan_id,
            "source_evidence_digest": self.source_evidence_digest,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class BenchmarkCampaign:
    campaign_id: str
    plan_id: str
    benchmark_suite_id: str
    workload_id: str
    state: str
    schema_version: int = CURRENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _bounded(self.campaign_id, _IDENTIFIER, "campaign_id")
        _bounded(self.plan_id, _IDENTIFIER, "plan_id")
        _bounded(self.benchmark_suite_id, _IDENTIFIER, "benchmark_suite_id")
        _bounded(self.workload_id, _IDENTIFIER, "workload_id")
        _bounded(self.state, _IDENTIFIER, "state")

    @property
    def record_id(self) -> str:
        return self.campaign_id

    def public_dict(self) -> dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "plan_id": self.plan_id,
            "benchmark_suite_id": self.benchmark_suite_id,
            "workload_id": self.workload_id,
            "state": self.state,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class BenchmarkComparison:
    comparison_id: str
    plan_ids: tuple[str, ...]
    campaign_ids: tuple[str, ...]
    comparability: str
    verdict: str
    source_evidence_digest: str
    schema_version: int = CURRENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _bounded(self.comparison_id, _IDENTIFIER, "comparison_id")
        if len(self.plan_ids) < 2:
            raise ValueError("a comparison requires at least two plans")
        for plan_id in self.plan_ids:
            _bounded(plan_id, _IDENTIFIER, "plan_ids")
        for campaign_id in self.campaign_ids:
            _bounded(campaign_id, _IDENTIFIER, "campaign_ids")
        _bounded(self.comparability, _IDENTIFIER, "comparability")
        _bounded(self.verdict, _IDENTIFIER, "verdict")
        _digest(self.source_evidence_digest, "source_evidence_digest")

    @property
    def record_id(self) -> str:
        return self.comparison_id

    def public_dict(self) -> dict[str, Any]:
        return {
            "comparison_id": self.comparison_id,
            "plan_ids": list(self.plan_ids),
            "campaign_ids": list(self.campaign_ids),
            "comparability": self.comparability,
            "verdict": self.verdict,
            "source_evidence_digest": self.source_evidence_digest,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class DiagnosisRecord:
    diagnosis_id: str
    plan_id: str
    evidence_package_digest: str
    observations: tuple[str, ...]
    hypotheses: tuple[str, ...]
    confidence: float
    citations: tuple[str, ...]
    proposed_checks: tuple[str, ...]
    schema_version: int = CURRENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _bounded(self.diagnosis_id, _IDENTIFIER, "diagnosis_id")
        _bounded(self.plan_id, _IDENTIFIER, "plan_id")
        _digest(self.evidence_package_digest, "evidence_package_digest")
        for group in (self.observations, self.hypotheses, self.citations, self.proposed_checks):
            for item in group:
                _bounded(item, _IDENTIFIER, "diagnosis item")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be within [0, 1]")

    @property
    def record_id(self) -> str:
        return self.diagnosis_id

    def public_dict(self) -> dict[str, Any]:
        return {
            "diagnosis_id": self.diagnosis_id,
            "plan_id": self.plan_id,
            "evidence_package_digest": self.evidence_package_digest,
            "observations": list(self.observations),
            "hypotheses": list(self.hypotheses),
            "confidence": self.confidence,
            "citations": list(self.citations),
            "proposed_checks": list(self.proposed_checks),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class Recommendation:
    recommendation_id: str
    machine_id: str
    plan_ids: tuple[str, ...]
    evidence_ranked: bool
    weights: tuple[tuple[str, float], ...]
    schema_version: int = CURRENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _bounded(self.recommendation_id, _IDENTIFIER, "recommendation_id")
        _bounded(self.machine_id, _IDENTIFIER, "machine_id")
        if not self.plan_ids:
            raise ValueError("a recommendation must rank at least one plan")
        for plan_id in self.plan_ids:
            _bounded(plan_id, _IDENTIFIER, "plan_ids")
        if not self.weights:
            raise ValueError("recommendation weights cannot be empty")
        for key, weight in self.weights:
            _bounded(key, _SETTING_NAME, "weights")
            if not 0.0 <= weight <= 1.0:
                raise ValueError("weights must be within [0, 1]")

    @property
    def record_id(self) -> str:
        return self.recommendation_id

    def public_dict(self) -> dict[str, Any]:
        return {
            "recommendation_id": self.recommendation_id,
            "machine_id": self.machine_id,
            "plan_ids": list(self.plan_ids),
            "evidence_ranked": self.evidence_ranked,
            "weights": [list(pair) for pair in self.weights],
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class AcceleratorFacts:
    vendor: str
    name: str
    device_id: str
    memory_bytes: int | None
    topology: tuple[str, ...]
    capabilities: tuple[str, ...]
    state: str

    def __post_init__(self) -> None:
        _bounded(self.vendor, _IDENTIFIER, "vendor")
        if not _DISPLAY_NAME.fullmatch(self.name):
            raise ValueError("name must be a bounded display name")
        _bounded(self.device_id, _IDENTIFIER, "device_id")
        if self.memory_bytes is not None and self.memory_bytes < 1:
            raise ValueError("accelerator memory must be positive when known")
        for item in self.topology:
            _bounded(item, _IDENTIFIER, "topology")
        for item in self.capabilities:
            _bounded(item, _IDENTIFIER, "capabilities")
        _bounded(self.state, _IDENTIFIER, "state")

    def public_dict(self) -> dict[str, Any]:
        return {
            "vendor": self.vendor,
            "name": self.name,
            "device_id": self.device_id,
            "memory_bytes": self.memory_bytes,
            "topology": list(self.topology),
            "capabilities": list(self.capabilities),
            "state": self.state,
        }


@dataclass(frozen=True, slots=True)
class StorageFacts:
    category: str
    total_bytes: int

    def __post_init__(self) -> None:
        _bounded(self.category, _IDENTIFIER, "category")
        if self.total_bytes < 1:
            raise ValueError("storage capacity must be positive")

    def public_dict(self) -> dict[str, Any]:
        return {"category": self.category, "total_bytes": self.total_bytes}


@dataclass(frozen=True, slots=True)
class DriverFacts:
    kind: str
    version: str

    def __post_init__(self) -> None:
        _bounded(self.kind, _IDENTIFIER, "kind")
        _bounded(self.version, _IDENTIFIER, "version")

    def public_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "version": self.version}


@dataclass(frozen=True, slots=True)
class HostProfile:
    profile_version: int
    machine_id: str
    platform: str
    architecture: str
    cpu_cores: int | None
    cpu_features: tuple[str, ...]
    memory_bytes: int | None
    accelerators: tuple[AcceleratorFacts, ...]
    storage: tuple[StorageFacts, ...]
    os_version: str
    container_runtime: str | None
    driver_versions: tuple[DriverFacts, ...]
    schema_version: int = CURRENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.profile_version < 1:
            raise ValueError("profile version must be positive")
        _bounded(self.machine_id, _IDENTIFIER, "machine_id")
        _bounded(self.platform, _IDENTIFIER, "platform")
        _bounded(self.architecture, _IDENTIFIER, "architecture")
        if self.cpu_cores is not None and self.cpu_cores < 1:
            raise ValueError("cpu core count must be positive when known")
        for feature in self.cpu_features:
            _bounded(feature, _IDENTIFIER, "cpu_features")
        if self.memory_bytes is not None and self.memory_bytes < 1:
            raise ValueError("memory must be positive when known")
        for accelerator in self.accelerators:
            if not isinstance(accelerator, AcceleratorFacts):
                raise ValueError("profile must contain exact accelerator facts")
        for entry in self.storage:
            if not isinstance(entry, StorageFacts):
                raise ValueError("profile must contain exact storage facts")
        _bounded(self.os_version, _IDENTIFIER, "os_version")
        if self.container_runtime is not None:
            _bounded(self.container_runtime, _IDENTIFIER, "container_runtime")
        for driver in self.driver_versions:
            if not isinstance(driver, DriverFacts):
                raise ValueError("profile must contain exact driver facts")

    @property
    def record_id(self) -> str:
        return self.machine_id

    def public_dict(self) -> dict[str, Any]:
        return {
            "profile_version": self.profile_version,
            "machine_id": self.machine_id,
            "platform": self.platform,
            "architecture": self.architecture,
            "cpu_cores": self.cpu_cores,
            "cpu_features": list(self.cpu_features),
            "memory_bytes": self.memory_bytes,
            "accelerators": [item.public_dict() for item in self.accelerators],
            "storage": [item.public_dict() for item in self.storage],
            "os_version": self.os_version,
            "container_runtime": self.container_runtime,
            "driver_versions": [item.public_dict() for item in self.driver_versions],
            "schema_version": self.schema_version,
        }


_CAPABILITY_VALUES = frozenset({"known", "unavailable", "permission_denied", "unsupported"})


@dataclass(frozen=True, slots=True)
class CapabilityProfile:
    machine_id: str
    memory_state: str
    memory_bytes: int | None
    storage_state: str
    storage_bytes: int | None
    accelerator_state: str
    accelerator_count: int | None
    accelerator_memory_state: str
    accelerator_memory_bytes: int | None
    driver_state: str
    container_runtime: str | None
    supported_formats: tuple[str, ...]
    features: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    schema_version: int = CURRENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _bounded(self.machine_id, _IDENTIFIER, "machine_id")
        self._validate_state("memory_state", self.memory_state, self.memory_bytes)
        self._validate_state("storage_state", self.storage_state, self.storage_bytes)
        self._validate_state("accelerator_state", self.accelerator_state, self.accelerator_count)
        self._validate_state(
            "accelerator_memory_state",
            self.accelerator_memory_state,
            self.accelerator_memory_bytes,
        )
        self._validate_state("driver_state", self.driver_state, None)
        if self.container_runtime is not None:
            _bounded(self.container_runtime, _IDENTIFIER, "container_runtime")
        for item in self.supported_formats:
            _bounded(item, _IDENTIFIER, "supported_formats")
        for item in self.features:
            _bounded(item, _IDENTIFIER, "features")
        for item in self.missing_evidence:
            _bounded(item, _IDENTIFIER, "missing_evidence")

    @staticmethod
    def _validate_state(field: str, state: str, amount: int | None) -> None:
        if state not in _CAPABILITY_VALUES:
            raise ValueError(f"{field} must be a PLAT-001 capability value")
        if state in {"permission_denied", "unsupported"} and amount is not None:
            raise ValueError(f"{field} amount must be unknown unless the value is observed")

    @property
    def record_id(self) -> str:
        return self.machine_id

    def public_dict(self) -> dict[str, Any]:
        return {
            "machine_id": self.machine_id,
            "memory_state": self.memory_state,
            "memory_bytes": self.memory_bytes,
            "storage_state": self.storage_state,
            "storage_bytes": self.storage_bytes,
            "accelerator_state": self.accelerator_state,
            "accelerator_count": self.accelerator_count,
            "accelerator_memory_state": self.accelerator_memory_state,
            "accelerator_memory_bytes": self.accelerator_memory_bytes,
            "driver_state": self.driver_state,
            "container_runtime": self.container_runtime,
            "supported_formats": list(self.supported_formats),
            "features": list(self.features),
            "missing_evidence": list(self.missing_evidence),
            "schema_version": self.schema_version,
        }


_RECORD_TYPES: dict[str, type[Any]] = {
    "machine_profile": MachineProfile,
    "model_identity": ModelIdentity,
    "engine_identity": EngineIdentity,
    "workload_profile": WorkloadProfile,
    "deployment_plan": DeploymentPlan,
    "benchmark_campaign": BenchmarkCampaign,
    "benchmark_comparison": BenchmarkComparison,
    "diagnosis": DiagnosisRecord,
    "recommendation": Recommendation,
    "host_profile": HostProfile,
    "capability_profile": CapabilityProfile,
}
_RECORD_TYPE_NAMES = {record_type: name for name, record_type in _RECORD_TYPES.items()}


def _rebuild_value(hint: Any, value: Any) -> Any:
    origin = get_origin(hint)
    if origin is tuple:
        element_hint = get_args(hint)[0]
        if get_args(hint)[-1] is Ellipsis:
            return tuple(_rebuild_value(element_hint, item) for item in value)
        return tuple(
            _rebuild_value(element, item)
            for element, item in zip(get_args(hint), value, strict=False)
        )
    if is_dataclass(hint):
        return _rebuild_record(hint, value)  # type: ignore[arg-type]
    return value


def _rebuild_record(record_type: type[Any], data: dict[str, Any]) -> Any:
    hints = get_type_hints(record_type)
    expected = {field.name: hints[field.name] for field in fields(record_type)}
    if set(data) != set(expected):
        raise ValueError(f"{record_type.__name__} payload must contain exactly its declared fields")
    arguments = {name: _rebuild_value(hint, data[name]) for name, hint in expected.items()}
    return record_type(**arguments)


def _encode_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


@dataclass(frozen=True, slots=True)
class RecordEnvelope:
    record_type: str
    schema_version: int
    record_id: str
    payload: dict[str, Any]

    def __post_init__(self) -> None:
        if self.record_type not in _RECORD_TYPES:
            raise UnknownRecordTypeError(f"unknown record type {self.record_type!r}")
        if self.schema_version != CURRENT_SCHEMA_VERSION:
            raise SchemaVersionError(
                f"record schema version {self.schema_version} is not supported"
            )
        _bounded(self.record_id, _IDENTIFIER, "record_id")

    @classmethod
    def from_record(cls, record: Any) -> RecordEnvelope:
        record_type = _RECORD_TYPE_NAMES.get(type(record))
        if record_type is None:
            raise UnknownRecordTypeError(f"unknown record type {type(record).__name__!r}")
        return cls(
            record_type=record_type,
            schema_version=record.schema_version,
            record_id=record.record_id,
            payload=record.public_dict(),
        )

    def encode(self) -> bytes:
        return _encode_payload(
            {
                "record_type": self.record_type,
                "schema_version": self.schema_version,
                "record_id": self.record_id,
                "payload": self.payload,
            }
        )

    @classmethod
    def decode(cls, data: bytes) -> RecordEnvelope:
        document = json.loads(data.decode())
        if not isinstance(document, dict):
            raise ValueError("envelope must be a JSON object")
        try:
            record_type = document["record_type"]
            envelope = cls(
                record_type=record_type,
                schema_version=document["schema_version"],
                record_id=document["record_id"],
                payload=document["payload"],
            )
        except KeyError as error:
            raise ValueError(f"envelope is missing {error.args[0]!r}") from error
        _rebuild_record(_RECORD_TYPES[record_type], envelope.payload)
        return envelope

    def to_record(self) -> Any:
        record_type = _RECORD_TYPES[self.record_type]
        record = _rebuild_record(record_type, self.payload)
        if record.record_id != self.record_id:
            raise ValueError("envelope record_id must match the payload identity")
        return record


def encode_record(record: Any) -> bytes:
    return RecordEnvelope.from_record(record).encode()


def decode_record(data: bytes) -> Any:
    return RecordEnvelope.decode(data).to_record()
