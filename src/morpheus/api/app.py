from __future__ import annotations

import hmac
import os
import re
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import uvicorn
import yaml
from dotenv import dotenv_values
from fastapi import Depends, FastAPI, Header, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from morpheus import __version__ as morpheus_version
from morpheus.adapters.inference.openai import OpenAIInferenceAdapter
from morpheus.adapters.metrics.collector import collect_metrics
from morpheus.adapters.metrics.vllm import VllmMetricsAdapter
from morpheus.adapters.persistence.settings import SettingsJournal, SettingsJournalError
from morpheus.adapters.persistence.sqlite import SqliteStore
from morpheus.adapters.runtime.agent import RuntimeAgentClient
from morpheus.adapters.workflows.dev_executor import DevWorkflowExecutor
from morpheus.adapters.workflows.runner import LazyAuditStore, WorkflowRunner, WorkflowRunnerError
from morpheus.api.body_limit import BodyLimitMiddleware
from morpheus.api.operations import (
    COMPONENT_MAPPING,
    analytics_payload,
    benchmarks_payload,
    controls_payload,
    events_payload,
    metrics_payload,
    navigation_payload,
    observed_component_health,
    settings_payload,
    workflows_payload,
)
from morpheus.api.runtime import runtime_services_snapshot, runtime_snapshot
from morpheus.api.session import BrowserSession, SessionCodec, SessionValidationError
from morpheus.api.settings_plan import plan_settings
from morpheus.config import MorpheusSettings, load_settings
from morpheus.core.access import AccessPolicyError, access_capabilities
from morpheus.core.analytics import analytics_report
from morpheus.core.benchmark import BenchmarkSummary
from morpheus.core.benchstore import BenchmarkStore
from morpheus.core.capabilities import Capability, evaluate_capabilities
from morpheus.core.catalog import SEED_CATALOG
from morpheus.core.compatibility import compatibility_payload
from morpheus.core.concurrency import ConcurrencyLimiter, FixedWindowRateLimiter, RetryPolicy
from morpheus.core.controls import ComponentHealth
from morpheus.core.diagnosis import DiagnosisConfig, DiagnosisMode
from morpheus.core.diagnostic_evidence import (
    DiagnosticEvidence,
    DiagnosticProvenance,
    build_diagnostic_evidence,
)
from morpheus.core.events import EventsError
from morpheus.core.health import Evidence, HealthState
from morpheus.core.metrics_history import (
    MetricsHistoryError,
    freshness_state,
    gaps,
    retention_cutoff,
    rollup,
    unit_for_signal,
)
from morpheus.core.recommendation import (
    RecommendationError,
    RecommendationStore,
    budget_from_host,
    build_recommendation,
    recommend_for_host,
)
from morpheus.core.settings_catalog import detect_sources, settings_catalog
from morpheus.core.workflows import WorkflowId, workflow_definitions
from morpheus.core.workload import SEED_PROFILES, OperatorConstraints
from morpheus.ops.diagnosis import DiagnosisService
from morpheus.ops.diagnostics import DiagnosticEvidenceBuilder, DiagnosticEvidenceError
from morpheus.ports.protocols import Clock, InferencePort, RuntimeAgentPort


class AuthenticationRequired(Exception):
    pass


class CsrfValidationError(Exception):
    pass


class SessionUnavailable(Exception):
    pass


class OperationsDataError(Exception):
    """An operations query was rejected at the bounded data boundary."""


class SessionLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str = Field(min_length=1, max_length=512)


class RecommendationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: str = Field(min_length=1, max_length=128)
    operator: dict[str, Any] | None = None


class SettingsChanges(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changes: dict[str, Any] = Field(default_factory=dict, max_length=64)


class WorkflowStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed: bool = False


_SESSION_COOKIE = "morpheus_session"
_CSRF_COOKIE = "morpheus_csrf"


def _layer_values(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        if path.suffix in {".yaml", ".yml"}:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        return dict(dotenv_values(path))
    except (OSError, yaml.YAMLError):
        return {}


def _evidence_json(evidence: Evidence) -> dict[str, Any]:
    value = asdict(evidence)
    value["state"] = evidence.state.value
    value["observed_at"] = evidence.observed_at.isoformat()
    value["expires_at"] = evidence.expires_at.isoformat()
    value["duration_ms"] = evidence.duration.total_seconds() * 1000
    value.pop("duration")
    return value


def _diagnosis_config(settings: MorpheusSettings) -> DiagnosisConfig:
    destination = {
        "disabled": "none",
        "local": "local",
        "external": f"external:{settings.diagnosis_provider or 'api'}",
    }[settings.diagnosis_mode]
    return DiagnosisConfig(
        mode=DiagnosisMode(settings.diagnosis_mode),
        provider_name=settings.diagnosis_provider or settings.diagnosis_mode,
        timeout_ms=settings.diagnosis_timeout_ms,
        max_cost=settings.diagnosis_max_cost,
        retention=settings.diagnosis_retention,
        data_destination=destination,
        endpoint=settings.diagnosis_endpoint,
        consent_required=True,
        consent_granted=settings.diagnosis_consent,
    )


def create_app(
    *,
    settings: MorpheusSettings,
    inference: InferencePort,
    clock: Clock,
    runtime_agent: RuntimeAgentPort | None = None,
) -> FastAPI:
    app = FastAPI(title="Morpheus Control API", version="0.1.0", docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.inference = inference
    app.state.clock = clock
    app.add_middleware(BodyLimitMiddleware, max_body_bytes=settings.max_request_bytes)
    session_secret = settings.session_secret.get_secret_value().encode()
    session_codec = (
        SessionCodec(secret=session_secret, ttl_seconds=settings.session_ttl_seconds)
        if session_secret
        else None
    )
    request_limiter = ConcurrencyLimiter(settings.max_concurrent_requests)
    rate_limiter = FixedWindowRateLimiter(settings.max_requests_per_minute)
    workflow_runner = WorkflowRunner(
        executor=DevWorkflowExecutor(settings),
        audit=LazyAuditStore(
            SqliteStore(settings.data_dir / "morpheus.sqlite3", owned_root=settings.data_dir)
        ),
    )
    allowed_origins = [
        f"http://127.0.0.1:{settings.dashboard_port}",
        f"http://localhost:{settings.dashboard_port}",
        *settings.allowed_origins,
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "X-Request-ID"],
    )

    @app.middleware("http")
    async def enforce_origin_controls(
        request: Request,
        call_next: Callable[[Request], Awaitable[Any]],
    ) -> Any:
        expected_hosts = {urlsplit(origin).netloc for origin in settings.allowed_origins}
        if expected_hosts and request.headers.get("host") not in expected_hosts:
            return JSONResponse(
                status_code=403,
                content={
                    "error": {
                        "code": "origin_not_allowed",
                        "message": "Host is not in the allowed origin controls",
                    }
                },
            )
        return await call_next(request)

    @app.middleware("http")
    async def secure_responses(
        request: Request,
        call_next: Callable[[Request], Awaitable[Any]],
    ) -> Any:
        request_id = request.headers.get("X-Request-ID") or secrets.token_hex(16)

        def secured(response: Response) -> Response:
            response.headers["X-Request-ID"] = request_id[:128]
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; frame-ancestors 'none'"
            )
            return response

        content_length = request.headers.get("Content-Length")
        if content_length:
            try:
                declared_size = int(content_length)
            except ValueError:
                return secured(
                    JSONResponse(
                        status_code=400,
                        content={
                            "error": {
                                "code": "invalid_content_length",
                                "message": "Content-Length must be a non-negative integer",
                            }
                        },
                    )
                )
            if declared_size < 0:
                return secured(
                    JSONResponse(
                        status_code=400,
                        content={
                            "error": {
                                "code": "invalid_content_length",
                                "message": "Content-Length must be a non-negative integer",
                            }
                        },
                    )
                )
            if declared_size > settings.max_request_bytes:
                return secured(
                    JSONResponse(
                        status_code=413,
                        content={
                            "error": {
                                "code": "request_too_large",
                                "message": "Request body is too large",
                            }
                        },
                    )
                )
        limited = request.url.path.startswith("/api/") and request.method != "OPTIONS"
        client_key = request.client.host if request.client is not None else "local"
        if limited and not await rate_limiter.allow(client_key):
            return secured(
                JSONResponse(
                    status_code=429,
                    headers={"Retry-After": "60"},
                    content={
                        "error": {
                            "code": "request_rate_limited",
                            "message": "Request rate is temporarily limited",
                        }
                    },
                )
            )
        if limited and not await request_limiter.try_acquire():
            return secured(
                JSONResponse(
                    status_code=429,
                    headers={"Retry-After": "1"},
                    content={
                        "error": {
                            "code": "request_capacity_exhausted",
                            "message": "Request capacity is temporarily exhausted",
                        }
                    },
                )
            )
        try:
            return secured(await call_next(request))
        finally:
            if limited:
                await request_limiter.release()

    @app.exception_handler(AuthenticationRequired)
    async def authentication_error(request: Request, error: AuthenticationRequired) -> JSONResponse:
        del request, error
        return JSONResponse(
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
            content={
                "error": {
                    "code": "authentication_required",
                    "message": "Authentication is required",
                }
            },
        )

    @app.exception_handler(CsrfValidationError)
    async def csrf_error(request: Request, error: CsrfValidationError) -> JSONResponse:
        del request, error
        return JSONResponse(
            status_code=403,
            content={
                "error": {"code": "csrf_validation_failed", "message": "CSRF validation failed"}
            },
        )

    @app.exception_handler(SessionUnavailable)
    async def session_unavailable(request: Request, error: SessionUnavailable) -> JSONResponse:
        del request, error
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "session_unavailable",
                    "message": "Browser sessions are unavailable",
                }
            },
        )

    @app.exception_handler(RecommendationError)
    async def recommendation_error(request: Request, error: RecommendationError) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=404 if "no recommendation record" in str(error) else 422,
            content={
                "error": {
                    "code": "recommendation_unavailable",
                    "message": str(error),
                }
            },
        )

    @app.exception_handler(OperationsDataError)
    async def operations_data_error(request: Request, error: OperationsDataError) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "operations_data_error",
                    "message": str(error),
                }
            },
        )

    def browser_session(request: Request) -> BrowserSession:
        if session_codec is None:
            raise AuthenticationRequired
        token = request.cookies.get(_SESSION_COOKIE, "")
        try:
            return session_codec.verify(token, now=clock.utc_now())
        except SessionValidationError:
            raise AuthenticationRequired from None

    def require_api_key(request: Request) -> None:
        expected = settings.api_key.get_secret_value()
        supplied = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if expected and hmac.compare_digest(supplied, expected):
            return
        browser_session(request)

    def require_csrf(request: Request) -> None:
        require_api_key(request)
        session = browser_session(request)
        token = request.headers.get("X-CSRF-Token", "")
        if not token or not hmac.compare_digest(token, session.csrf_token):
            raise CsrfValidationError

    def settings_journal() -> SettingsJournal:
        return SettingsJournal(
            settings.data_dir / "settings" / "overrides.env", owned_root=settings.data_dir
        )

    def set_session_cookies(response: Response, *, token: str, session: BrowserSession) -> None:
        response.set_cookie(
            _SESSION_COOKIE,
            token,
            max_age=settings.session_ttl_seconds,
            path="/",
            secure=settings.session_cookie_secure,
            httponly=True,
            samesite="strict",
        )
        response.set_cookie(
            _CSRF_COOKIE,
            session.csrf_token,
            max_age=settings.session_ttl_seconds,
            path="/",
            secure=settings.session_cookie_secure,
            httponly=False,
            samesite="strict",
        )

    def clear_session_cookies(response: Response) -> None:
        response.delete_cookie(
            _SESSION_COOKIE,
            path="/",
            secure=settings.session_cookie_secure,
            httponly=True,
            samesite="strict",
        )
        response.delete_cookie(
            _CSRF_COOKIE,
            path="/",
            secure=settings.session_cookie_secure,
            httponly=False,
            samesite="strict",
        )

    def capability_payload(evidence: Evidence, service_evidence: dict[str, Any]) -> dict[str, Any]:
        configured: dict[Capability, bool] = {
            Capability.CORE: True,
            **{Capability(name): enabled for name, enabled in settings.features().items()},
        }
        dependency_health = {Capability.CORE: evidence.state is HealthState.READY}
        blockers: dict[Capability, tuple[str, ...]] = {}
        if evidence.state is not HealthState.READY:
            blockers[Capability.CORE] = (evidence.reason_code,)
        _add_optional_capability_health(
            configured=configured,
            dependency_health=dependency_health,
            blockers=blockers,
            service_evidence=service_evidence,
        )
        report = evaluate_capabilities(
            configured=configured,
            dependency_health=dependency_health,
            blockers=blockers,
        )
        return {
            capability.value: {
                "state": status.state.value,
                "blockers": list(status.blockers),
            }
            for capability, status in report.items()
        }

    @app.get("/healthz")
    async def public_health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/v1/session")
    async def login(credentials: SessionLogin, response: Response) -> dict[str, str]:
        expected = settings.api_key.get_secret_value()
        if not expected or not hmac.compare_digest(credentials.api_key, expected):
            raise AuthenticationRequired
        if session_codec is None:
            raise SessionUnavailable
        token, session = session_codec.issue(now=clock.utc_now())
        set_session_cookies(response, token=token, session=session)
        return {"status": "authenticated"}

    @app.delete("/api/v1/session")
    async def logout(
        request: Request,
        response: Response,
        x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> dict[str, str]:
        session = browser_session(request)
        if not x_csrf_token or not hmac.compare_digest(x_csrf_token, session.csrf_token):
            raise CsrfValidationError
        clear_session_cookies(response)
        return {"status": "signed_out"}

    @app.get("/api/v1/health", dependencies=[Depends(require_api_key)])
    async def health() -> dict[str, Any]:
        evidence = await inference.health()
        return {"health": _evidence_json(evidence)}

    @app.get("/api/v1/models", dependencies=[Depends(require_api_key)])
    async def models() -> dict[str, Any]:
        discovered = await inference.models()
        return {"models": [asdict(model) for model in discovered]}

    @app.get("/api/v1/capabilities", dependencies=[Depends(require_api_key)])
    async def capabilities() -> dict[str, Any]:
        evidence = await inference.health()
        service_evidence = await runtime_services_snapshot(runtime_agent, clock=clock)
        return {"capabilities": capability_payload(evidence, service_evidence)}

    @app.get("/api/v1/system/compatibility", dependencies=[Depends(require_api_key)])
    async def system_compatibility(request: Request) -> dict[str, Any]:
        return compatibility_payload(
            backend_version=morpheus_version,
            desktop_version=request.headers.get("X-Morpheus-Desktop-Version"),
        )

    @app.get("/api/v1/system/access", dependencies=[Depends(require_api_key)])
    async def system_access() -> dict[str, Any]:
        try:
            return {"access": access_capabilities(settings)}
        except AccessPolicyError as error:
            raise OperationsDataError(str(error)) from error

    @app.get("/api/v1/operations/navigation", dependencies=[Depends(require_api_key)])
    async def operations_navigation() -> dict[str, Any]:
        host = await runtime_snapshot(runtime_agent, clock=clock)
        try:
            discovered = await inference.models()
        except (httpx.HTTPError, OSError, ValueError):
            discovered = None
        store = SqliteStore(settings.data_dir / "morpheus.sqlite3", owned_root=settings.data_dir)
        await store.initialize()
        events = await store.events(limit=1)
        benchmark_store = BenchmarkStore(settings.data_dir / "benchmarks")
        benchmark_store.initialize()
        runs = benchmark_store.list_runs(limit=100)
        completed = sum(1 for run in runs if run.status == "completed")
        data_states = {
            "benchmarks": "ready" if runs else "empty",
            "analytics": "ready" if completed >= 2 else "partial" if completed == 1 else "empty",
            "logs_events": "ready" if events else "empty",
            "settings": "ready",
            "recovery": "ready" if settings_journal().rollback_available() else "empty",
        }
        return navigation_payload(
            discovered=discovered,
            host=host,
            observed_at=clock.utc_now().isoformat(),
            data_states=data_states,
        )

    @app.get("/api/v1/operations/controls", dependencies=[Depends(require_api_key)])
    async def operations_controls() -> dict[str, Any]:
        evidence = await inference.health()
        service_evidence = await runtime_services_snapshot(runtime_agent, clock=clock)
        return controls_payload(
            settings=settings,
            evidence=evidence,
            service_evidence=service_evidence,
            observed_at=clock.utc_now().isoformat(),
        )

    @app.get("/api/v1/operations/metrics", dependencies=[Depends(require_api_key)])
    async def operations_metrics(
        signal: str = Query(...),
        window_seconds: int = Query(300, ge=60, le=86_400),
        hours: float = Query(6, gt=0, le=24),
    ) -> dict[str, Any]:
        observed_at = clock.utc_now().isoformat()
        host = await runtime_snapshot(runtime_agent, clock=clock)
        engine = (
            VllmMetricsAdapter(metrics_url=settings.vllm_metrics_url)
            if settings.vllm_metrics_url
            else None
        )
        samples, sources = await collect_metrics(engine=engine, host=host, observed_at=observed_at)
        store = SqliteStore(settings.data_dir / "morpheus.sqlite3", owned_root=settings.data_dir)
        await store.initialize()
        if samples:
            await store.record_metric_samples(samples)
        await store.prune_metrics(
            before=retention_cutoff(observed_at, retention_days=settings.metrics_retention_days)
        )
        start = (clock.utc_now() - timedelta(hours=hours)).isoformat()
        try:
            stored = await store.metric_samples(
                signal=signal, start=start, end=observed_at, limit=10_000
            )
            buckets = rollup(stored, window_seconds=window_seconds, start=start, end=observed_at)
            missing = gaps(stored, window_seconds=window_seconds, start=start, end=observed_at)
        except MetricsHistoryError as error:
            raise OperationsDataError(str(error)) from error
        latest = await store.latest_metric_observed_at(signal=signal)
        age_seconds: float | None = None
        if latest is not None:
            age_seconds = (clock.utc_now() - datetime.fromisoformat(latest)).total_seconds()
        return metrics_payload(
            observed_at=observed_at,
            signal=signal,
            unit=unit_for_signal(signal),
            freshness={
                "state": freshness_state(
                    latest,
                    now=observed_at,
                    grace_seconds=2 * settings.metrics_collection_interval_seconds,
                ),
                "latest_observed_at": latest,
                "age_seconds": age_seconds,
            },
            sources=sources,
            buckets=buckets,
            gaps=missing,
            sample_count=len(stored),
        )

    @app.get("/api/v1/operations/events", dependencies=[Depends(require_api_key)])
    async def operations_events(
        limit: int = Query(100, ge=1, le=200),
        source: str | None = Query(None),
        severity: str | None = Query(None),
        correlation_id: str | None = Query(None),
        since: str | None = Query(None),
    ) -> dict[str, Any]:
        observed_at = clock.utc_now().isoformat()
        store = SqliteStore(settings.data_dir / "morpheus.sqlite3", owned_root=settings.data_dir)
        await store.initialize()
        try:
            events = await store.events(
                source=source,
                severity=severity,
                correlation_id=correlation_id,
                since=since,
                limit=limit,
            )
        except EventsError as error:
            raise OperationsDataError(str(error)) from error
        await store.prune_events(
            before=retention_cutoff(observed_at, retention_days=settings.events_retention_days)
        )
        return events_payload(observed_at=observed_at, events=events)

    @app.get("/api/v1/operations/benchmarks", dependencies=[Depends(require_api_key)])
    async def operations_benchmarks(
        limit: int = Query(20, ge=1, le=100),
    ) -> dict[str, Any]:
        observed_at = clock.utc_now().isoformat()
        store = BenchmarkStore(settings.data_dir / "benchmarks")
        store.initialize()
        try:
            runs = store.list_runs(limit=limit)
        except Exception as error:
            raise OperationsDataError(str(error)) from error
        return benchmarks_payload(observed_at=observed_at, runs=runs)

    @app.get("/api/v1/operations/analytics", dependencies=[Depends(require_api_key)])
    async def operations_analytics() -> dict[str, Any]:
        observed_at = clock.utc_now().isoformat()
        benchmark_store = BenchmarkStore(settings.data_dir / "benchmarks")
        benchmark_store.initialize()
        runs = benchmark_store.list_runs(limit=100)
        summaries: dict[str, BenchmarkSummary] = {}
        for run in runs:
            summary = load_run_summary(benchmark_store, run.run_id)
            if summary is not None:
                summaries[run.run_id] = summary
        telemetry_store = SqliteStore(
            settings.data_dir / "morpheus.sqlite3", owned_root=settings.data_dir
        )
        await telemetry_store.initialize()
        cutoff = retention_cutoff(observed_at, retention_days=settings.telemetry_retention_days)
        telemetry = [
            record
            for record in await telemetry_store.telemetry(limit=1_000)
            if record["recorded_at"] >= cutoff
        ]
        report = analytics_report(
            runs=runs,
            summaries=summaries,
            telemetry=telemetry,
            window_days=settings.telemetry_retention_days,
        )
        return analytics_payload(observed_at=observed_at, report=report)

    @app.get("/api/v1/operations/settings", dependencies=[Depends(require_api_key)])
    async def operations_settings() -> dict[str, Any]:
        observed_at = clock.utc_now().isoformat()
        journal = settings_journal()
        sources = detect_sources(
            environ=os.environ,
            env_file=_layer_values(Path(".env")),
            config_file=_layer_values(Path("deploy/config/morpheus.yaml")),
            overrides=journal.current(),
        )
        last_applied = journal.last_applied()
        return settings_payload(
            observed_at=observed_at,
            entries=settings_catalog(settings, sources=sources),
            journal={
                "applied_at": last_applied["applied_at"] if last_applied else None,
                "applied": last_applied["applied"] if last_applied else [],
                "rollback_available": journal.rollback_available(),
            },
        )

    @app.post("/api/v1/operations/settings/plan", dependencies=[Depends(require_csrf)])
    async def operations_settings_plan(body: SettingsChanges) -> dict[str, Any]:
        return plan_settings(settings, changes=body.changes)

    @app.post("/api/v1/operations/settings/apply", dependencies=[Depends(require_csrf)])
    async def operations_settings_apply(body: SettingsChanges) -> dict[str, Any]:
        plan = plan_settings(settings, changes=body.changes)
        if not plan["valid"]:
            raise OperationsDataError("settings plan is invalid; review the issues first")
        journal = settings_journal()
        try:
            result = journal.apply({key: str(value) for key, value in body.changes.items()})
        except SettingsJournalError as error:
            raise OperationsDataError(str(error)) from error
        return {"schema_version": 1, "applied": result["applied"], "restart_required": True}

    @app.post("/api/v1/operations/settings/rollback", dependencies=[Depends(require_csrf)])
    async def operations_settings_rollback() -> dict[str, Any]:
        journal = settings_journal()
        try:
            journal.rollback()
        except SettingsJournalError as error:
            raise OperationsDataError(str(error)) from error
        return {"schema_version": 1, "rolled_back": True}

    @app.get("/api/v1/operations/workflows", dependencies=[Depends(require_api_key)])
    async def operations_workflows() -> dict[str, Any]:
        observed_at = clock.utc_now().isoformat()
        store = SqliteStore(settings.data_dir / "morpheus.sqlite3", owned_root=settings.data_dir)
        await store.initialize()
        audit_events = await store.workflow_audit_events(limit=50)
        sessions = {
            workflow_id.value: session
            for workflow_id in WorkflowId
            if (session := await workflow_runner.session(workflow_id)) is not None
        }
        return workflows_payload(
            observed_at=observed_at,
            definitions=workflow_definitions(),
            sessions=sessions,
            audit_events=audit_events,
        )

    @app.post(
        "/api/v1/operations/workflows/{workflow_id}/start", dependencies=[Depends(require_csrf)]
    )
    async def operations_workflow_start(workflow_id: str, body: WorkflowStart) -> dict[str, Any]:
        try:
            workflow = WorkflowId(workflow_id)
        except ValueError:
            raise OperationsDataError("unknown workflow id") from None
        try:
            result = await workflow_runner.start(
                workflow,
                confirmed=body.confirmed,
                session_id=secrets.token_urlsafe(16),
                observed_at=clock.utc_now().isoformat(),
            )
        except WorkflowRunnerError as error:
            raise OperationsDataError(str(error)) from error
        return {"schema_version": 1, "started": result["started"], "session": result["session"]}

    @app.post(
        "/api/v1/operations/workflows/{workflow_id}/cancel", dependencies=[Depends(require_csrf)]
    )
    async def operations_workflow_cancel(workflow_id: str) -> dict[str, Any]:
        try:
            workflow = WorkflowId(workflow_id)
        except ValueError:
            raise OperationsDataError("unknown workflow id") from None
        try:
            await workflow_runner.cancel(workflow, observed_at=clock.utc_now().isoformat())
        except WorkflowRunnerError as error:
            raise OperationsDataError(str(error)) from error
        return {"schema_version": 1, "cancelled": True}

    @app.get(
        "/api/v1/operations/workflows/{workflow_id}/session",
        dependencies=[Depends(require_api_key)],
    )
    async def operations_workflow_session(workflow_id: str) -> dict[str, Any]:
        try:
            workflow = WorkflowId(workflow_id)
        except ValueError:
            raise OperationsDataError("unknown workflow id") from None
        session = await workflow_runner.session(workflow)
        if session is None:
            raise OperationsDataError("no workflow session exists for this id")
        return {"schema_version": 1, "session": session.to_dict()}

    @app.get("/api/v1/overview", dependencies=[Depends(require_api_key)])
    async def overview() -> dict[str, Any]:
        evidence = await inference.health()
        discovered = await inference.models()
        host = await runtime_snapshot(runtime_agent, clock=clock)
        observed_at = clock.utc_now().isoformat()
        return {
            "observed_at": observed_at,
            "inference": _evidence_json(evidence),
            "models": [asdict(model) for model in discovered],
            "capabilities": capability_payload(evidence, _service_evidence_from_host(host)),
            "host": host,
            "diagnostics": _diagnostics_payload(
                settings=settings,
                evidence=evidence,
                model_contract_ready=bool(discovered),
                host=host,
                observed_at=observed_at,
            ),
            "external_controls": [],
        }

    @app.get("/api/v1/diagnostics", dependencies=[Depends(require_api_key)])
    async def diagnostics() -> dict[str, Any]:
        evidence = await inference.health()
        host = await runtime_snapshot(runtime_agent, clock=clock)
        try:
            discovered = await inference.models()
            model_contract_ready = bool(discovered)
        except (httpx.HTTPError, OSError, ValueError):
            model_contract_ready = False
        observed_at = clock.utc_now().isoformat()
        payload = _diagnostics_payload(
            settings=settings,
            evidence=evidence,
            model_contract_ready=model_contract_ready,
            host=host,
            observed_at=observed_at,
        )
        return {
            **payload,
            "inference": _evidence_json(evidence),
            "host": host,
            "configuration": settings.public_dict(),
        }

    @app.post("/api/v1/diagnostics/evidence", dependencies=[Depends(require_api_key)])
    async def diagnostics_evidence() -> dict[str, Any]:
        """Build a bounded, redacted diagnostic evidence package (AID-001)."""
        evidence = await inference.health()
        host = await runtime_snapshot(runtime_agent, clock=clock)
        try:
            discovered = await inference.models()
            model_contract_ready = bool(discovered)
        except (httpx.HTTPError, OSError, ValueError):
            model_contract_ready = False
        observed_at = clock.utc_now().isoformat()
        checks = _diagnostics_payload(
            settings=settings,
            evidence=evidence,
            model_contract_ready=model_contract_ready,
            host=host,
            observed_at=observed_at,
        )
        try:
            evidence_package = await _live_evidence(checks=checks, host=host)
            package = DiagnosticEvidenceBuilder(settings.data_dir / "diagnostics").build(
                evidence=evidence_package,
                run_id=f"diag-{clock.utc_now().strftime('%Y%m%d-%H%M%S-%f')}",
                source_commit=settings.source_commit,
                canaries={},
                started_at=clock.utc_now(),
                ended_at=clock.utc_now(),
                safe_summary="Diagnostic evidence package assembled for local analysis",
                tool_versions={"morpheus": morpheus_version},
            )
        except (DiagnosticEvidenceError, EventsError, ValueError, OSError) as error:
            raise OperationsDataError(str(error)) from error
        return {"schema_version": 1, "evidence_package": package.to_json()}

    async def _live_evidence(*, checks: dict[str, Any], host: dict[str, Any]) -> DiagnosticEvidence:
        store = SqliteStore(settings.data_dir / "morpheus.sqlite3", owned_root=settings.data_dir)
        await store.initialize()
        events = await store.events(limit=200)
        benchmark_store = BenchmarkStore(settings.data_dir / "benchmarks")
        benchmark_store.initialize()
        runs = benchmark_store.list_runs(limit=100)
        summaries: dict[str, BenchmarkSummary] = {}
        for run in runs:
            summary = load_run_summary(benchmark_store, run.run_id)
            if summary is not None:
                summaries[run.run_id] = summary
        report = analytics_report(
            runs=runs,
            summaries=summaries,
            telemetry=[],
            window_days=settings.telemetry_retention_days,
        )
        return build_diagnostic_evidence(
            health={
                "status": checks["status"],
                "checks": checks["checks"],
            },
            machine_profile=host,
            deployment={
                "version": morpheus_version,
                "release_version": settings.release_version,
                "source_commit": settings.source_commit,
            },
            metrics={},
            events=[
                {
                    "recorded_at": event.recorded_at,
                    "source": event.source,
                    "severity": event.severity,
                    "message": event.message,
                    "correlation_id": event.correlation_id,
                }
                for event in events
            ],
            log_excerpts=[],
            regressions=list(report["regressions"]),
            runbooks=["batwing-operator"],
            provenance=DiagnosticProvenance(
                morpheus_version=morpheus_version,
                source_commit=settings.source_commit,
                observed_at=clock.utc_now().isoformat(),
            ),
        )

    @app.get("/api/v1/diagnostics/provider", dependencies=[Depends(require_api_key)])
    async def diagnosis_provider_capabilities() -> dict[str, Any]:
        """Show provider capabilities before any evidence leaves the host (AID-002)."""
        return {"provider": _diagnosis_config(settings).capabilities()}

    @app.post("/api/v1/diagnostics/analyze", dependencies=[Depends(require_api_key)])
    async def analyze_diagnostics() -> dict[str, Any]:
        """Run grounded AI diagnosis over the bounded evidence package (AID-003/004)."""
        evidence = await inference.health()
        host = await runtime_snapshot(runtime_agent, clock=clock)
        try:
            discovered = await inference.models()
            model_contract_ready = bool(discovered)
        except (httpx.HTTPError, OSError, ValueError):
            model_contract_ready = False
        checks = _diagnostics_payload(
            settings=settings,
            evidence=evidence,
            model_contract_ready=model_contract_ready,
            host=host,
            observed_at=clock.utc_now().isoformat(),
        )
        try:
            evidence_package = await _live_evidence(checks=checks, host=host)
        except (DiagnosticEvidenceError, EventsError, ValueError, OSError) as error:
            raise OperationsDataError(str(error)) from error
        config = _diagnosis_config(settings)
        outcome = await DiagnosisService().run(
            evidence_package,
            config,
            api_key=settings.diagnosis_api_key.get_secret_value(),
        )
        return {
            "schema_version": 1,
            "provider": config.capabilities(),
            "outcome": outcome.to_json(),
        }

    def _store() -> RecommendationStore:
        store = RecommendationStore(settings.data_dir / "recommendations")
        store.initialize()
        return store

    @app.get("/api/v1/recommendations/latest", dependencies=[Depends(require_api_key)])
    async def latest_recommendation() -> dict[str, Any]:
        store = _store()
        record = store.latest()
        if record is None:
            raise RecommendationError("no recommendation record stored yet")
        return {"recommendation": record.to_dict()}

    @app.post("/api/v1/recommendations", dependencies=[Depends(require_api_key)])
    async def generate_recommendation(body: RecommendationRequest) -> dict[str, Any]:
        profile = next(
            (candidate for candidate in SEED_PROFILES if candidate.id == body.profile),
            None,
        )
        if profile is None:
            raise RecommendationError(f"unknown workload profile: {body.profile}")
        host = await runtime_snapshot(runtime_agent, clock=clock)
        budget = budget_from_host(host)
        if budget is None:
            raise RecommendationError(
                "host budget unavailable: runtime agent memory/disk evidence missing"
            )
        operator = OperatorConstraints(**body.operator) if body.operator else None
        ranked, excluded = recommend_for_host(
            profile=profile,
            budget=budget,
            catalog=SEED_CATALOG,
            operator=operator,
            reference_machine_id=host.get("observed_at", "local"),
        )
        record = build_recommendation(
            profile=profile,
            operator=operator,
            reference_machine_id=host.get("observed_at", "local"),
            budget={
                "ram_bytes": budget.ram_bytes,
                "vram_bytes": budget.vram_bytes,
                "storage_bytes": budget.storage_bytes,
                "accelerator": budget.accelerator,
            },
            ranked=ranked,
            excluded=excluded,
        )
        _store().store_record(record)
        return {"recommendation": record.to_dict()}

    return app


def _service_evidence_from_host(host: dict[str, Any]) -> dict[str, Any]:
    checks = host.get("checks")
    services = host.get("services")
    service_check = checks.get("morpheus_services") if isinstance(checks, dict) else None
    if (
        isinstance(service_check, dict)
        and service_check.get("status") == "pass"
        and isinstance(services, list)
    ):
        return {"status": "available", "services": services}
    return {
        "status": "unavailable",
        "reason": str(host.get("reason", "runtime_agent_service_evidence_unavailable")),
    }


def load_run_summary(benchmark_store: BenchmarkStore, run_id: str) -> BenchmarkSummary | None:
    if not benchmark_store.summary_exists(run_id, statistic="p50"):
        return None
    return benchmark_store.load_summary(run_id, statistic="p50")


def _add_optional_capability_health(
    *,
    configured: dict[Capability, bool],
    dependency_health: dict[Capability, bool],
    blockers: dict[Capability, tuple[str, ...]],
    service_evidence: dict[str, Any],
) -> None:
    """Use the runtime agent's owned-container health evidence conservatively.

    A component that is not observed, or whose health check is pending or
    unknown, does not verify the dependency contract, so the capability stays
    blocked.  Only verified healthy components can make an enabled optional
    capability available.
    """
    for capability, enabled in configured.items():
        if capability is Capability.CORE or not enabled:
            continue
        components = COMPONENT_MAPPING.get(capability.value)
        if not components:
            blockers[capability] = ("dependency_mapping_not_configured",)
            continue
        observed, component_blockers = observed_component_health(
            components=components,
            service_evidence=service_evidence,
        )
        if component_blockers:
            blockers[capability] = component_blockers
        verified = bool(observed) and all(
            health in {ComponentHealth.HEALTHY, ComponentHealth.UNHEALTHY} for health in observed
        )
        if verified:
            dependency_health[capability] = all(
                health is ComponentHealth.HEALTHY for health in observed
            )


def _diagnostic_check(
    code: str,
    status: str,
    reason_code: str,
    summary: str,
    observed_at: str,
    next_action: str | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "status": status,
        "reason_code": reason_code,
        "summary": summary,
        "observed_at": observed_at,
        "freshness": "current",
        "next_action": next_action,
    }


def _diagnostics_payload(
    *,
    settings: MorpheusSettings,
    evidence: Evidence,
    model_contract_ready: bool,
    host: dict[str, Any],
    observed_at: str,
) -> dict[str, Any]:
    candidate_identified = bool(settings.release_version and settings.source_commit)
    host_ready = host["status"] in {"available", "degraded"}
    services = host.get("services")
    service_items: list[Any] = services if isinstance(services, list) else []
    services_inspected = bool(service_items)
    image_pinned = bool(
        candidate_identified
        and services_inspected
        and all(
            isinstance(service, dict)
            and service.get("source_commit") == settings.source_commit
            and service.get("release_version") == settings.release_version
            and isinstance(service.get("image_id"), str)
            and re.fullmatch(r"sha256:[0-9a-f]{64}", service["image_id"])
            for service in service_items
        )
    )
    image_pin_status = (
        "pass"
        if image_pinned
        else "fail"
        if candidate_identified and services_inspected
        else "unavailable"
    )
    checks = [
        _diagnostic_check(
            "configuration",
            "pass",
            "configuration_valid",
            "Configuration passed schema and network-posture validation",
            observed_at,
        ),
        _diagnostic_check(
            "network_endpoint",
            "pass" if evidence.state is HealthState.READY else "fail",
            evidence.reason_code,
            evidence.summary,
            evidence.observed_at.isoformat(),
            evidence.next_action,
        ),
        _diagnostic_check(
            "service_contract",
            "pass" if model_contract_ready else "fail",
            "model_contract_ready" if model_contract_ready else "model_contract_unavailable",
            "Inference model discovery returned a compatible contract"
            if model_contract_ready
            else "Inference model discovery did not return a compatible contract",
            observed_at,
            None
            if model_contract_ready
            else "Verify the configured /v1/models endpoint and model response schema",
        ),
        _diagnostic_check(
            "storage",
            "pass" if host_ready and "disk" in host else "unavailable",
            "storage_evidence_ready"
            if host_ready and "disk" in host
            else "storage_evidence_unavailable",
            "Runtime-agent storage evidence is available"
            if host_ready and "disk" in host
            else "Runtime-agent storage evidence is unavailable",
            str(host.get("observed_at", observed_at)),
            None
            if host_ready and "disk" in host
            else "Configure and start the signed runtime agent",
        ),
        _diagnostic_check(
            "clock",
            "pass" if host_ready and "clock" in host else "unavailable",
            "clock_evidence_ready"
            if host_ready and "clock" in host
            else "clock_evidence_unavailable",
            "Runtime-agent clock evidence is available"
            if host_ready and "clock" in host
            else "Runtime-agent clock evidence is unavailable",
            str(host.get("observed_at", observed_at)),
            None
            if host_ready and "clock" in host
            else "Configure and start the signed runtime agent",
        ),
        _diagnostic_check(
            "image_pin",
            image_pin_status,
            "candidate_identity_ready" if image_pinned else "candidate_identity_unavailable",
            "Every running Morpheus service matches the immutable candidate identity"
            if image_pinned
            else "Running service image identity could not be verified against the candidate",
            observed_at,
            None
            if image_pinned
            else "Run the immutable candidate images and verify the signed runtime agent",
        ),
        _diagnostic_check(
            "runtime_agent",
            "pass" if host["status"] == "available" else "unavailable",
            "runtime_agent_ready"
            if host["status"] == "available"
            else str(host.get("reason", "runtime_agent_partial_failure")),
            "All runtime-agent probes passed"
            if host["status"] == "available"
            else "One or more runtime-agent probes are unavailable",
            str(host.get("observed_at", observed_at)),
            None
            if host["status"] == "available"
            else "Verify the runtime agent service and its dedicated credential",
        ),
    ]
    failed = any(check["status"] == "fail" for check in checks)
    incomplete = any(check["status"] == "unavailable" for check in checks)
    return {
        "status": "unhealthy" if failed else "degraded" if incomplete else "ready",
        "observed_at": observed_at,
        "checks": checks,
    }


class SystemClock:
    def utc_now(self) -> Any:
        from datetime import UTC, datetime

        return datetime.now(UTC)

    def monotonic(self) -> float:
        import time

        return time.monotonic()


def run() -> None:
    settings = load_settings()
    clock = SystemClock()
    inference = OpenAIInferenceAdapter(
        base_url=settings.llm_base_url,
        clock=clock,
        timeout_seconds=settings.request_timeout_seconds,
        api_key=settings.upstream_api_key.get_secret_value(),
        retry_policy=RetryPolicy(
            max_attempts=settings.retry_max_attempts,
            deadline_seconds=settings.retry_deadline_seconds,
        ),
    )
    agent_key = settings.agent_key.get_secret_value().encode()
    runtime_endpoint_configured = bool(settings.runtime_agent_url or settings.runtime_agent_socket)
    runtime_agent = (
        RuntimeAgentClient(
            base_url=settings.runtime_agent_url or "http://runtime-agent",
            key=agent_key,
            timeout_seconds=min(settings.request_timeout_seconds, 5),
            uds=settings.runtime_agent_socket,
        )
        if runtime_endpoint_configured and agent_key
        else None
    )
    app = create_app(
        settings=settings,
        inference=inference,
        clock=clock,
        runtime_agent=runtime_agent,
    )
    if settings.access_profile == "network":
        uvicorn.run(
            app,
            host=settings.bind_address,
            port=settings.api_port,
            access_log=False,
            ssl_certfile=str(settings.tls_cert_path),
            ssl_keyfile=str(settings.tls_key_path),
        )
        return
    uvicorn.run(app, host=settings.bind_address, port=settings.api_port, access_log=False)
