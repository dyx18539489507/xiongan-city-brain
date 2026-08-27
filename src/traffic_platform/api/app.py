"""FastAPI implementation of the formal Phase 1 management API."""

import asyncio
import json
import os
import statistics
import subprocess
import sys
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
from traffic_platform.comparison_service import (
    LivePairedExperimentRunner,
    PairedDigitalTwinHub,
    PairedExperimentControl,
    build_fairness_manifest,
    fairness_fingerprint,
)
from traffic_platform.contracts.factory import MessageFactory
from traffic_platform.contracts.models import (
    ExperimentEvent,
    SourceType,
)
from traffic_platform.experiment_service.benchmark import run_benchmark
from traffic_platform.experiment_service.engine import (
    ExperimentConfig,
    ExperimentControl,
    ExperimentRunner,
)
from traffic_platform.messaging.factory import message_bus_from_environment
from traffic_platform.observability.logging import get_logger
from traffic_platform.realtime import DigitalTwinHub
from traffic_platform.report_service.generator import generate_report
from traffic_platform.scenario_engine.draft_builder import (
    AUTOMATIC_MIN_TRIP_DISTANCES_M,
    AUTOMATIC_TARGET_FLOW_MIN_VEH_H,
    OSM_SIMULATION_DURATION_S,
    build_draft_scenario,
)
from traffic_platform.scenario_engine.factory import (
    build_selected_scenario,
    validate_selection,
)
from traffic_platform.scenario_engine.generator import generate_demo_scenario
from traffic_platform.scenario_engine.models import ScenarioConfig
from traffic_platform.scenario_engine.profiles import ScenarioProfileSet
from traffic_platform.scenario_engine.source_factory import (
    create_draft_record,
    draft_dir,
    load_draft,
    load_drafts,
    local_osm_map,
    prepare_osm_draft,
    prepare_planning_draft,
    save_draft,
    store_upload,
    update_draft,
    validate_draft,
)
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


class ScenarioTrafficDemandRequest(ApiModel):
    """Explicit synthetic demand used for a newly drafted road network."""

    source: Literal["synthetic"] = "synthetic"
    target_flow_veh_h: float = Field(
        default=float(AUTOMATIC_TARGET_FLOW_MIN_VEH_H), ge=60.0, le=7200.0
    )
    duration_s: float = Field(
        default=OSM_SIMULATION_DURATION_S,
        ge=OSM_SIMULATION_DURATION_S,
        le=7200.0,
    )
    od_pattern: Literal[
        "network_wide",
        "boundary_exchange",
        "boundary_dominant",
    ] = "boundary_exchange"
    min_trip_distance_m: float = Field(default=AUTOMATIC_MIN_TRIP_DISTANCES_M[0], ge=0.0, le=5000.0)


class ScenarioBuildRequest(ApiModel):
    """Build a versioned scenario from the exact user-selected intersections."""

    scenario_id: str = Field(min_length=3, max_length=64)
    display_name: str = Field(min_length=2, max_length=120)
    source_type: Literal["current_osm", "osm_bbox", "planning_file"] = "current_osm"
    draft_id: str | None = Field(default=None, pattern=r"^draft-[a-f0-9]{12}$")
    selected_intersection_ids: list[str] = Field(min_length=1, max_length=2000)
    seed: int = Field(default=42, ge=0, le=2_147_483_647)
    traffic_demand: ScenarioTrafficDemandRequest | None = None


class OsmBounds(ApiModel):
    """Geographic bounding box selected directly on the map."""

    west: float = Field(ge=-180, le=180)
    south: float = Field(ge=-90, le=90)
    east: float = Field(ge=-180, le=180)
    north: float = Field(ge=-90, le=90)


class OsmDraftRequest(ApiModel):
    """Create an editable source draft from an OSM map selection."""

    bbox: OsmBounds


class ScenarioDraftUpdateRequest(ApiModel):
    """Persist user review and manual network corrections."""

    selected_intersection_ids: list[str] | None = Field(default=None, max_length=2000)
    review_confirmed: bool | None = None
    roads: list[dict[str, Any]] | None = Field(default=None, max_length=6000)
    intersections: list[dict[str, Any]] | None = Field(default=None, max_length=500)


class BenchmarkRequest(ApiModel):
    """Launch an actual fair algorithm matrix on the verified baseline scene."""

    algorithms: list[str] = Field(min_length=2, max_length=4)
    seeds: list[int] = Field(min_length=1, max_length=10)
    duration_s: float = Field(default=300.0, ge=10.0, le=1800.0)
    warmup_s: float = Field(default=600.0, ge=0.0, le=1500.0)


class LiveComparisonRequest(ApiModel):
    """Create one live same-condition baseline/candidate SUMO pair."""

    scenario_id: str = "xiongan_rongdong_20"
    baseline_algorithm: str = "fixed-time"
    candidate_algorithm: str = "coordinated-max-pressure"
    seed: int = Field(default=42, ge=0)
    duration_s: float = Field(default=300.0, gt=0, le=18_000)
    profile: Literal["BASE", "S01", "S02", "S03", "S04", "S05", "S06", "S07"] = "BASE"
    gui: Literal[False] = False


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
        self.scenario_builds: dict[str, dict[str, Any]] = {}
        self.scenario_build_tasks: dict[str, asyncio.Task[None]] = {}
        self.scenario_drafts: dict[str, dict[str, Any]] = load_drafts(workspace)
        for record in self.scenario_drafts.values():
            if record.get("status") not in {"queued", "processing"}:
                continue
            record.update(
                status="failed",
                message="上次解析任务已中断, 请重新解析",
                error="服务重启中断了未完成的场景解析任务",
            )
            save_draft(workspace, record)
        self.scenario_draft_tasks: dict[str, asyncio.Task[None]] = {}
        self.benchmarks: dict[str, dict[str, Any]] = self._load_benchmarks()
        self.benchmark_tasks: dict[str, asyncio.Task[None]] = {}
        self.live_comparisons: dict[str, dict[str, Any]] = {}
        self.comparison_controls: dict[str, PairedExperimentControl] = {}
        self.comparison_tasks: dict[str, asyncio.Task[None]] = {}
        self.faults: list[dict[str, Any]] = []
        self.realtime: dict[str, object] = {
            "status": "idle",
            "message": "尚未运行",
        }
        self.digital_twin = DigitalTwinHub(workspace)
        self.comparison_twin = PairedDigitalTwinHub(workspace)
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

    async def start_osm_draft(
        self,
        draft_id: str,
        bbox: dict[str, float],
    ) -> None:
        """Download and convert a real OSM selection without blocking the API."""

        sumo_home_value = os.environ.get("SUMO_HOME")
        if not sumo_home_value:
            record = self.scenario_drafts[draft_id]
            record.update(
                status="failed",
                message="SUMO_HOME 未配置",
                error="SUMO_HOME is required for OSM network conversion",
            )
            save_draft(self.workspace, record)
            return
        try:
            result = await asyncio.to_thread(
                prepare_osm_draft,
                self.workspace,
                Path(sumo_home_value),
                draft_id,
                bbox,
            )
            self.scenario_drafts[draft_id] = result
        except Exception:
            self.scenario_drafts[draft_id] = load_draft(self.workspace, draft_id)
            logger.exception("osm_scenario_draft_failed", draft_id=draft_id)

    async def start_planning_draft(self, draft_id: str) -> None:
        """Parse one uploaded planning source into an editable draft."""

        try:
            result = await asyncio.to_thread(
                prepare_planning_draft,
                self.workspace,
                draft_id,
            )
            self.scenario_drafts[draft_id] = result
        except Exception:
            self.scenario_drafts[draft_id] = load_draft(self.workspace, draft_id)
            logger.exception("planning_scenario_draft_failed", draft_id=draft_id)

    async def start_scenario_build(self, build_id: str) -> None:
        """Execute one scenario build without blocking the management API."""

        record = self.scenario_builds[build_id]
        request: ScenarioBuildRequest = record["request"]
        sumo_home_value = os.environ.get("SUMO_HOME")
        if not sumo_home_value:
            record.update(
                status="failed",
                progress=0,
                message="SUMO_HOME is not configured",
                error="SUMO_HOME is required for scenario generation",
            )
            return

        record.update(status="running", progress=1, message="开始构建场景")

        def progress(value: int, message: str) -> None:
            record["progress"] = value
            record["message"] = message
            record["logs"].append(
                {
                    "time": datetime.now(UTC).isoformat(),
                    "progress": value,
                    "message": message,
                }
            )

        try:
            if request.source_type == "current_osm":
                result = await asyncio.to_thread(
                    build_selected_scenario,
                    self.workspace,
                    Path(sumo_home_value),
                    scenario_id=request.scenario_id,
                    display_name=request.display_name,
                    selected_intersection_ids=request.selected_intersection_ids,
                    seed=request.seed,
                    progress=progress,
                )
            else:
                if request.draft_id is None:
                    raise ValueError("draft_id is required for a source draft build")
                result = await asyncio.to_thread(
                    build_draft_scenario,
                    self.workspace,
                    Path(sumo_home_value),
                    draft_id=request.draft_id,
                    scenario_id=request.scenario_id,
                    display_name=request.display_name,
                    seed=request.seed,
                    traffic_demand=(
                        request.traffic_demand.model_dump(mode="python")
                        if request.traffic_demand is not None
                        else None
                    ),
                    progress=progress,
                )
            config_path = self.workspace / "scenarios" / "configs" / f"{request.scenario_id}.yaml"
            self.scenarios[request.scenario_id] = ScenarioConfig.from_yaml(config_path)
            record.update(
                status="completed",
                progress=100,
                message="场景已生成并通过SUMO验证",
                result=result,
                error=None,
            )
        except Exception as exc:
            logger.exception(
                "scenario_factory_build_failed",
                build_id=build_id,
                scenario_id=request.scenario_id,
            )
            record.update(
                status="failed",
                message="场景构建失败",
                error=f"{type(exc).__name__}: {exc}",
            )

    async def start_benchmark(self, benchmark_id: str) -> None:
        """Run a real paired algorithm matrix and retain its statistical evidence."""

        record = self.benchmarks[benchmark_id]
        request: BenchmarkRequest = record["request"]
        sumo_home_value = os.environ.get("SUMO_HOME")
        if not sumo_home_value:
            record.update(
                status="failed",
                message="SUMO_HOME is not configured",
                error="SUMO_HOME is required for algorithm benchmarks",
            )
            return
        record.update(status="running", progress=0, message="开始公平配对实验矩阵")

        def progress(completed: int, total: int, row: dict[str, Any]) -> None:
            percent = round(completed / max(1, total) * 100)
            record.update(
                progress=percent,
                completed_runs=completed,
                message=(f"已完成 {completed}/{total}: {row['algorithm']} seed {row['seed']}"),
            )
            record["rows"] = [*record["rows"], row]

        try:
            output_dir = self.workspace / "results" / "benchmarks" / benchmark_id
            matrix = await run_benchmark(
                sumo_home=Path(sumo_home_value),
                algorithms=request.algorithms,
                seeds=request.seeds,
                duration_s=request.duration_s,
                output_dir=output_dir,
                warmup_s=request.warmup_s,
                progress=progress,
            )
            record.update(
                status="completed",
                progress=100,
                message="实际公平配对实验矩阵已完成",
                result=matrix,
                output_dir=str(output_dir),
                error=None,
            )
        except Exception as exc:
            logger.exception("algorithm_benchmark_failed", benchmark_id=benchmark_id)
            record.update(
                status="failed",
                message="算法实验矩阵运行失败",
                error=f"{type(exc).__name__}: {exc}",
            )

    def _load_scenarios(self) -> dict[str, ScenarioConfig]:
        return {
            config.scenario_id: config
            for path in sorted((self.workspace / "scenarios" / "configs").glob("*.yaml"))
            for config in [ScenarioConfig.from_yaml(path)]
        }

    def _load_benchmarks(self) -> dict[str, dict[str, Any]]:
        """Recover benchmark progress and completed evidence from disk."""

        records: dict[str, dict[str, Any]] = {}
        benchmark_root = self.workspace / "results" / "benchmarks"
        directories = {
            path.parent
            for pattern in ("*/runner-status.json", "*/benchmark.json")
            for path in benchmark_root.glob(pattern)
        }
        for output_dir in sorted(directories):
            result_path = output_dir / "benchmark.json"
            status_path = output_dir / "runner-status.json"
            if result_path.is_file():
                try:
                    payload = json.loads(result_path.read_text(encoding="utf-8"))
                    request = BenchmarkRequest(
                        algorithms=payload["algorithms"],
                        seeds=payload["seeds"],
                        duration_s=payload["duration_s"],
                        warmup_s=payload.get("warmup_s", 0.0),
                    )
                except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                    continue
                identifier = output_dir.name
                rows = payload.get("rows", [])
                records[identifier] = {
                    "id": identifier,
                    "status": "completed",
                    "progress": 100,
                    "message": "已从磁盘恢复实际公平配对实验矩阵",
                    "request": request,
                    "completed_runs": len(rows),
                    "total_runs": len(request.algorithms) * len(request.seeds),
                    "rows": rows,
                    "result": payload,
                    "output_dir": str(output_dir),
                    "error": None,
                    "created_at": datetime.fromtimestamp(
                        result_path.stat().st_mtime,
                        tz=UTC,
                    ).isoformat(),
                }
                continue
            if not status_path.is_file():
                continue
            try:
                status_payload = json.loads(status_path.read_text(encoding="utf-8"))
                request = BenchmarkRequest(
                    algorithms=status_payload["algorithms"],
                    seeds=status_payload["seeds"],
                    duration_s=status_payload["duration_s"],
                    warmup_s=status_payload.get("warmup_s", 0.0),
                )
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
            identifier = output_dir.name
            records[identifier] = {
                "id": identifier,
                "status": status_payload.get("status", "failed"),
                "progress": status_payload.get("progress", 0),
                "message": status_payload.get("message", "正在读取正式实验状态"),
                "request": request,
                "completed_runs": status_payload.get("completed_runs", 0),
                "total_runs": status_payload.get(
                    "total_runs", len(request.algorithms) * len(request.seeds)
                ),
                "rows": [],
                "result": None,
                "output_dir": str(output_dir),
                "error": status_payload.get("error"),
                "created_at": status_payload.get("started_at")
                or datetime.fromtimestamp(status_path.stat().st_mtime, tz=UTC).isoformat(),
            }
        return records

    def refresh_benchmarks_from_disk(self) -> None:
        """Merge independent runner progress without replacing active API tasks."""

        active_ids = {
            identifier for identifier, task in self.benchmark_tasks.items() if not task.done()
        }
        for identifier, record in self._load_benchmarks().items():
            if identifier not in active_ids:
                self.benchmarks[identifier] = record

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
            isolate_algorithms=(
                os.environ.get("TRAFFIC_PLATFORM_ISOLATE_ALGORITHMS", "true").strip().lower()
                not in {"0", "false", "no", "off"}
            ),
        )
        record["status"] = "running"
        await self._update_persisted_status(experiment_id, "running")
        write_latency_start = len(self.writer.write_latencies_ms) if self.writer is not None else 0
        try:
            self.digital_twin.select_scene(request.scenario_id)
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

    async def start_live_comparison(self, pair_id: str) -> None:
        """Run a baseline and candidate as two synchronized real SUMO instances."""

        record = self.live_comparisons[pair_id]
        request: LiveComparisonRequest = record["request"]
        control = self.comparison_controls[pair_id]
        sumo_home_value = os.environ.get("SUMO_HOME")
        if not sumo_home_value:
            record.update(status="failed", error="SUMO_HOME is not configured")
            self.comparison_twin.invalidate("SUMO_HOME is not configured")
            return

        generated = self.workspace / "scenarios" / "generated" / request.scenario_id
        config_name = (
            f"{request.scenario_id}.sumocfg"
            if request.profile == "BASE"
            else f"{request.scenario_id}.{request.profile}.sumocfg"
        )
        profile_set = self.scenario_profiles.get(request.scenario_id)
        profile = (
            profile_set.get(request.profile)
            if request.profile != "BASE" and profile_set is not None
            else None
        )
        cloud_outage = profile.cloud_outage_window() if profile is not None else None
        common = {
            "scenario_id": request.scenario_id,
            "seed": request.seed,
            "duration_s": request.duration_s,
            "config_file": generated / config_name,
            "selection_file": generated / "controlled_intersections.json",
            "scenario_definition_file": (
                self.workspace / "scenarios" / "configs" / f"{request.scenario_id}.yaml"
            ),
            "scenario_profile_code": request.profile,
            "scenario_profile_file": (
                self.workspace / "scenarios" / "configs" / "presets" / "S01-S07.yaml"
            ),
            "gui": False,
            "cloud_outage_start_s": cloud_outage[0] if cloud_outage else None,
            "cloud_outage_duration_s": cloud_outage[1] if cloud_outage else None,
            "isolate_algorithms": (
                os.environ.get("TRAFFIC_PLATFORM_ISOLATE_ALGORITHMS", "true").strip().lower()
                not in {"0", "false", "no", "off"}
            ),
            # Live paired views consume the in-memory samples and atomic twin
            # stream directly. Avoid serializing duplicate telemetry topics
            # that have no control-path subscriber in this runtime.
            "publish_feedback_to_bus": False,
            "publish_runtime_telemetry_to_bus": False,
        }
        baseline_config = ExperimentConfig(
            experiment_id=record["baseline_experiment_id"],
            algorithm=request.baseline_algorithm,
            result_dir=self.workspace / "results" / pair_id / "baseline",
            **common,
        )
        candidate_config = ExperimentConfig(
            experiment_id=record["candidate_experiment_id"],
            algorithm=request.candidate_algorithm,
            result_dir=self.workspace / "results" / pair_id / "candidate",
            **common,
        )
        record.update(error=None)

        def receive_snapshot(role: str, snapshot: dict[str, object]) -> None:
            record["snapshots"][role] = snapshot
            if record["status"] == "starting" and all(
                isinstance(item, dict) for item in record["snapshots"].values()
            ):
                record["status"] = "running"

        try:
            result = await LivePairedExperimentRunner(
                baseline_config=baseline_config,
                candidate_config=candidate_config,
                sumo_home=Path(sumo_home_value),
                baseline_bus=message_bus_from_environment(os.environ, seed=request.seed),
                candidate_bus=message_bus_from_environment(os.environ, seed=request.seed),
                control=control,
                hub=self.comparison_twin,
                snapshot_callback=receive_snapshot,
            ).run()
            status = "stopped" if control.stop_requested else "completed"
            record.update(status=status, result=result)
            self.comparison_twin.set_status(status)
        except Exception as exc:
            record.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            self.comparison_twin.invalidate(str(record["error"]))

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
        for control in self.comparison_controls.values():
            control.stop()
        tasks = [
            *self.tasks.values(),
            *self.scenario_build_tasks.values(),
            *self.benchmark_tasks.values(),
            *self.comparison_tasks.values(),
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
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

    @app.post("/api/v1/scenario-drafts/osm", status_code=202)
    async def create_osm_scenario_draft(
        request: OsmDraftRequest,
    ) -> dict[str, object]:
        bbox = request.bbox.model_dump(mode="json")
        if bbox["west"] >= bbox["east"] or bbox["south"] >= bbox["north"]:
            raise HTTPException(status_code=422, detail="invalid bbox coordinate order")
        if bbox["east"] - bbox["west"] > 0.12 or bbox["north"] - bbox["south"] > 0.12:
            raise HTTPException(status_code=422, detail="selection is too large")
        draft_id = f"draft-{uuid4().hex[:12]}"
        record = create_draft_record(
            root,
            draft_id,
            "osm_bbox",
            {
                "bbox": bbox,
                "provider": "河北本地 OpenStreetMap 固定快照",
                "snapshot_date": "2026-08-21",
            },
        )
        state.scenario_drafts[draft_id] = record
        task = asyncio.create_task(
            state.start_osm_draft(draft_id, bbox),
            name=f"osm-draft-{draft_id}",
        )
        state.scenario_draft_tasks[draft_id] = task
        return {"id": draft_id, "status": "queued"}

    @app.get("/api/v1/osm/local-map")
    async def get_local_osm_map(
        west: float,
        south: float,
        east: float,
        north: float,
    ) -> JSONResponse:
        try:
            payload = await asyncio.to_thread(
                local_osm_map,
                root,
                {"west": west, "south": south, "east": east, "north": north},
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return JSONResponse(payload, headers={"Cache-Control": "private, max-age=3600"})

    @app.post("/api/v1/scenario-drafts/planning", status_code=202)
    async def create_planning_scenario_draft(request: Request) -> dict[str, object]:
        filename = request.headers.get("x-file-name") or request.query_params.get("filename")
        if not filename:
            raise HTTPException(status_code=422, detail="x-file-name header is required")
        content = await request.body()
        draft_id = f"draft-{uuid4().hex[:12]}"
        record = create_draft_record(
            root,
            draft_id,
            "planning_file",
            {"original_name": filename, "size_bytes": len(content)},
        )
        try:
            source_path = store_upload(root, draft_id, filename, content)
        except ValueError as exc:
            record.update(status="failed", message="规划资料上传失败", error=str(exc))
            save_draft(root, record)
            state.scenario_drafts[draft_id] = record
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        record["artifacts"] = {"source": source_path.name}
        save_draft(root, record)
        state.scenario_drafts[draft_id] = record
        task = asyncio.create_task(
            state.start_planning_draft(draft_id),
            name=f"planning-draft-{draft_id}",
        )
        state.scenario_draft_tasks[draft_id] = task
        return {"id": draft_id, "status": "queued"}

    @app.get("/api/v1/scenario-drafts")
    async def list_scenario_drafts() -> dict[str, object]:
        records = [load_draft(root, draft_id) for draft_id in state.scenario_drafts]
        return {
            "items": sorted(
                records,
                key=lambda item: str(item["created_at"]),
                reverse=True,
            )
        }

    @app.get("/api/v1/scenario-drafts/{draft_id}")
    async def get_scenario_draft(draft_id: str) -> dict[str, object]:
        try:
            record = load_draft(root, draft_id)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="scenario draft not found") from exc
        state.scenario_drafts[draft_id] = record
        return record

    @app.patch("/api/v1/scenario-drafts/{draft_id}")
    async def patch_scenario_draft(
        draft_id: str,
        request: ScenarioDraftUpdateRequest,
    ) -> dict[str, object]:
        try:
            record = update_draft(
                root,
                draft_id,
                selected_intersection_ids=request.selected_intersection_ids,
                review_confirmed=request.review_confirmed,
                roads=request.roads,
                intersections=request.intersections,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="scenario draft not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        state.scenario_drafts[draft_id] = record
        return record

    @app.get("/api/v1/scenario-drafts/{draft_id}/artifacts/{artifact_key}")
    async def get_scenario_draft_artifact(draft_id: str, artifact_key: str) -> FileResponse:
        try:
            record = load_draft(root, draft_id)
            name = str(record.get("artifacts", {})[artifact_key])
            folder = draft_dir(root, draft_id).resolve()
            target = (folder / name).resolve()
            if folder not in target.parents or not target.is_file():
                raise FileNotFoundError(name)
        except (FileNotFoundError, KeyError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="draft artifact not found") from exc
        return FileResponse(target)

    @app.post("/api/v1/scenario-builds/validate")
    async def validate_scenario_build(
        request: ScenarioBuildRequest,
    ) -> dict[str, object]:
        if request.source_type == "current_osm":
            return validate_selection(root, request.selected_intersection_ids)
        if request.draft_id is None:
            raise HTTPException(status_code=422, detail="draft_id is required")
        try:
            draft = load_draft(root, request.draft_id)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="scenario draft not found") from exc
        if draft["source_type"] != request.source_type:
            raise HTTPException(status_code=422, detail="draft source type mismatch")
        draft["selected_intersection_ids"] = list(dict.fromkeys(request.selected_intersection_ids))
        return validate_draft(draft)

    @app.post("/api/v1/scenario-builds", status_code=202)
    async def create_scenario_build(
        request: ScenarioBuildRequest,
    ) -> dict[str, object]:
        if request.scenario_id in {"xiongan_rongdong_20", "official_20_independent"}:
            raise HTTPException(status_code=409, detail="protected scenario id")
        active_same_scenario = any(
            item["request"].scenario_id == request.scenario_id
            and item["status"] in {"queued", "running"}
            for item in state.scenario_builds.values()
        )
        if active_same_scenario:
            raise HTTPException(
                status_code=409,
                detail="a build for this scenario is already active",
            )
        if request.source_type == "current_osm":
            validation = validate_selection(root, request.selected_intersection_ids)
        else:
            if request.draft_id is None:
                raise HTTPException(status_code=422, detail="draft_id is required")
            try:
                draft = update_draft(
                    root,
                    request.draft_id,
                    selected_intersection_ids=request.selected_intersection_ids,
                )
            except FileNotFoundError as exc:
                raise HTTPException(status_code=404, detail="scenario draft not found") from exc
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            if draft["source_type"] != request.source_type:
                raise HTTPException(status_code=422, detail="draft source type mismatch")
            state.scenario_drafts[request.draft_id] = draft
            validation = validate_draft(draft)
        if not validation["valid"]:
            raise HTTPException(status_code=422, detail=validation)
        build_id = f"build-{uuid4().hex[:12]}"
        state.scenario_builds[build_id] = {
            "id": build_id,
            "status": "queued",
            "progress": 0,
            "message": "等待场景构建",
            "request": request,
            "validation": validation,
            "logs": [],
            "result": None,
            "error": None,
            "created_at": datetime.now(UTC).isoformat(),
        }
        task = asyncio.create_task(
            state.start_scenario_build(build_id),
            name=f"scenario-build-{build_id}",
        )
        state.scenario_build_tasks[build_id] = task
        return {"id": build_id, "status": "queued", "validation": validation}

    @app.get("/api/v1/scenario-builds")
    async def list_scenario_builds() -> dict[str, object]:
        return {
            "items": [
                {
                    **{key: value for key, value in item.items() if key != "request"},
                    "request": item["request"].model_dump(mode="json"),
                }
                for item in sorted(
                    state.scenario_builds.values(),
                    key=lambda value: value["created_at"],
                    reverse=True,
                )
            ]
        }

    @app.get("/api/v1/scenario-builds/{build_id}")
    async def get_scenario_build(build_id: str) -> dict[str, object]:
        record = state.scenario_builds.get(build_id)
        if record is None:
            raise HTTPException(status_code=404, detail="scenario build not found")
        return {
            **{key: value for key, value in record.items() if key != "request"},
            "request": record["request"].model_dump(mode="json"),
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
                    "duration_s": config.simulation.duration_s,
                    "seed": config.simulation.seed,
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

    @app.post("/api/v1/scenarios/{scenario_id}/open-folder")
    async def open_scenario_folder(scenario_id: str) -> dict[str, object]:
        if scenario_id not in state.scenarios:
            raise HTTPException(status_code=404, detail="scenario not found")
        generated_root = (root / "scenarios" / "generated").resolve()
        folder = (generated_root / scenario_id).resolve()
        if generated_root not in folder.parents or not folder.is_dir():
            raise HTTPException(status_code=404, detail="scenario folder not found")

        def reveal() -> None:
            if sys.platform == "win32":
                subprocess.Popen(["explorer.exe", str(folder)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])

        await asyncio.to_thread(reveal)
        return {"opened": True, "scenario_id": scenario_id}

    @app.post("/api/v1/scenarios/{scenario_id}/open-sumo")
    async def open_scenario_in_sumo(scenario_id: str) -> dict[str, object]:
        if scenario_id not in state.scenarios:
            raise HTTPException(status_code=404, detail="scenario not found")
        generated_root = (root / "scenarios" / "generated").resolve()
        folder = (generated_root / scenario_id).resolve()
        if generated_root not in folder.parents or not folder.is_dir():
            raise HTTPException(status_code=404, detail="scenario folder not found")

        preferred_config = folder / f"{scenario_id}.sumocfg"
        configs = (
            [preferred_config] if preferred_config.is_file() else sorted(folder.glob("*.sumocfg"))
        )
        if not configs:
            raise HTTPException(status_code=404, detail="SUMO configuration not found")
        config = configs[0].resolve()
        if folder not in config.parents or not config.is_file():
            raise HTTPException(status_code=404, detail="SUMO configuration not found")

        gui_name = "sumo-gui.exe" if os.name == "nt" else "sumo-gui"
        project_sumo_home = (root / ".tools" / "sumo").resolve()
        portable_sumo_home = (root / "runtime" / "sumo").resolve()
        configured_home = (
            Path(os.environ["SUMO_HOME"]).resolve() if os.environ.get("SUMO_HOME") else None
        )
        sumo_homes = [project_sumo_home, portable_sumo_home]
        if configured_home not in sumo_homes:
            sumo_homes.append(configured_home)
        sumo_home = next(
            (
                candidate
                for candidate in sumo_homes
                if candidate and (candidate / "bin" / gui_name).is_file()
            ),
            None,
        )
        if sumo_home is None:
            raise HTTPException(status_code=503, detail="project SUMO GUI not found")
        binary = sumo_home / "bin" / gui_name

        def launch() -> None:
            environment = os.environ.copy()
            environment["SUMO_HOME"] = str(sumo_home)
            launch_options: dict[str, object] = {}
            if os.name == "nt":
                launch_options["creationflags"] = subprocess.CREATE_NO_WINDOW
            subprocess.Popen(
                [str(binary), "-c", str(config)],
                cwd=str(folder),
                env=environment,
                **launch_options,
            )

        try:
            await asyncio.to_thread(launch)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"failed to open SUMO GUI: {exc}") from exc
        return {
            "opened": True,
            "scenario_id": scenario_id,
            "config_file": str(config),
        }

    @app.get("/api/v1/scenes/{scenario_id}/3d")
    async def get_3d_scene(scenario_id: str) -> FileResponse:
        """Serve a generated static scene; never synthesize one during a request."""

        if scenario_id not in state.scenarios:
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
            headers={"Cache-Control": "public, max-age=86400, immutable"},
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
                        "createdAt": datetime.fromtimestamp(
                            replay_stat.st_mtime, tz=UTC
                        ).isoformat(),
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
        if any(
            item["status"] in {"created", "starting", "running", "paused", "stopping"}
            for item in state.live_comparisons.values()
        ):
            raise HTTPException(
                status_code=409,
                detail="stop the live comparison before creating a single experiment",
            )
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
        if record["status"] in {"completed", "failed", "stopped"}:
            return {"id": id, "status": record["status"]}
        state.controls[id].stop()
        if record["status"] == "created":
            record["status"] = "stopped"
            state.digital_twin.set_status("stopped")
            await state._update_persisted_status(id, "stopped")
            return {"id": id, "status": "stopped"}
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

    @app.post("/api/v1/live-comparisons", status_code=201)
    async def create_live_comparison(request: LiveComparisonRequest) -> dict[str, object]:
        if request.scenario_id not in state.scenarios:
            raise HTTPException(status_code=422, detail="unknown scenario")
        if request.baseline_algorithm == request.candidate_algorithm:
            raise HTTPException(
                status_code=422,
                detail="baseline and candidate algorithms must be different",
            )
        available = {item["name"] for item in state.registry.discover()}
        unknown = [
            algorithm
            for algorithm in (request.baseline_algorithm, request.candidate_algorithm)
            if algorithm not in available
        ]
        if unknown:
            raise HTTPException(status_code=422, detail=f"unavailable algorithms: {unknown}")
        if request.profile != "BASE" and request.scenario_id not in state.scenario_profiles:
            raise HTTPException(status_code=422, detail="scenario has no validated profiles")
        if any(
            item["status"] in {"created", "starting", "running", "paused", "stopping"}
            for item in state.live_comparisons.values()
        ):
            raise HTTPException(status_code=409, detail="a live comparison is already active")
        if any(
            item["status"] in {"created", "running", "paused", "stopping", "finalizing"}
            for item in state.experiments.values()
        ):
            raise HTTPException(
                status_code=409,
                detail="stop the single experiment before creating a live comparison",
            )
        if any(item["status"] in {"queued", "running"} for item in state.benchmarks.values()):
            raise HTTPException(
                status_code=409,
                detail="wait for the algorithm benchmark before creating a live comparison",
            )

        config_name = (
            f"{request.scenario_id}.sumocfg"
            if request.profile == "BASE"
            else f"{request.scenario_id}.{request.profile}.sumocfg"
        )
        generated = state.workspace / "scenarios" / "generated" / request.scenario_id
        config_file = generated / config_name
        if not config_file.is_file():
            raise HTTPException(
                status_code=422,
                detail=f"generated SUMO configuration is unavailable: {config_name}",
            )
        selection_file = generated / "controlled_intersections.json"
        scenario_definition_file = (
            state.workspace / "scenarios" / "configs" / f"{request.scenario_id}.yaml"
        )
        profile_file = state.workspace / "scenarios" / "configs" / "presets" / "S01-S07.yaml"
        profile_set = state.scenario_profiles.get(request.scenario_id)
        profile = (
            profile_set.get(request.profile)
            if request.profile != "BASE" and profile_set is not None
            else None
        )
        cloud_outage = profile.cloud_outage_window() if profile is not None else None
        try:
            manifest = build_fairness_manifest(
                sumo_config=config_file,
                scenario_id=request.scenario_id,
                scenario_profile=request.profile,
                seed=request.seed,
                duration_s=request.duration_s,
                communication_profile={
                    "message_bus": os.environ.get("TRAFFIC_MESSAGE_BUS", "emulated"),
                    "cloud_outage_start_s": cloud_outage[0] if cloud_outage else None,
                    "cloud_outage_duration_s": cloud_outage[1] if cloud_outage else None,
                },
                runtime_files={
                    "controlled-intersections": selection_file,
                    "scenario-definition": scenario_definition_file,
                    "scenario-profiles": profile_file,
                },
            )
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        fingerprint = fairness_fingerprint(manifest)
        pair_id = f"pair-{uuid4().hex[:12]}"
        baseline_experiment_id = f"{pair_id}-baseline"
        candidate_experiment_id = f"{pair_id}-candidate"
        state.live_comparisons[pair_id] = {
            "id": pair_id,
            "status": "created",
            "request": request,
            "baseline_experiment_id": baseline_experiment_id,
            "candidate_experiment_id": candidate_experiment_id,
            "fairness_manifest": manifest,
            "fairness_fingerprint": fingerprint,
            "snapshots": {"baseline": None, "candidate": None},
            "result": None,
            "error": None,
            "created_at": datetime.now(UTC).isoformat(),
        }
        state.comparison_controls[pair_id] = PairedExperimentControl()
        state.comparison_twin.configure(
            pair_id=pair_id,
            scenario_id=request.scenario_id,
            baseline_algorithm=request.baseline_algorithm,
            candidate_algorithm=request.candidate_algorithm,
            baseline_experiment_id=baseline_experiment_id,
            candidate_experiment_id=candidate_experiment_id,
            fairness_manifest=manifest,
            fairness_fingerprint=fingerprint,
        )
        return {
            "id": pair_id,
            "status": "created",
            "fairness_fingerprint": fingerprint,
        }

    def live_comparison(pair_id: str) -> dict[str, Any]:
        record = state.live_comparisons.get(pair_id)
        if record is None:
            raise HTTPException(status_code=404, detail="live comparison not found")
        return record

    @app.get("/api/v1/live-comparisons/{pair_id}")
    async def get_live_comparison(pair_id: str) -> dict[str, object]:
        record = live_comparison(pair_id)
        snapshots = record["snapshots"]
        result = record.get("result")
        final_comparison = result.get("comparison") if isinstance(result, dict) else None
        comparison = (
            final_comparison
            if isinstance(final_comparison, dict)
            else state.comparison_twin.accumulator.summary()
            if state.comparison_twin.pair_id == pair_id
            else None
        )
        latest = {
            role: {
                "experiment_id": snapshot.get("experiment_id"),
                "simulation_time_s": snapshot.get("simulation_time_s"),
                "algorithm": snapshot.get("algorithm"),
            }
            if isinstance(snapshot, dict)
            else None
            for role, snapshot in snapshots.items()
        }
        return {
            **{
                key: value
                for key, value in record.items()
                if key not in {"request", "snapshots", "result"}
            },
            "request": record["request"].model_dump(mode="json"),
            "latest": latest,
            "result_available": record.get("result") is not None,
            "comparison": comparison,
        }

    @app.post("/api/v1/live-comparisons/{pair_id}/start")
    async def start_live_comparison(pair_id: str) -> dict[str, object]:
        record = live_comparison(pair_id)
        if record["status"] != "created":
            raise HTTPException(status_code=409, detail="live comparison cannot start")
        record["status"] = "starting"
        state.comparison_twin.set_status("starting")
        task = asyncio.create_task(
            state.start_live_comparison(pair_id),
            name=f"live-comparison-{pair_id}",
        )
        state.comparison_tasks[pair_id] = task
        return {"id": pair_id, "status": "starting"}

    @app.post("/api/v1/live-comparisons/{pair_id}/pause")
    async def pause_live_comparison(pair_id: str) -> dict[str, object]:
        record = live_comparison(pair_id)
        if record["status"] != "running":
            raise HTTPException(status_code=409, detail="live comparison is not running")
        state.comparison_controls[pair_id].pause()
        record["status"] = "paused"
        state.comparison_twin.set_status("paused")
        return {"id": pair_id, "status": "paused"}

    @app.post("/api/v1/live-comparisons/{pair_id}/resume")
    async def resume_live_comparison(pair_id: str) -> dict[str, object]:
        record = live_comparison(pair_id)
        if record["status"] != "paused":
            raise HTTPException(status_code=409, detail="live comparison is not paused")
        state.comparison_controls[pair_id].resume()
        record["status"] = "running"
        state.comparison_twin.set_status("running")
        return {"id": pair_id, "status": "running"}

    @app.post("/api/v1/live-comparisons/{pair_id}/rate")
    async def set_live_comparison_rate(
        pair_id: str,
        request: SimulationRateRequest,
    ) -> dict[str, object]:
        record = live_comparison(pair_id)
        if record["status"] not in {"created", "starting", "running", "paused"}:
            raise HTTPException(status_code=409, detail="live comparison cannot be paced")
        state.comparison_controls[pair_id].set_simulation_rate(request.rate)
        return {"id": pair_id, "simulation_rate": request.rate}

    @app.post("/api/v1/live-comparisons/{pair_id}/stop")
    async def stop_live_comparison(pair_id: str) -> dict[str, object]:
        record = live_comparison(pair_id)
        if record["status"] in {"completed", "failed", "stopped"}:
            return {"id": pair_id, "status": record["status"]}
        state.comparison_controls[pair_id].stop()
        if record["status"] == "created":
            record["status"] = "stopped"
            state.comparison_twin.set_status("stopped")
            return {"id": pair_id, "status": "stopped"}
        record["status"] = "stopping"
        state.comparison_twin.set_status("stopping")
        return {"id": pair_id, "status": "stopping"}

    @app.post(
        "/api/v1/live-comparisons/{pair_id}/faults/inject",
        status_code=202,
    )
    async def inject_live_comparison_fault(
        pair_id: str,
        request: FaultRequest,
    ) -> dict[str, object]:
        record = live_comparison(pair_id)
        if record["status"] not in {"running", "paused"}:
            raise HTTPException(
                status_code=409,
                detail="live comparison is not running or paused",
            )
        control = state.comparison_controls.get(pair_id)
        if control is None:
            raise HTTPException(status_code=409, detail="live comparison control is unavailable")

        now = datetime.now(UTC)
        experiment_ids = [
            record["baseline_experiment_id"],
            record["candidate_experiment_id"],
        ]
        fault_id = f"fault-{uuid4().hex[:10]}"
        comparison_request: LiveComparisonRequest = record["request"]
        canonical_parameters = dict(request.parameters)
        if request.fault_type == "incident":
            try:
                incident_target = state.comparison_twin.select_shared_incident_vehicle(
                    request.target,
                    comparison_request.seed,
                )
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            canonical_parameters.update(
                {
                    "vehicle_id": incident_target["vehicle_id"],
                    "edge_id": incident_target["edge_id"],
                }
            )
        fault = control.inject_fault(
            request.fault_type,
            {
                **canonical_parameters,
                "duration_s": request.duration_s,
                "target": request.target,
            },
            event_id=fault_id,
            target=request.target,
            seed=comparison_request.seed,
        )
        fault.update(
            {
                "pair_id": pair_id,
                "experiment_ids": experiment_ids,
                "severity": request.severity,
                "injected_at": now.isoformat(),
                # Kept only for older API consumers. Paired event activity and
                # expiry are authoritative on the SUMO timestamps above.
                "expires_at": (now + timedelta(seconds=request.duration_s)).isoformat(),
                "clock_authority": "simulation_time",
            }
        )
        state.faults.append(fault)
        await state.publish_fault_profile()
        return fault

    @app.post("/api/v1/live-comparisons/{pair_id}/faults/clear")
    async def clear_live_comparison_faults(pair_id: str) -> dict[str, object]:
        record = live_comparison(pair_id)
        if record["status"] not in {"running", "paused"}:
            raise HTTPException(
                status_code=409,
                detail="live comparison is not running or paused",
            )
        control = state.comparison_controls.get(pair_id)
        if control is None:
            raise HTTPException(status_code=409, detail="live comparison control is unavailable")
        experiment_ids = {
            str(record["baseline_experiment_id"]),
            str(record["candidate_experiment_id"]),
        }
        retained = [
            fault
            for fault in state.faults
            if experiment_ids.isdisjoint({str(item) for item in fault.get("experiment_ids", [])})
        ]
        cleared = len(state.faults) - len(retained)
        state.faults = retained
        control.clear_faults()
        await state.publish_fault_profile()
        return {"pair_id": pair_id, "cleared": cleared}

    @app.get("/api/v1/experiments/{id}/evidence")
    async def get_experiment_evidence(id: str) -> dict[str, object]:
        """Return a bounded, plot-ready trace from immutable SUMO evidence."""

        if Path(id).name != id:
            raise HTTPException(status_code=404, detail="experiment evidence not found")

        def load() -> dict[str, object]:
            direct = root / "results" / id / "result.json"
            candidates = (
                [direct]
                if direct.is_file()
                else list((root / "results" / "benchmarks").glob(f"*/runs/{id}/result.json"))
            )
            if not candidates:
                raise FileNotFoundError(id)
            payload = json.loads(candidates[0].read_text(encoding="utf-8"))
            raw_samples = payload.get("samples", [])
            samples = raw_samples if isinstance(raw_samples, list) else []
            stride = max(1, (len(samples) + 359) // 360)
            indices = list(range(0, len(samples), stride))
            if samples and indices[-1] != len(samples) - 1:
                indices.append(len(samples) - 1)
            series: list[dict[str, object]] = []
            for index in indices:
                sample = samples[index]
                if not isinstance(sample, dict):
                    continue
                by_intersection = sample.get("intersection_queue_vehicles", {})
                controlled_queue = (
                    sum(
                        float(value)
                        for value in by_intersection.values()
                        if isinstance(value, int | float)
                    )
                    if isinstance(by_intersection, dict)
                    else 0.0
                )
                series.append(
                    {
                        "simulation_time_s": sample.get("simulation_time_s"),
                        "total_queue_vehicles": sample.get("total_queue_vehicles"),
                        "total_queue_m": sample.get("total_queue_m"),
                        "controlled_queue_vehicles": controlled_queue,
                        "core_corridor_queue_vehicles": sample.get("core_corridor_queue_vehicles"),
                        "mean_speed_m_s": sample.get("mean_speed_m_s"),
                        "completed_trips": sample.get("completed_trips"),
                        "bicycle_completed_trips": sample.get("bicycle_completed_trips"),
                        "completed_vehicles": sample.get("completed_vehicles"),
                        "waiting_time_s": sample.get("waiting_time_s"),
                        "stop_count": sample.get("stop_count"),
                        "spillback_intersections": sample.get("spillback_intersections"),
                        "congested_intersections": sample.get("congested_intersections"),
                        "fuel_mg": sample.get("fuel_mg"),
                        "co2_mg": sample.get("co2_mg"),
                        "nox_mg": sample.get("nox_mg"),
                        "emergency_braking_count": sample.get("emergency_braking_count"),
                        "acceleration_variance": sample.get("acceleration_variance"),
                        "motor_motor_conflict_count": sample.get("motor_motor_conflict_count"),
                        "motor_bicycle_conflict_count": sample.get("motor_bicycle_conflict_count"),
                        "motor_pedestrian_conflict_count": sample.get(
                            "motor_pedestrian_conflict_count"
                        ),
                        "bicycle_pedestrian_conflict_count": sample.get(
                            "bicycle_pedestrian_conflict_count"
                        ),
                        "minimum_ttc_s": sample.get("minimum_ttc_s"),
                        "minimum_pet_s": sample.get("minimum_pet_s"),
                        "intersection_queue_vehicles": sample.get("intersection_queue_vehicles"),
                        "intersection_mean_speed_m_s": sample.get("intersection_mean_speed_m_s"),
                        "max_downstream_occupancy": sample.get("max_downstream_occupancy"),
                        "vehicle_trajectory_probes": sample.get("vehicle_trajectory_probes"),
                        "cpu_percent": sample.get("cpu_percent"),
                        "memory_mb": sample.get("memory_mb"),
                        "fallback_mode": sample.get("fallback_mode"),
                        "cloud_online": sample.get("cloud_online"),
                        "mqtt_online": sample.get("mqtt_online"),
                        "prediction_status": sample.get("prediction_status"),
                        "prediction_model_id": sample.get("prediction_model_id"),
                        "prediction_horizon_s": sample.get("prediction_horizon_s"),
                        "prediction_confidence": sample.get("prediction_confidence"),
                        "predicted_queue_vehicles": sample.get("predicted_queue_vehicles"),
                        "predicted_spillback_risk": sample.get("predicted_spillback_risk"),
                        "selected_policy_counts": sample.get("selected_policy_counts"),
                        "candidate_policy_score_mean": sample.get("candidate_policy_score_mean"),
                        "b3_expected_gain_ratio": sample.get("b3_expected_gain_ratio"),
                        "target_speed_factor_mean": sample.get("target_speed_factor_mean"),
                        "signal_action_executed_count": sample.get("signal_action_executed_count"),
                        "signal_action_modified_count": sample.get("signal_action_modified_count"),
                        "signal_action_rejected_count": sample.get("signal_action_rejected_count"),
                        "signal_action_rejection_reasons": sample.get(
                            "signal_action_rejection_reasons"
                        ),
                    }
                )
            return {
                "experiment_id": payload.get("experiment_id", id),
                "scenario_id": payload.get("scenario_id"),
                "algorithm": payload.get("algorithm"),
                "profile": payload.get("scenario_profile"),
                "seed": payload.get("seed"),
                "actual_run": payload.get("actual_run") is True,
                "metrics": payload.get("metrics", {}),
                "source_sample_count": len(samples),
                "sample_stride": stride,
                "series": series,
            }

        try:
            return await asyncio.to_thread(load)
        except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=404,
                detail="experiment evidence not found",
            ) from exc

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

    @app.post("/api/v1/benchmarks", status_code=202)
    async def create_benchmark(request: BenchmarkRequest) -> dict[str, object]:
        state.refresh_benchmarks_from_disk()
        available = {item["name"] for item in state.registry.discover()}
        if len(set(request.algorithms)) != len(request.algorithms):
            raise HTTPException(status_code=422, detail="algorithms must be unique")
        unknown = [name for name in request.algorithms if name not in available]
        if unknown:
            raise HTTPException(status_code=422, detail=f"unavailable algorithms: {unknown}")
        if len(set(request.seeds)) != len(request.seeds):
            raise HTTPException(status_code=422, detail="seeds must be unique")
        if len(request.algorithms) * len(request.seeds) > 20:
            raise HTTPException(status_code=422, detail="benchmark matrix is limited to 20 runs")
        if any(item["status"] in {"queued", "running"} for item in state.benchmarks.values()):
            raise HTTPException(status_code=409, detail="an algorithm benchmark is already active")
        if any(
            item["status"] in {"created", "running", "paused"}
            for item in state.experiments.values()
        ):
            raise HTTPException(
                status_code=409, detail="stop the live experiment before benchmarking"
            )
        if any(
            item["status"] in {"created", "starting", "running", "paused", "stopping"}
            for item in state.live_comparisons.values()
        ):
            raise HTTPException(
                status_code=409, detail="stop the live comparison before benchmarking"
            )
        benchmark_id = f"benchmark-{uuid4().hex[:12]}"
        total_runs = len(request.algorithms) * len(request.seeds)
        state.benchmarks[benchmark_id] = {
            "id": benchmark_id,
            "status": "queued",
            "progress": 0,
            "message": "等待实际公平配对实验矩阵",
            "request": request,
            "completed_runs": 0,
            "total_runs": total_runs,
            "rows": [],
            "result": None,
            "output_dir": None,
            "error": None,
            "created_at": datetime.now(UTC).isoformat(),
        }
        task = asyncio.create_task(
            state.start_benchmark(benchmark_id),
            name=f"algorithm-{benchmark_id}",
        )
        state.benchmark_tasks[benchmark_id] = task
        return {"id": benchmark_id, "status": "queued", "total_runs": total_runs}

    @app.get("/api/v1/benchmarks")
    async def list_benchmarks() -> dict[str, object]:
        state.refresh_benchmarks_from_disk()
        return {
            "items": [
                {
                    **{key: value for key, value in item.items() if key != "request"},
                    "request": item["request"].model_dump(mode="json"),
                }
                for item in sorted(
                    state.benchmarks.values(),
                    key=lambda value: value["created_at"],
                    reverse=True,
                )
            ]
        }

    @app.get("/api/v1/benchmarks/{benchmark_id}")
    async def get_benchmark(benchmark_id: str) -> dict[str, object]:
        state.refresh_benchmarks_from_disk()
        record = state.benchmarks.get(benchmark_id)
        if record is None:
            raise HTTPException(status_code=404, detail="benchmark not found")
        return {
            **{key: value for key, value in record.items() if key != "request"},
            "request": record["request"].model_dump(mode="json"),
        }

    @app.get("/api/v1/benchmarks/{benchmark_id}/artifacts/{name}")
    async def get_benchmark_artifact(benchmark_id: str, name: str) -> FileResponse:
        state.refresh_benchmarks_from_disk()
        record = state.benchmarks.get(benchmark_id)
        if record is None or record.get("status") != "completed":
            raise HTTPException(status_code=404, detail="benchmark artifact not found")
        allowed = {
            "benchmark.json": "application/json",
            "benchmark.csv": "text/csv",
            "benchmark.html": "text/html",
        }
        if name not in allowed:
            raise HTTPException(status_code=404, detail="benchmark artifact not found")
        path = Path(str(record["output_dir"])) / name
        if not path.is_file():
            raise HTTPException(status_code=404, detail="benchmark artifact not found")
        return FileResponse(path, media_type=allowed[name], filename=name)

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
            "experiment_ids": [
                *state.controls,
                *[
                    child_id
                    for item in state.live_comparisons.values()
                    for child_id in (
                        item["baseline_experiment_id"],
                        item["candidate_experiment_id"],
                    )
                ],
            ],
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
        for control in state.comparison_controls.values():
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
        for control in state.comparison_controls.values():
            control.clear_faults()
        await state.publish_fault_profile()
        return {"cleared": cleared}

    @app.get("/api/v1/faults")
    async def faults() -> dict[str, object]:
        now = datetime.now(UTC)
        state.faults = [
            item
            for item in state.faults
            if (
                item.get("status") not in {"expired", "cleared", "failed"}
                and (
                    item.get("clock_authority") == "simulation_time"
                    or datetime.fromisoformat(str(item["expires_at"])) > now
                )
            )
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

    @app.websocket("/ws/v1/digital-twin/comparison")
    async def comparison_digital_twin(websocket: WebSocket) -> None:
        """Send one atomic baseline/candidate/delta frame per synchronized time."""

        await websocket.accept()
        initial = state.comparison_twin.initial_message()
        await websocket.send_json(initial)
        raw_initial_sequence = initial["sequence"]
        sequence = int(raw_initial_sequence) if isinstance(raw_initial_sequence, int | str) else 0
        try:
            while True:
                for message in state.comparison_twin.messages_after(sequence):
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
