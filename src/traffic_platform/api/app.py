"""FastAPI implementation of the formal Phase 1 management API."""

import asyncio
import json
import os
import statistics
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import structlog
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.gzip import GZipMiddleware

from traffic_platform.algorithm_sdk.types import AlgorithmConfig
from traffic_platform.algorithms import builtin_registry
from traffic_platform.common.errors import ErrorCode, PlatformError
from traffic_platform.common.runtime_registry import RuntimeRegistry
from traffic_platform.contracts.factory import MessageFactory
from traffic_platform.contracts.models import (
    ExperimentEvent,
    SourceType,
)
from traffic_platform.experiment_service.engine import (
    ExperimentConfig,
    ExperimentControl,
    ExperimentRunner,
)
from traffic_platform.messaging.factory import message_bus_from_environment
from traffic_platform.observability.logging import get_logger
from traffic_platform.realtime import DigitalTwinHub
from traffic_platform.report_service.generator import generate_report
from traffic_platform.scenario_engine.generator import generate_demo_scenario
from traffic_platform.scenario_engine.models import ScenarioConfig
from traffic_platform.scenario_engine.profiles import ScenarioProfileSet
from traffic_platform.storage import (
    BufferedBatchWriter,
    DataPriority,
    RetentionPolicy,
    SqlAlchemyBatchSink,
    WriteItem,
)

logger = get_logger(__name__)


class ApiModel(BaseModel):
    """Strict API request model."""

    model_config = ConfigDict(strict=True, extra="forbid")


class ErrorResponse(ApiModel):
    """Uniform machine-readable API error response."""

    error_code: ErrorCode
    message: str
    trace_id: str
    details: dict[str, Any] | list[Any] = Field(default_factory=dict)


class ExperimentRequest(ApiModel):
    """Create-experiment request."""

    scenario_id: str = "xiongan_rongdong_20"
    algorithm: str = "coordinated-max-pressure"
    seed: int = Field(default=42, ge=0)
    duration_s: float = Field(default=30.0, gt=0, le=18_000)
    gui: bool = False
    profile: Literal["BASE", "S01", "S02", "S03", "S04", "S05", "S06", "S07"] = "BASE"


class FaultRequest(ApiModel):
    """Fault injection request."""

    fault_type: str
    target: str
    severity: str = "medium"
    duration_s: float = Field(default=30.0, gt=0)
    parameters: dict[str, float | str | bool] = Field(default_factory=dict)


class SimulationRateRequest(ApiModel):
    """Wall-clock playback rate for an active SUMO experiment."""

    rate: float | None = Field(default=None, gt=0, le=32)


class ScenarioGenerateRequest(ApiModel):
    """Request availability or generation of a known scenario."""

    scenario_id: str = "xiongan_rongdong_20"


class PlatformState:
    """In-process lifecycle store; database persistence is handled separately."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.registry = builtin_registry()
        self.scenarios = self._load_scenarios()
        self.scenario_profiles = self._load_scenario_profiles()
        self.experiments: dict[str, dict[str, Any]] = {}
        self.controls: dict[str, ExperimentControl] = {}
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.faults: list[dict[str, Any]] = []
        self.realtime: dict[str, object] = {
            "status": "idle",
            "message": "尚未运行",
        }
        self.digital_twin = DigitalTwinHub(workspace)
        self.intersection_history: dict[str, list[dict[str, object]]] = {}
        self.active_algorithm = "coordinated-max-pressure"
        redis_url = os.environ.get("REDIS_URL")
        self.runtime_registry = RuntimeRegistry(redis_url) if redis_url else None
        database_url = os.environ.get("DATABASE_URL")
        self.storage_fallback_path = self.workspace / "results" / "storage-fallback.jsonl"
        self.database = SqlAlchemyBatchSink(database_url) if database_url else None
        self.writer = (
            BufferedBatchWriter(
                self.database,
                batch_size=100,
                max_items=10_000,
                flush_interval_s=5.0,
                fallback_path=self.storage_fallback_path,
            )
            if self.database is not None
            else None
        )

    def _load_scenarios(self) -> dict[str, ScenarioConfig]:
        return {
            config.scenario_id: config
            for path in sorted((self.workspace / "scenarios" / "configs").glob("*.yaml"))
            for config in [ScenarioConfig.from_yaml(path)]
        }

    def _load_scenario_profiles(self) -> dict[str, ScenarioProfileSet]:
        profile_path = self.workspace / "scenarios" / "configs" / "presets" / "S01-S07.yaml"
        if not profile_path.is_file():
            return {}
        profile_set = ScenarioProfileSet.from_yaml(profile_path)
        return {profile_set.base_scenario_id: profile_set}

    def snapshot(self, data: dict[str, object]) -> None:
        """Receive an actual runner snapshot for REST and WebSocket consumers."""

        self.realtime = {"status": "running", **data}
        raw_simulation_time = data.get("simulation_time_s", 0.0)
        simulation_time_s = (
            float(raw_simulation_time) if isinstance(raw_simulation_time, float | int) else 0.0
        )
        experiment_id = str(data.get("experiment_id", ""))
        intersections = data.get("intersections", [])
        if not isinstance(intersections, list):
            return
        for item in intersections:
            if not isinstance(item, dict):
                continue
            intersection_id = item.get("intersection_id")
            if not isinstance(intersection_id, str):
                continue
            history = self.intersection_history.setdefault(intersection_id, [])
            history.append(
                {
                    "experiment_id": experiment_id,
                    "simulation_time_s": simulation_time_s,
                    "phase_id": item.get("phase_id"),
                    "phase_state": item.get("phase_state"),
                    "queue_vehicles": item.get("queue_vehicles"),
                    "mean_speed_m_s": item.get("mean_speed_m_s"),
                    "congestion_level": item.get("congestion_level"),
                    "spillback_risk": item.get("spillback_risk"),
                    "control_mode": item.get("control_mode"),
                }
            )
            del history[:-300]

    async def start_experiment(self, experiment_id: str) -> None:
        """Run one experiment in a cancellable background task."""

        record = self.experiments[experiment_id]
        request: ExperimentRequest = record["request"]
        control = self.controls[experiment_id]
        sumo_home_value = os.environ.get("SUMO_HOME")
        if not sumo_home_value:
            record["status"] = "failed"
            record["error"] = "SUMO_HOME is not configured"
            await self._update_persisted_status(experiment_id, "failed")
            return
        generated = self.workspace / "scenarios" / "generated" / request.scenario_id
        profile_set = self.scenario_profiles.get(request.scenario_id)
        profile = (
            profile_set.get(request.profile)
            if request.profile != "BASE" and profile_set is not None
            else None
        )
        cloud_outage = profile.cloud_outage_window() if profile is not None else None
        config_name = (
            f"{request.scenario_id}.sumocfg"
            if request.profile == "BASE"
            else f"{request.scenario_id}.{request.profile}.sumocfg"
        )
        config = ExperimentConfig(
            experiment_id=experiment_id,
            scenario_id=request.scenario_id,
            algorithm=request.algorithm,
            seed=request.seed,
            duration_s=request.duration_s,
            config_file=generated / config_name,
            selection_file=generated / "controlled_intersections.json",
            result_dir=self.workspace / "results" / experiment_id,
            scenario_definition_file=(
                self.workspace / "scenarios" / "configs" / f"{request.scenario_id}.yaml"
            ),
            scenario_profile_code=request.profile,
            scenario_profile_file=(
                self.workspace / "scenarios" / "configs" / "presets" / "S01-S07.yaml"
            ),
            gui=request.gui,
            cloud_outage_start_s=cloud_outage[0] if cloud_outage else None,
            cloud_outage_duration_s=cloud_outage[1] if cloud_outage else None,
        )
        record["status"] = "running"
        await self._update_persisted_status(experiment_id, "running")
        write_latency_start = len(self.writer.write_latencies_ms) if self.writer is not None else 0
        try:
            result = await ExperimentRunner(
                config,
                sumo_home=Path(sumo_home_value),
                bus=message_bus_from_environment(
                    os.environ,
                    seed=request.seed,
                ),
                control=control,
                snapshot_callback=self.snapshot,
                digital_twin_callback=self.digital_twin.publish,
                persistence_callback=self.persist_runtime_item,
            ).run()
            terminal_status = "stopped" if control.stop_requested else "completed"
            record["status"] = "finalizing"
            await self._update_persisted_status(experiment_id, "finalizing")
            record["result"] = result
            if self.writer is not None:
                await self.writer.flush()
                run_write_latencies = self.writer.write_latencies_ms[write_latency_start:]
                metrics = result.get("metrics")
                if isinstance(metrics, dict):
                    metrics["data_write_latency_ms"] = (
                        statistics.fmean(run_write_latencies)
                        if run_write_latencies
                        else "not_observed_no_flushed_batch"
                    )
                    metrics["data_write_batch_count"] = len(run_write_latencies)
            result["report_service_notified"] = True
            result["artifacts"] = generate_report(result, config.result_dir)
            report_service_notified = await self.publish_report_ready(config)
            if not report_service_notified:
                result["report_service_notified"] = False
                result["artifacts"] = generate_report(result, config.result_dir)
            record["status"] = terminal_status
            await self._update_persisted_status(
                experiment_id,
                terminal_status,
            )
            self.realtime = {
                **self.realtime,
                "status": record["status"],
            }
            self.digital_twin.set_status(terminal_status)
        except Exception as exc:
            record["status"] = "failed"
            record["error"] = f"{type(exc).__name__}: {exc}"
            await self._update_persisted_status(experiment_id, "failed")
            self.realtime = {
                "status": "failed",
                "experiment_id": experiment_id,
                "error": record["error"],
            }
            self.digital_twin.set_status("failed")

    async def publish_report_ready(self, config: ExperimentConfig) -> bool:
        """Notify the independent report worker after final persistence flush."""

        bus = message_bus_from_environment(os.environ, seed=config.seed)
        factory = MessageFactory(
            source_id="experiment-api",
            source_type=SourceType.EXPERIMENT,
            scenario_id=config.scenario_id,
            experiment_id=config.experiment_id,
            environment=os.environ.get("ENVIRONMENT", "development"),
        )
        event = factory.build(
            ExperimentEvent,
            simulation_time=config.duration_s,
            ttl_s=300.0,
            event_type="REPORT_READY",
            payload={"result_file": str((config.result_dir / "result.json").resolve())},
        )
        try:
            await bus.connect()
            await bus.publish(
                (f"traffic/{event.environment}/experiment/{config.experiment_id}/event"),
                event.model_dump_json().encode("utf-8"),
                qos=1,
            )
            return True
        except Exception as exc:
            logger.error(
                "report_service_notification_failed",
                experiment_id=config.experiment_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return False
        finally:
            await bus.disconnect()

    async def shutdown(self) -> None:
        """Request active experiments to stop and await graceful cleanup."""

        for control in self.controls.values():
            control.stop()
        if self.tasks:
            await asyncio.gather(*self.tasks.values(), return_exceptions=True)
        if self.writer is not None:
            await self.writer.close()
        if self.database is not None:
            self.database.close()
        if self.runtime_registry is not None:
            await self.runtime_registry.close()

    async def startup(self) -> None:
        """Start cancellable background persistence after migrations finish."""

        if self.database is not None:
            try:
                deleted = await self.database.apply_retention(
                    RetentionPolicy(
                        metric_days=int(os.environ.get("METRIC_RETENTION_DAYS", "30")),
                        trajectory_days=int(os.environ.get("TRAJECTORY_RETENTION_DAYS", "14")),
                        event_days=int(os.environ.get("EVENT_RETENTION_DAYS", "180")),
                    )
                )
                logger.info("storage_retention_applied", deleted=deleted)
            except (SQLAlchemyError, OSError) as exc:
                await self._record_storage_failure(
                    "apply_retention",
                    {},
                    exc,
                )
        if self.writer is not None:
            await self.writer.start()
        if self.runtime_registry is not None:
            await self.runtime_registry.ping()

    async def publish_fault_profile(self) -> None:
        """Share live fault controls with independently deployed workers."""

        if self.runtime_registry is None:
            return
        await self.runtime_registry.set_latest(
            "communication-fault-profile",
            "active",
            {"faults": self.faults},
            ttl_s=86_400,
        )

    async def service_statuses(self) -> dict[str, object]:
        """Return TTL-backed status for independently deployed workers."""

        if self.runtime_registry is None:
            return {"status": "not_configured", "services": {}}
        identities = {
            "cloud-service": "cloud-primary",
            "rsu-service": "rsu-rongdong",
            "edge-service": "edge-rongdong",
            "vehicle-agent": "vehicle-agent-primary",
            "report-service": "report-primary",
            "sumo-runner": "sumo-runner-primary",
        }
        services: dict[str, object] = {}
        for role, instance_id in identities.items():
            heartbeat = await self.runtime_registry.get_heartbeat(
                role,
                instance_id,
            )
            services[role] = {
                "online": heartbeat is not None,
                "heartbeat": heartbeat,
            }
        return {
            "status": (
                "online"
                if all(
                    isinstance(value, dict) and value.get("online") is True
                    for value in services.values()
                )
                else "degraded"
            ),
            "services": services,
        }

    async def persist_experiment(
        self,
        experiment_id: str,
        request: ExperimentRequest,
    ) -> None:
        """Persist the experiment identity before any metric can reference it."""

        if self.database is None:
            return
        try:
            await self.database.upsert_experiment(
                experiment_id,
                scenario_id=request.scenario_id,
                algorithm=request.algorithm,
                status="created",
                parameters=request.model_dump(mode="json"),
            )
        except (SQLAlchemyError, OSError) as exc:
            await self._record_storage_failure(
                "upsert_experiment",
                {
                    "experiment_id": experiment_id,
                    "scenario_id": request.scenario_id,
                    "algorithm": request.algorithm,
                    "status": "created",
                    "parameters": request.model_dump(mode="json"),
                },
                exc,
            )

    async def persist_runtime_item(
        self,
        kind: str,
        payload: dict[str, object],
    ) -> None:
        """Queue sampled metrics and durable events with explicit priority."""

        if self.writer is None:
            return
        priorities = {
            "event": DataPriority.EVENT,
            "trajectory": DataPriority.TRAJECTORY,
            "metric": DataPriority.METRIC,
        }
        await self.writer.submit(
            WriteItem(
                kind,
                payload,
                priorities.get(kind, DataPriority.VISUALIZATION),
            )
        )

    async def _update_persisted_status(
        self,
        experiment_id: str,
        status: str,
    ) -> None:
        if self.database is None:
            return
        try:
            await self.database.update_experiment_status(
                experiment_id,
                status,
            )
        except (SQLAlchemyError, OSError) as exc:
            await self._record_storage_failure(
                "update_experiment_status",
                {
                    "experiment_id": experiment_id,
                    "status": status,
                },
                exc,
            )

    async def _record_storage_failure(
        self,
        operation: str,
        payload: dict[str, object],
        exc: Exception,
    ) -> None:
        """Retain a failed critical write locally and emit structured evidence."""

        record: dict[str, object] = {
            "kind": "storage_failure",
            "operation": operation,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "payload": payload,
        }
        logger.error("storage_write_degraded", **record)
        await asyncio.to_thread(self._append_storage_failure, record)

    def _append_storage_failure(self, record: dict[str, object]) -> None:
        self.storage_fallback_path.parent.mkdir(parents=True, exist_ok=True)
        with self.storage_fallback_path.open("a", encoding="utf-8") as target:
            target.write(json.dumps(record, ensure_ascii=False) + "\n")


def create_app(workspace: Path | None = None) -> FastAPI:
    """Create a fully wired FastAPI application."""

    root = (workspace or Path.cwd()).resolve()
    state = PlatformState(root)
    replay_frame_count_cache: dict[Path, tuple[int, int, int]] = {}
    replay_inventory_cache: tuple[float, dict[str, object]] | None = None
    replay_inventory_lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await state.startup()
        yield
        await state.shutdown()

    app = FastAPI(
        title="Xiongan Traffic Platform API",
        version="1.0.0",
        lifespan=lifespan,
        responses={
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
            500: {"model": ErrorResponse},
        },
    )
    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)
    app.state.platform = state

    @app.middleware("http")
    async def trace_middleware(request: Request, call_next: Any) -> Any:
        trace_id = request.headers.get("x-trace-id", uuid4().hex)
        request.state.trace_id = trace_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            trace_id=trace_id,
            method=request.method,
            path=request.url.path,
        )
        try:
            response = await call_next(request)
            response.headers["x-trace-id"] = trace_id
            return response
        finally:
            structlog.contextvars.clear_contextvars()

    def error_response(
        request: Request,
        *,
        status_code: int,
        error_code: ErrorCode,
        message: str,
        details: dict[str, Any] | list[Any] | None = None,
    ) -> JSONResponse:
        trace_id = getattr(request.state, "trace_id", uuid4().hex)
        return JSONResponse(
            status_code=status_code,
            content=ErrorResponse(
                error_code=error_code,
                message=message,
                trace_id=trace_id,
                details=details or {},
            ).model_dump(mode="json"),
            headers={"x-trace-id": trace_id},
        )

    @app.exception_handler(PlatformError)
    async def platform_error_handler(
        request: Request,
        exc: PlatformError,
    ) -> JSONResponse:
        status_code = {
            ErrorCode.RESOURCE_NOT_FOUND: 404,
            ErrorCode.ALGORITHM_NOT_FOUND: 404,
            ErrorCode.INVALID_STATE_TRANSITION: 409,
            ErrorCode.MESSAGE_EXPIRED: 410,
            ErrorCode.INTERNAL_ERROR: 500,
        }.get(exc.code, 422)
        return error_response(
            request,
            status_code=status_code,
            error_code=exc.code,
            message=exc.message,
            details=exc.details,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        code = {
            404: ErrorCode.RESOURCE_NOT_FOUND,
            409: ErrorCode.INVALID_STATE_TRANSITION,
        }.get(exc.status_code, ErrorCode.VALIDATION_ERROR)
        return error_response(
            request,
            status_code=exc.status_code,
            error_code=code,
            message=str(exc.detail),
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return error_response(
            request,
            status_code=422,
            error_code=ErrorCode.VALIDATION_ERROR,
            message="request validation failed",
            details=list(exc.errors()),
        )

    @app.exception_handler(Exception)
    async def internal_error_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        logger.exception(
            "unhandled_api_error",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return error_response(
            request,
            status_code=500,
            error_code=ErrorCode.INTERNAL_ERROR,
            message="internal server error",
        )

    @app.get("/health")
    async def health() -> dict[str, object]:
        return {"status": "healthy", "service": "traffic-platform-api"}

    @app.get("/ready")
    async def ready() -> dict[str, object]:
        generated = root / "scenarios/generated/xiongan_rongdong_20/xiongan_rongdong_20.sumocfg"
        is_ready = generated.is_file()
        dependencies = await state.service_statuses()
        dependency_ready = dependencies["status"] in {
            "online",
            "not_configured",
        }
        database = (
            await state.database.timescale_status()
            if state.database is not None
            else {"provider": "not_configured", "enabled": False}
        )
        database_ready = state.database is None or database.get("enabled") is True
        return {
            "status": (
                "ready" if is_ready and dependency_ready and database_ready else "not_ready"
            ),
            "scenario": is_ready,
            "dependencies": dependencies,
            "database": database,
        }

    @app.get("/metrics", include_in_schema=False)
    async def prometheus_metrics() -> Response:
        """Expose low-cardinality service metrics for Prometheus."""

        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/api/v1/system/status")
    async def system_status() -> dict[str, object]:
        dependencies = await state.service_statuses()
        realtime_fields = {
            key: state.realtime[key]
            for key in (
                "scenario_id",
                "scenario_profile",
                "experiment_id",
                "algorithm",
                "simulation_time_s",
                "fallback_mode",
            )
            if key in state.realtime
        }
        return {
            "status": state.realtime.get("status", "idle"),
            "active_algorithm": state.active_algorithm,
            "experiment_count": len(state.experiments),
            "fault_count": len(state.faults),
            "mqtt": (
                dependencies["status"]
                if os.environ.get(
                    "TRAFFIC_MESSAGE_BUS",
                    "emulated",
                ).lower()
                == "mqtt"
                else "communication_emulator"
            ),
            "services": dependencies["services"],
            "cloud": "offline"
            if any(item["fault_type"] == "cloud_offline" for item in state.faults)
            else "online",
            **realtime_fields,
        }

    @app.post("/api/v1/scenarios/validate")
    async def validate_scenario(config: ScenarioConfig) -> dict[str, object]:
        return {"valid": True, "scenario_id": config.scenario_id}

    @app.post("/api/v1/scenarios/generate", status_code=202)
    async def generate_scenario(
        request: ScenarioGenerateRequest,
    ) -> dict[str, object]:
        scenario_id = request.scenario_id
        if scenario_id not in state.scenarios:
            raise HTTPException(status_code=404, detail="scenario not found")
        if scenario_id != "xiongan_rongdong_20":
            raise HTTPException(
                status_code=422,
                detail=(
                    "official_20_independent is a read-only evidence collection "
                    "and cannot be generated as one connected SUMO network"
                ),
            )
        if any(
            record["status"] in {"running", "paused", "stopping", "finalizing"}
            for record in state.experiments.values()
        ):
            raise HTTPException(
                status_code=409,
                detail="cannot regenerate scenario while an experiment is active",
            )
        sumo_home_value = os.environ.get("SUMO_HOME")
        if not sumo_home_value:
            raise HTTPException(
                status_code=503,
                detail="SUMO_HOME is required for scenario generation",
            )
        result = await asyncio.to_thread(
            generate_demo_scenario,
            root,
            Path(sumo_home_value),
            rebuild=True,
        )
        return {
            "status": "generated",
            "scenario_id": scenario_id,
            "result": result,
        }

    @app.get("/api/v1/scenarios")
    async def list_scenarios() -> dict[str, object]:
        return {
            "items": [
                {
                    "scenario_id": config.scenario_id,
                    "display_name": config.display_name,
                    "provenance": config.provenance,
                    "is_real_measured_network": config.is_real_measured_network,
                    "runnable": (
                        root
                        / "scenarios"
                        / "generated"
                        / config.scenario_id
                        / f"{config.scenario_id}.sumocfg"
                    ).is_file(),
                    "profiles": [
                        {
                            "code": profile.code,
                            "name": profile.name,
                            "flow_multiplier": profile.flow_multiplier,
                            "communication_profile": profile.communication_profile,
                            "disturbance_types": [
                                disturbance.type for disturbance in profile.disturbances
                            ],
                        }
                        for profile in (
                            state.scenario_profiles[config.scenario_id].profiles
                            if config.scenario_id in state.scenario_profiles
                            else []
                        )
                    ],
                }
                for config in state.scenarios.values()
            ]
        }

    @app.get("/api/v1/scenarios/{scenario_id}")
    async def get_scenario(scenario_id: str) -> dict[str, Any]:
        config = state.scenarios.get(scenario_id)
        if config is None:
            raise HTTPException(status_code=404, detail="scenario not found")
        return config.model_dump(mode="json")

    @app.get("/api/v1/scenes/{scenario_id}/3d")
    async def get_3d_scene(scenario_id: str) -> FileResponse:
        """Serve a generated static scene; never synthesize one during a request."""

        if scenario_id != "xiongan_rongdong_20":
            raise HTTPException(status_code=404, detail="3D scene not found")
        scene_path = root / "generated" / "scenes" / f"{scenario_id}.scene.json"
        if not scene_path.is_file():
            raise HTTPException(
                status_code=404,
                detail="3D scene has not been generated; run generate-3d-scene",
            )
        return FileResponse(
            scene_path,
            media_type="application/json",
            headers={"Cache-Control": "public, max-age=300, must-revalidate"},
        )

    @app.get("/api/v1/replays")
    async def list_replays() -> dict[str, object]:
        """List only replay files recorded from actual digital-twin frames."""

        nonlocal replay_inventory_cache

        def last_nonempty_line(replay_path: Path) -> bytes:
            with replay_path.open("rb") as stream:
                stream.seek(0, os.SEEK_END)
                position = stream.tell()
                suffix = b""
                while position > 0:
                    size = min(64 * 1024, position)
                    position -= size
                    stream.seek(position)
                    suffix = stream.read(size) + suffix
                    stripped = suffix.rstrip(b"\r\n")
                    boundary = stripped.rfind(b"\n")
                    if boundary >= 0:
                        return stripped[boundary + 1 :]
                    if len(suffix) > 16 * 1024 * 1024:
                        raise ValueError("replay terminal frame exceeds 16 MB")
                return suffix.strip()

        def scan() -> dict[str, object]:
            items: list[dict[str, object]] = []
            replay_paths = sorted(
                (root / "results").glob("*/digital_twin.replay.ndjson"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            for replay_path in replay_paths:
                try:
                    replay_stat = replay_path.stat()
                    cached_count = replay_frame_count_cache.get(replay_path)
                    with replay_path.open("rb") as stream:
                        first_line = stream.readline()
                        if (
                            cached_count is not None
                            and cached_count[0] == replay_stat.st_size
                            and cached_count[1] == replay_stat.st_mtime_ns
                        ):
                            frame_count = cached_count[2]
                        else:
                            frame_count = 1 if first_line.strip() else 0
                            last_byte = first_line[-1:] if first_line else b""
                            remainder_bytes = 0
                            while chunk := stream.read(1024 * 1024):
                                remainder_bytes += len(chunk)
                                frame_count += chunk.count(b"\n")
                                last_byte = chunk[-1:]
                            if remainder_bytes and last_byte not in {b"\n", b"\r"}:
                                frame_count += 1
                            replay_frame_count_cache[replay_path] = (
                                replay_stat.st_size,
                                replay_stat.st_mtime_ns,
                                frame_count,
                            )
                    first = json.loads(first_line)
                    last = json.loads(last_nonempty_line(replay_path))
                except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
                    continue
                result_path = replay_path.parent / "result.json"
                result_payload: dict[str, Any] = {}
                if result_path.is_file():
                    try:
                        candidate = json.loads(result_path.read_text(encoding="utf-8"))
                        if isinstance(candidate, dict) and candidate.get("actual_run") is True:
                            result_payload = candidate
                    except (OSError, json.JSONDecodeError):
                        result_payload = {}
                items.append(
                    {
                        "experimentId": replay_path.parent.name,
                        "scenarioId": first.get("scenarioId"),
                        "simulationTimeS": last.get(
                            "simulationTimeS", first.get("simulationTimeS", 0)
                        ),
                        "status": last.get("status", "recording"),
                        "frameCount": frame_count,
                        "bytes": replay_stat.st_size,
                        "url": f"/api/v1/replays/{replay_path.parent.name}",
                        "algorithm": result_payload.get("algorithm"),
                        "profile": result_payload.get("scenario_profile"),
                        "seed": result_payload.get("seed"),
                        "summaryMetrics": result_payload.get("metrics", {}),
                        "actualRun": result_payload.get("actual_run") is True,
                    }
                )
            return {"items": items}

        loop = asyncio.get_running_loop()
        now = loop.time()
        if replay_inventory_cache is not None and now - replay_inventory_cache[0] < 2:
            return replay_inventory_cache[1]
        async with replay_inventory_lock:
            now = loop.time()
            if replay_inventory_cache is not None and now - replay_inventory_cache[0] < 2:
                return replay_inventory_cache[1]
            payload = await asyncio.to_thread(scan)
            replay_inventory_cache = (loop.time(), payload)
            return payload

    @app.get("/api/v1/replays/{experiment_id}")
    async def get_replay(experiment_id: str) -> FileResponse:
        if Path(experiment_id).name != experiment_id:
            raise HTTPException(status_code=404, detail="replay not found")
        replay_path = root / "results" / experiment_id / "digital_twin.replay.ndjson"
        if not replay_path.is_file():
            raise HTTPException(status_code=404, detail="replay not found")
        return FileResponse(
            replay_path,
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/api/v1/experiments", status_code=201)
    async def create_experiment(request: ExperimentRequest) -> dict[str, object]:
        if request.scenario_id not in state.scenarios:
            raise HTTPException(status_code=422, detail="unknown scenario")
        config_name = (
            f"{request.scenario_id}.sumocfg"
            if request.profile == "BASE"
            else f"{request.scenario_id}.{request.profile}.sumocfg"
        )
        generated_config = (
            state.workspace / "scenarios" / "generated" / request.scenario_id / config_name
        )
        if request.profile != "BASE" and request.scenario_id not in state.scenario_profiles:
            raise HTTPException(status_code=422, detail="scenario has no validated profiles")
        if not generated_config.is_file():
            raise HTTPException(
                status_code=422,
                detail=(
                    f"generated SUMO configuration is unavailable: {config_name}"
                    if request.profile != "BASE"
                    else (
                        "scenario is a read-only independent-intersection collection, "
                        "not one runnable regional SUMO network"
                    )
                ),
            )
        if request.algorithm not in {item["name"] for item in state.registry.discover()}:
            raise HTTPException(status_code=422, detail="unknown algorithm")
        experiment_id = f"exp-{uuid4().hex[:12]}"
        state.experiments[experiment_id] = {
            "id": experiment_id,
            "status": "created",
            "request": request,
        }
        state.controls[experiment_id] = ExperimentControl()
        await state.persist_experiment(experiment_id, request)
        return {"id": experiment_id, "status": "created"}

    def experiment(experiment_id: str) -> dict[str, Any]:
        record = state.experiments.get(experiment_id)
        if record is None:
            raise HTTPException(status_code=404, detail="experiment not found")
        return record

    @app.post("/api/v1/experiments/{id}/start")
    async def start_experiment(id: str) -> dict[str, object]:
        record = experiment(id)
        if record["status"] not in {"created"}:
            raise HTTPException(status_code=409, detail="experiment cannot start")
        task = asyncio.create_task(state.start_experiment(id), name=f"experiment-{id}")
        state.tasks[id] = task
        state.digital_twin.set_status("starting")
        return {"id": id, "status": "starting"}

    @app.post("/api/v1/experiments/{id}/pause")
    async def pause_experiment(id: str) -> dict[str, object]:
        record = experiment(id)
        if record["status"] != "running":
            raise HTTPException(status_code=409, detail="experiment is not running")
        state.controls[id].pause()
        record["status"] = "paused"
        state.digital_twin.set_status("paused")
        await state._update_persisted_status(id, "paused")
        return {"id": id, "status": "paused"}

    @app.post("/api/v1/experiments/{id}/resume")
    async def resume_experiment(id: str) -> dict[str, object]:
        record = experiment(id)
        if record["status"] != "paused":
            raise HTTPException(status_code=409, detail="experiment is not paused")
        state.controls[id].resume()
        record["status"] = "running"
        state.digital_twin.set_status("running")
        await state._update_persisted_status(id, "running")
        return {"id": id, "status": "running"}

    @app.post("/api/v1/experiments/{id}/rate")
    async def set_experiment_rate(
        id: str,
        request: SimulationRateRequest,
    ) -> dict[str, object]:
        record = experiment(id)
        # ``start`` schedules the runner asynchronously. Accepting ``created``
        # avoids a race when the UI configures pacing immediately after start.
        if record["status"] not in {"created", "running", "paused"}:
            raise HTTPException(status_code=409, detail="experiment cannot be paced")
        state.controls[id].set_simulation_rate(request.rate)
        return {"id": id, "simulation_rate": request.rate}

    @app.post("/api/v1/experiments/{id}/stop")
    async def stop_experiment(id: str) -> dict[str, object]:
        record = experiment(id)
        state.controls[id].stop()
        record["status"] = "stopping"
        state.digital_twin.set_status("stopping")
        await state._update_persisted_status(id, "stopping")
        return {"id": id, "status": "stopping"}

    @app.get("/api/v1/experiments/{id}")
    async def get_experiment(id: str) -> dict[str, object]:
        record = experiment(id)
        request: ExperimentRequest = record["request"]
        return {
            "id": id,
            "status": record["status"],
            "request": request.model_dump(mode="json"),
            "error": record.get("error"),
        }

    @app.get("/api/v1/experiments/{id}/metrics")
    async def get_metrics(id: str) -> dict[str, object]:
        record = experiment(id)
        result = record.get("result")
        return result["metrics"] if result else {"status": "尚未运行"}

    @app.get("/api/v1/experiments/{id}/events")
    async def get_events(id: str) -> dict[str, object]:
        record = experiment(id)
        result = record.get("result")
        return {"items": result["events"] if result else []}

    @app.get("/api/v1/experiments/{id}/report")
    async def get_report(id: str) -> FileResponse:
        record = experiment(id)
        result = record.get("result")
        if not result:
            raise HTTPException(status_code=404, detail="report not generated")
        return FileResponse(
            result["artifacts"]["html"],
            media_type="text/html",
            filename=f"{id}.html",
        )

    @app.get("/api/v1/algorithms")
    async def algorithms() -> dict[str, object]:
        return {"items": state.registry.discover(), "active": state.active_algorithm}

    @app.post("/api/v1/algorithms/{name}/validate-config")
    async def validate_algorithm_config(
        name: str,
        config: AlgorithmConfig,
    ) -> dict[str, object]:
        state.registry.create(name)
        return {"valid": True, "name": name, "config": config.model_dump(mode="json")}

    @app.post("/api/v1/algorithms/{name}/activate")
    async def activate_algorithm(name: str) -> dict[str, object]:
        state.registry.create(name)
        state.active_algorithm = name
        return {"active": name}

    @app.post("/api/v1/faults/inject", status_code=202)
    async def inject_fault(request: FaultRequest) -> dict[str, object]:
        now = datetime.now(UTC)
        state.faults = [
            item for item in state.faults if datetime.fromisoformat(str(item["expires_at"])) > now
        ]
        simulation_time_value = state.realtime.get("simulation_time_s", 0.0)
        current_simulation_time = (
            float(simulation_time_value) if isinstance(simulation_time_value, int | float) else 0.0
        )
        fault = {
            "id": f"fault-{uuid4().hex[:10]}",
            **request.model_dump(mode="json"),
            "experiment_ids": list(state.controls),
            "injected_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=request.duration_s)).isoformat(),
            "expires_at_simulation_time": (current_simulation_time + request.duration_s),
        }
        state.faults.append(fault)
        for control in state.controls.values():
            control.inject_fault(
                request.fault_type,
                {
                    **request.parameters,
                    "duration_s": request.duration_s,
                    "target": request.target,
                },
            )
        await state.publish_fault_profile()
        return fault

    @app.post("/api/v1/faults/clear")
    async def clear_faults() -> dict[str, object]:
        cleared = len(state.faults)
        state.faults.clear()
        for control in state.controls.values():
            control.clear_faults()
        await state.publish_fault_profile()
        return {"cleared": cleared}

    @app.get("/api/v1/faults")
    async def faults() -> dict[str, object]:
        now = datetime.now(UTC)
        state.faults = [
            item for item in state.faults if datetime.fromisoformat(str(item["expires_at"])) > now
        ]
        return {"items": state.faults}

    def selection() -> dict[str, Any]:
        path = root / "scenarios/generated/xiongan_rongdong_20/controlled_intersections.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}

    @app.get("/api/v1/intersections")
    async def intersections() -> dict[str, object]:
        selected = selection()
        return {
            "items": selected.get("intersections", []),
            "topology_edges": selected.get("topology_edges", []),
        }

    @app.get("/api/v1/intersections/{id}/state")
    async def intersection_state(id: str) -> dict[str, object]:
        item = next(
            (
                node
                for node in selection().get("intersections", [])
                if node["intersection_id"] == id
            ),
            None,
        )
        if item is None:
            raise HTTPException(status_code=404, detail="intersection not found")
        return {"intersection": item, "network_realtime": state.realtime}

    @app.get("/api/v1/intersections/{id}/history")
    async def intersection_history(id: str) -> dict[str, object]:
        if not any(node["intersection_id"] == id for node in selection().get("intersections", [])):
            raise HTTPException(status_code=404, detail="intersection not found")
        return {
            "intersection_id": id,
            "history": state.intersection_history.get(id, []),
        }

    @app.websocket("/ws/v1/realtime")
    async def realtime(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            while True:
                await websocket.send_json(state.realtime)
                await asyncio.sleep(1.0)
        except (WebSocketDisconnect, RuntimeError, OSError):
            return

    @app.websocket("/ws/v1/digital-twin")
    async def digital_twin(websocket: WebSocket) -> None:
        """Send a scene reference plus bounded SUMO entity deltas."""

        await websocket.accept()
        initial = state.digital_twin.initial_message()
        await websocket.send_json(initial)
        initial_sequence = initial["sequence"]
        sequence = int(initial_sequence) if isinstance(initial_sequence, int | str) else 0
        try:
            while True:
                for message in state.digital_twin.messages_after(sequence):
                    await websocket.send_json(message)
                    raw_sequence = message["sequence"]
                    sequence = (
                        int(raw_sequence) if isinstance(raw_sequence, int | str) else sequence
                    )
                await asyncio.sleep(0.05)
        except (WebSocketDisconnect, RuntimeError, OSError):
            return

    return app


app = create_app()
