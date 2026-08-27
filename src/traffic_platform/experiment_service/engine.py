"""Actual SUMO-cloud-edge-vehicle experiment runner."""

import asyncio
import json
import os
import platform
import statistics
import time
import xml.etree.ElementTree as ET
from collections import deque
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

import psutil

from traffic_platform.algorithm_sdk.types import (
    AlgorithmConfig,
    ControlDecision,
    DecisionStatus,
    NetworkTopology,
)
from traffic_platform.cloud_service.coordinator import (
    CoordinatorConfig,
    RegionalCoordinator,
)
from traffic_platform.cloud_service.runtime import CloudRuntime
from traffic_platform.communication_emulator.channel import ChannelConfig
from traffic_platform.contracts.factory import MessageFactory
from traffic_platform.contracts.models import (
    ActionType,
    CommunicationEvent,
    EdgeControlAction,
    EmissionEstimate,
    ExecutionFeedback,
    ExecutionStatus,
    ExperimentEvent,
    IntersectionState,
    MetricSnapshot,
    PositionXY,
    SourceType,
    SpeedGuidance,
    ValidationStatus,
    VehicleGuidanceCommand,
    VehicleState,
)
from traffic_platform.edge_service.aggregation import EdgeStateAggregator
from traffic_platform.edge_service.controller import EdgeController
from traffic_platform.edge_service.runtime import EdgeRuntime
from traffic_platform.edge_service.state_machine import DegradationConfig, EdgeMode
from traffic_platform.experiment_service.disturbances import DisturbanceRuntime
from traffic_platform.experiment_service.sample_fields import (
    intersection_sample_fields,
    prediction_sample_fields,
    runner_manifest_fields,
    runner_options,
)
from traffic_platform.messaging.base import MessageBus
from traffic_platform.messaging.emulated import EmulatedMessageBus
from traffic_platform.messaging.mqtt import MqttMessageBus
from traffic_platform.metrics_engine.calculator import MetricsAccumulator, MetricSample
from traffic_platform.metrics_engine.surrogate_safety import SurrogateSafetyMonitor
from traffic_platform.realtime import DigitalTwinSourceFrame
from traffic_platform.report_service.generator import generate_report
from traffic_platform.safety_kernel import SafetyContext, SafetyOutcome
from traffic_platform.scenario_engine.manifest import build_manifest
from traffic_platform.scenario_engine.models import Disturbance, ScenarioConfig
from traffic_platform.scenario_engine.profiles import ScenarioProfileSet
from traffic_platform.sumo_adapter import TraciSumoAdapter, VehicleSnapshot
from traffic_platform.vehicle_agent.agent import (
    GlosaEffectivenessGate,
    GlosaMobilityRegimeClassifier,
    VehicleDynamics,
    VehicleGuidanceAgent,
)


@dataclass(frozen=True, slots=True)
class ScheduledFault:
    """One deterministic live-fault injection on the simulation clock."""

    fault_type: str
    start_s: float
    duration_s: float
    parameters: dict[str, float | str | bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.start_s < 0:
            raise ValueError("scheduled fault start_s must be non-negative")
        if self.duration_s <= 0:
            raise ValueError("scheduled fault duration_s must be positive")


@dataclass(frozen=True, slots=True)
class QueuedLiveFault:
    """One canonical live fault waiting for its authoritative SUMO timestamp."""

    event_id: str
    fault_type: str
    apply_at_simulation_time_s: float
    duration_s: float
    parameters: dict[str, float | str | bool]


@dataclass(frozen=True, slots=True)
class ExperimentConfig:
    """One reproducible experiment execution request."""

    experiment_id: str
    scenario_id: str
    algorithm: str
    seed: int
    duration_s: float
    config_file: Path
    selection_file: Path
    result_dir: Path
    scenario_definition_file: Path | None = None
    scenario_profile_code: str = "BASE"
    scenario_profile_file: Path | None = None
    cloud_interval_s: float = 5.0
    gui: bool = False
    cloud_outage_start_s: float | None = None
    cloud_outage_duration_s: float | None = None
    degradation_config: DegradationConfig | None = None
    disturbance_time_scale: float = 1.0
    scheduled_faults: tuple[ScheduledFault, ...] = ()
    isolate_algorithms: bool = True
    publish_feedback_to_bus: bool = True
    publish_runtime_telemetry_to_bus: bool = True
    include_communication_events: bool = True
    surrogate_safety_interval_s: float = 1.0
    sumo_extra_args: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Reject non-causal schedule scaling at configuration time."""

        if self.disturbance_time_scale <= 0:
            raise ValueError("disturbance_time_scale must be positive")
        if self.surrogate_safety_interval_s <= 0:
            raise ValueError("surrogate_safety_interval_s must be positive")


class ExperimentControl:
    """Cooperative pause, resume, stop and cloud-availability controls."""

    def __init__(self) -> None:
        self._running = asyncio.Event()
        self._running.set()
        self.stop_requested = False
        self.cloud_online = True
        self.edge_online = True
        self.broker_online = True
        self.edge_outage_duration_s = 30.0
        self.broker_outage_duration_s = 30.0
        self.roadwork_active = False
        self.channel_config = ChannelConfig()
        self.simulation_time_s = 0.0
        # ``None`` preserves the historical maximum-throughput runner. A finite
        # value paces SUMO simulation seconds against wall-clock seconds without
        # changing SUMO state, demand or control decisions.
        self.simulation_rate: float | None = None
        self._active_faults: dict[
            str,
            tuple[str, float, dict[str, float | str | bool]],
        ] = {}
        self._queued_faults: list[QueuedLiveFault] = []
        self._pending_disturbances: list[Disturbance] = []
        self._dynamic_disturbance_counter = 0
        self._dynamic_fault_ids: set[str] = set()
        self._applied_dynamic_fault_ids: set[str] = set()
        self._fault_status_callback: Callable[[str, str, float, str | None], None] | None = None

    def pause(self) -> None:
        """Pause before the next SUMO simulation step."""

        self._running.clear()

    def resume(self) -> None:
        """Allow SUMO stepping to continue."""

        self._running.set()

    def stop(self) -> None:
        """Request graceful termination and release any paused waiter."""

        self.stop_requested = True
        self._running.set()

    def set_simulation_rate(self, rate: float | None) -> None:
        """Set wall-clock pacing; ``None`` means maximum computation speed."""

        if rate is not None and (rate <= 0 or rate > 32):
            raise ValueError("simulation rate must be in (0, 32]")
        self.simulation_rate = rate

    async def wait_until_running(self) -> None:
        """Wait without blocking the service event loop."""

        await self._running.wait()

    def inject_fault(
        self,
        fault_type: str,
        parameters: dict[str, float | str | bool],
    ) -> None:
        """Apply a live, runner-observed fault configuration."""

        self._activate_fault(
            f"standalone-{uuid4().hex[:12]}",
            fault_type,
            parameters,
            canonical_dynamic=False,
        )

    def set_fault_status_callback(
        self,
        callback: Callable[[str, str, float, str | None], None] | None,
    ) -> None:
        """Receive causal state changes for pair-level fault auditing."""

        self._fault_status_callback = callback

    def queue_fault(
        self,
        *,
        event_id: str,
        fault_type: str,
        apply_at_simulation_time_s: float,
        parameters: dict[str, float | str | bool],
    ) -> None:
        """Queue a canonical event without applying it between SUMO steps."""

        duration_s = float(parameters.get("duration_s", 30.0))
        if duration_s <= 0:
            raise ValueError("fault duration_s must be positive")
        if apply_at_simulation_time_s < self.simulation_time_s:
            raise ValueError("fault application time cannot precede the SUMO clock")
        if any(item.event_id == event_id for item in self._queued_faults):
            raise ValueError(f"duplicate queued fault event_id: {event_id}")
        self._queued_faults.append(
            QueuedLiveFault(
                event_id=event_id,
                fault_type=fault_type,
                apply_at_simulation_time_s=apply_at_simulation_time_s,
                duration_s=duration_s,
                parameters=dict(parameters),
            )
        )
        self._report_fault_status(event_id, "pending", self.simulation_time_s)

    def _activate_fault(
        self,
        event_id: str,
        fault_type: str,
        parameters: dict[str, float | str | bool],
        *,
        canonical_dynamic: bool,
    ) -> None:
        duration_s = float(parameters.get("duration_s", 30.0))
        if duration_s <= 0:
            raise ValueError("fault duration_s must be positive")
        dynamic_types = {"incident", "flow_surge", "large_event"}
        if canonical_dynamic:
            dynamic_types.add("roadwork")
        if fault_type in dynamic_types:
            self._dynamic_disturbance_counter += 1
            disturbance_parameters: dict[str, float | str | bool] = {}
            if fault_type in {"flow_surge", "large_event"}:
                disturbance_parameters["flow_multiplier"] = float(
                    parameters.get(
                        "flow_multiplier",
                        2.5 if fault_type == "large_event" else 1.8,
                    )
                )
            if fault_type == "incident":
                for parameter_name in ("vehicle_id", "edge_id"):
                    parameter_value = parameters.get(parameter_name)
                    if isinstance(parameter_value, str) and parameter_value:
                        disturbance_parameters[parameter_name] = parameter_value
            lane_id = parameters.get("lane_id")
            if fault_type == "roadwork" and isinstance(lane_id, str) and lane_id:
                disturbance_parameters["lane_id"] = lane_id
            self._pending_disturbances.append(
                Disturbance.model_validate(
                    {
                        "event_id": event_id,
                        "type": (
                            fault_type
                            if fault_type in {"incident", "roadwork"}
                            else "event_dispersal"
                        ),
                        "simulation_time_s": self.simulation_time_s,
                        "duration_s": duration_s,
                        "target": str(
                            parameters.get(
                                "target",
                                "downstream_bottleneck"
                                if fault_type == "incident"
                                else (
                                    "north_activity"
                                    if fault_type == "large_event"
                                    else "network_local"
                                ),
                            )
                        ),
                        "parameters": disturbance_parameters,
                    },
                    strict=True,
                )
            )
            self._dynamic_fault_ids.add(event_id)
        active_parameters = dict(parameters)
        if canonical_dynamic and fault_type == "roadwork":
            active_parameters["_physical_disturbance"] = True
        self._active_faults[event_id] = (
            fault_type,
            self.simulation_time_s + duration_s,
            active_parameters,
        )
        self._recompute_fault_state()
        self._report_fault_status(
            event_id,
            "scheduled" if event_id in self._dynamic_fault_ids else "applied",
            self.simulation_time_s,
        )

    def drain_pending_disturbances(self) -> list[Disturbance]:
        pending = self._pending_disturbances
        self._pending_disturbances = []
        return pending

    def _recompute_fault_state(self) -> None:
        """Derive active controls from independently expiring fault records."""

        self.cloud_online = True
        self.edge_online = True
        self.broker_online = True
        self.roadwork_active = False
        self.edge_outage_duration_s = 30.0
        self.broker_outage_duration_s = 30.0
        base_latency_ms = 0.0
        jitter_ms = 0.0
        packet_loss_rate = 0.0
        corruption_rate = 0.0
        for fault_type, _expires_at, parameters in self._active_faults.values():
            if fault_type == "cloud_offline":
                self.cloud_online = False
            elif fault_type == "edge_offline":
                self.edge_online = False
                self.edge_outage_duration_s = float(parameters.get("duration_s", 30.0))
            elif fault_type in {"mqtt_broker_offline", "broker_offline"}:
                self.broker_online = False
                self.broker_outage_duration_s = float(parameters.get("duration_s", 30.0))
            elif fault_type == "roadwork" and not bool(
                parameters.get("_physical_disturbance", False)
            ):
                self.roadwork_active = True
            elif fault_type == "communication_latency":
                base_latency_ms = float(parameters.get("latency_ms", 0.0))
                jitter_ms = float(parameters.get("jitter_ms", jitter_ms))
            elif fault_type == "packet_loss":
                packet_loss_rate = float(parameters.get("packet_loss_rate", 0.0))
            elif fault_type == "communication_corruption":
                corruption_rate = float(parameters.get("corruption_rate", 0.0))
        self.channel_config = ChannelConfig(
            base_latency_ms=base_latency_ms,
            packet_loss_rate=packet_loss_rate,
            jitter_ms=jitter_ms,
            corruption_rate=corruption_rate,
        )

    def advance_simulation_time(self, simulation_time_s: float) -> list[str]:
        """Expire live faults on the causal SUMO clock and report removals."""

        self.simulation_time_s = simulation_time_s
        due = [
            item
            for item in self._queued_faults
            if simulation_time_s + 1e-9 >= item.apply_at_simulation_time_s
        ]
        self._queued_faults = [item for item in self._queued_faults if item not in due]
        for item in due:
            self._activate_fault(
                item.event_id,
                item.fault_type,
                item.parameters,
                canonical_dynamic=True,
            )
        expired = [
            (event_id, fault_type)
            for event_id, (fault_type, expires_at, _parameters) in self._active_faults.items()
            if simulation_time_s >= expires_at
        ]
        if expired:
            for event_id, _fault_type in expired:
                del self._active_faults[event_id]
                was_dynamic = event_id in self._dynamic_fault_ids
                self._dynamic_fault_ids.discard(event_id)
                if was_dynamic and event_id not in self._applied_dynamic_fault_ids:
                    self._report_fault_status(
                        event_id,
                        "failed",
                        simulation_time_s,
                        "physical disturbance was not applied before expiry",
                    )
                else:
                    self._report_fault_status(event_id, "expired", simulation_time_s)
                self._applied_dynamic_fault_ids.discard(event_id)
            self._recompute_fault_state()
        return [fault_type for _event_id, fault_type in expired]

    def mark_disturbance_applied(
        self,
        event_id: str,
        simulation_time_s: float,
        detail: str | None = None,
    ) -> None:
        """Acknowledge that a queued physical disturbance reached TraCI."""

        if event_id in self._dynamic_fault_ids:
            self._applied_dynamic_fault_ids.add(event_id)
            self._report_fault_status(event_id, "applied", simulation_time_s, detail)

    def _report_fault_status(
        self,
        event_id: str,
        status: str,
        simulation_time_s: float,
        detail: str | None = None,
    ) -> None:
        if self._fault_status_callback is not None:
            self._fault_status_callback(event_id, status, simulation_time_s, detail)

    def clear_faults(self) -> None:
        """Restore normal cloud, road and communication conditions."""

        event_ids = [*self._active_faults, *(item.event_id for item in self._queued_faults)]
        self._active_faults.clear()
        self._queued_faults.clear()
        self._dynamic_fault_ids.clear()
        self._applied_dynamic_fault_ids.clear()
        self._recompute_fault_state()
        for event_id in event_ids:
            self._report_fault_status(event_id, "cleared", self.simulation_time_s)


def _traci_label(experiment_id: str) -> str:
    """Keep sibling experiments distinct even when they share a pair prefix."""

    return f"experiment-{experiment_id}"


class ExperimentRunner:
    """Drive the complete Phase 1 vertical slice with a pluggable bus."""

    def __init__(
        self,
        config: ExperimentConfig,
        *,
        sumo_home: Path,
        bus: MessageBus | None = None,
        control: ExperimentControl | None = None,
        snapshot_callback: Callable[[dict[str, object]], None] | None = None,
        snapshot_detail: Literal["full", "progress"] = "full",
        digital_twin_callback: Callable[[DigitalTwinSourceFrame], None] | None = None,
        digital_twin_schedule_callback: (
            Callable[[float, float], float | None] | None
        ) = None,
        step_barrier_callback: Callable[[float], Awaitable[None]] | None = None,
        persistence_callback: (Callable[[str, dict[str, object]], Awaitable[None]] | None) = None,
    ) -> None:
        self.config = config
        self.sumo_home = sumo_home
        self.bus = bus or EmulatedMessageBus(seed=config.seed)
        self.control = control or ExperimentControl()
        self.snapshot_callback = snapshot_callback
        self.snapshot_detail = snapshot_detail
        self.digital_twin_callback = digital_twin_callback
        self.digital_twin_schedule_callback = digital_twin_schedule_callback
        self.step_barrier_callback = step_barrier_callback
        self.persistence_callback = persistence_callback
        self.events: list[dict[str, str | float]] = []

    async def run(self) -> dict[str, object]:
        """Run SUMO until the requested time and emit actual report artifacts."""

        selection = json.loads(self.config.selection_file.read_text(encoding="utf-8"))
        intersection_ids = [item["intersection_id"] for item in selection["intersections"]]
        edge_factory = MessageFactory(
            source_id="edge-rongdong",
            source_type=SourceType.EDGE,
            scenario_id=self.config.scenario_id,
            experiment_id=self.config.experiment_id,
        )
        rsu_factory = MessageFactory(
            source_id="sumo-rsu-gateway",
            source_type=SourceType.RSU,
            scenario_id=self.config.scenario_id,
            experiment_id=self.config.experiment_id,
        )
        cloud_factory = MessageFactory(
            source_id="cloud-regional",
            source_type=SourceType.CLOUD,
            scenario_id=self.config.scenario_id,
            experiment_id=self.config.experiment_id,
        )
        vehicle_factory = MessageFactory(
            source_id="sumo-vehicle-gateway",
            source_type=SourceType.VEHICLE,
            scenario_id=self.config.scenario_id,
            experiment_id=self.config.experiment_id,
        )
        experiment_factory = MessageFactory(
            source_id="experiment-runner",
            source_type=SourceType.EXPERIMENT,
            scenario_id=self.config.scenario_id,
            experiment_id=self.config.experiment_id,
        )
        adapter = TraciSumoAdapter(
            sumo_home=self.sumo_home,
            # Paired child IDs intentionally share a parent prefix. Keep the
            # complete identifier so TraCI never aliases baseline/candidate.
            label=_traci_label(self.config.experiment_id),
        )
        accumulator = MetricsAccumulator()
        process = psutil.Process(os.getpid())
        samples: list[dict[str, object]] = []
        trajectory_hz = 0.0
        dashboard_hz = 1.0
        if (
            self.config.scenario_definition_file is not None
            and self.config.scenario_definition_file.is_file()
        ):
            sampling = ScenarioConfig.from_yaml(self.config.scenario_definition_file).sampling
            trajectory_hz = sampling.vehicle_trajectory_hz
            dashboard_hz = sampling.dashboard_hz
        trajectory_interval_s = 1.0 / trajectory_hz if trajectory_hz > 0 else float("inf")
        next_trajectory_time_s = 0.0
        digital_twin_interval_s = 1.0 / dashboard_hz
        next_digital_twin_time_s = 0.0
        started_wall = time.perf_counter()
        executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix=f"sumo-{self.config.experiment_id[-20:]}",
        )
        loop = asyncio.get_running_loop()

        async def run_blocking(
            function: Callable[..., Any],
            /,
            *args: Any,
            **kwargs: Any,
        ) -> Any:
            # One dedicated worker keeps each TraCI connection thread-affine and
            # prevents paired runners from contending for the process-wide pool.
            return await loop.run_in_executor(executor, partial(function, *args, **kwargs))

        phase_history_ms: dict[str, deque[float]] = {
            name: deque(maxlen=120)
            for name in (
                "sumo_step",
                "disturbance",
                "aggregation",
                "control",
                "telemetry",
                "barrier",
                "total",
            )
        }

        def record_phase(name: str, started_at: float) -> None:
            phase_history_ms[name].append((time.perf_counter() - started_at) * 1000.0)

        def percentile(values: deque[float], fraction: float) -> float:
            if not values:
                return 0.0
            ordered = sorted(values)
            return ordered[min(len(ordered) - 1, round((len(ordered) - 1) * fraction))]

        def performance_snapshot() -> dict[str, object]:
            total_p50_ms = percentile(phase_history_ms["total"], 0.50)
            total_p95_ms = percentile(phase_history_ms["total"], 0.95)
            return {
                "sample_count": len(phase_history_ms["total"]),
                "step_p50_ms": round(total_p50_ms, 3),
                "step_p95_ms": round(total_p95_ms, 3),
                "achievable_rate_p50": (
                    round(1000.0 / total_p50_ms, 3) if total_p50_ms > 0 else None
                ),
                "achievable_rate_p95": (
                    round(1000.0 / total_p95_ms, 3) if total_p95_ms > 0 else None
                ),
                "phase_p95_ms": {
                    name: round(percentile(values, 0.95), 3)
                    for name, values in phase_history_ms.items()
                    if name != "total"
                },
            }

        def current_digital_twin_interval_s() -> float:
            target_rate = self.control.simulation_rate
            if target_rate is None:
                return digital_twin_interval_s
            # The browser interpolates SUMO frames. Four wall-clock updates per
            # second are enough for smooth motion and avoid making x8 encode and
            # fan out eight full paired frames every second.
            return max(digital_twin_interval_s, target_rate / 4.0)

        controller: EdgeController | None = None
        edge_runtime: EdgeRuntime | None = None
        pending_vehicle_commands: dict[str, VehicleGuidanceCommand] = {}
        pending_edge_actions: dict[str, EdgeControlAction] = {}
        remote_communication_events: list[CommunicationEvent] = []
        remote_action_event = asyncio.Event()
        published_event_index = 0
        digital_twin_event_index = 0
        seen_strategy_ids: set[str] = set()

        async def handle_vehicle_command(_topic: str, payload: bytes) -> None:
            command = VehicleGuidanceCommand.model_validate_json(payload)
            command.ensure_not_expired()
            if (
                command.experiment_id == self.config.experiment_id
                and command.executed
                and command.applied_speed_m_s is not None
            ):
                pending_vehicle_commands[command.vehicle_id] = command

        async def handle_edge_action(_topic: str, payload: bytes) -> None:
            action = EdgeControlAction.model_validate_json(payload)
            if action.expires_at <= datetime.now(UTC):
                return
            if action.experiment_id == self.config.experiment_id:
                pending_edge_actions[action.intersection_id] = action
                remote_action_event.set()

        async def handle_external_event(_topic: str, payload: bytes) -> None:
            event = ExperimentEvent.model_validate_json(payload)
            if (
                event.experiment_id != self.config.experiment_id
                or event.source_id == "experiment-runner"
            ):
                return
            self.events.append(
                {
                    "simulation_time": event.simulation_time,
                    "event": event.event_type,
                    "detail": json.dumps(
                        event.payload,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                }
            )

        async def handle_communication_event(
            _topic: str,
            payload: bytes,
        ) -> None:
            event = CommunicationEvent.model_validate_json(payload)
            if event.experiment_id == self.config.experiment_id:
                remote_communication_events.append(event)

        cloud_latencies_ms: list[float] = []
        edge_latencies_ms: list[float] = []
        remote_cloud_latencies_ms: list[float] = []
        remote_edge_latencies_ms: list[float] = []
        remote_control_latencies_ms: list[float] = []
        remote_action_count = 0
        remote_action_rejection_count = 0
        self.config.result_dir.mkdir(parents=True, exist_ok=True)
        await self.bus.connect()
        if isinstance(self.bus, MqttMessageBus):
            await self.bus.subscribe(
                "traffic/development/vehicle/+/command",
                handle_vehicle_command,
                qos=1,
            )
            await self.bus.subscribe(
                "traffic/development/edge/+/action/+",
                handle_edge_action,
                qos=1,
            )
            await self.bus.subscribe(
                (f"traffic/development/experiment/{self.config.experiment_id}/event"),
                handle_external_event,
                qos=1,
            )
            await self.bus.subscribe(
                (f"traffic/development/experiment/{self.config.experiment_id}/communication"),
                handle_communication_event,
                qos=1,
            )
        try:
            await run_blocking(
                adapter.start_simulation,
                self.config.config_file,
                gui=self.config.gui,
                seed=self.config.seed,
                extra_args=[
                    "--summary-output",
                    str((self.config.result_dir / "summary.xml").resolve()),
                    "--tripinfo-output",
                    str((self.config.result_dir / "tripinfo.xml").resolve()),
                    "--tripinfo-output.write-unfinished",
                    "true",
                    "--statistic-output",
                    str((self.config.result_dir / "statistics.xml").resolve()),
                    *self.config.sumo_extra_args,
                ],
            )
            evaluation_start_simulation_time_s = (
                await run_blocking(adapter.get_network_state)
            ).simulation_time_s
            aggregator = EdgeStateAggregator(
                adapter,
                rsu_factory if isinstance(self.bus, MqttMessageBus) else edge_factory,
                intersection_ids,
            )
            # Topology discovery performs many synchronous TraCI round trips.
            # Keep health checks, WebSockets and the control API responsive
            # while the live SUMO connection is being initialized.
            topology = await run_blocking(aggregator.build_topology)
            controller = EdgeController(
                adapter,
                edge_factory,
                topology,
                algorithm_config=AlgorithmConfig(),
                degradation_config=self.config.degradation_config,
                control_algorithm=self.config.algorithm,
                isolate_algorithms=self.config.isolate_algorithms,
            )
            edge_runtime = EdgeRuntime(
                self.bus,
                controller,
                environment="development",
                edge_id="edge-rongdong",
            )
            assert edge_runtime is not None
            cloud_runtime = CloudRuntime(
                self.bus,
                RegionalCoordinator(
                    cloud_factory,
                    CoordinatorConfig.from_selection(selection),
                ),
                environment="development",
            )
            if not isinstance(self.bus, MqttMessageBus):
                await edge_runtime.start()
                await cloud_runtime.start()
            guidance_agent = VehicleGuidanceAgent()
            safety_monitor = SurrogateSafetyMonitor()
            next_safety_sample_time = 0.0
            next_cloud_time = 0.0
            completed_total = 0
            completed_bicycle_total = 0
            completed_pedestrian_total = 0
            vehicle_class_history: dict[str, str] = {}
            crossing_pedestrians: set[str] = set()
            completed_crossings = 0
            roadwork_lane_id = self._roadwork_lane(topology)
            roadwork_applied = False
            disturbance_runtime = self._disturbance_runtime(
                roadwork_lane_id,
                topology,
            )
            emergency_priority_detections: set[tuple[str, str]] = set()
            broker_outage_end_s: float | None = None
            edge_outage_end_s: float | None = None
            distributed_control_mode = EdgeMode.EDGE_AUTONOMOUS.value
            latest_control_evidence: dict[str, dict[str, object]] = {}
            last_paced_simulation_time: float | None = None
            injected_scheduled_faults: set[int] = set()
            while adapter.running:
                await self.control.wait_until_running()
                if self.control.stop_requested:
                    self.events.append(
                        {
                            "simulation_time": adapter.get_network_state().simulation_time_s,
                            "event": "STOP_REQUESTED",
                        }
                    )
                    break
                step_wall_started = time.perf_counter()
                phase_started = time.perf_counter()
                network = await run_blocking(adapter.step)
                record_phase("sumo_step", phase_started)
                phase_started = time.perf_counter()
                if (
                    network.simulation_time_s
                    > evaluation_start_simulation_time_s + self.config.duration_s
                ):
                    break
                for expired_fault in self.control.advance_simulation_time(
                    network.simulation_time_s
                ):
                    self.events.append(
                        {
                            "simulation_time": network.simulation_time_s,
                            "event": "FAULT_AUTO_CLEARED",
                            "detail": expired_fault,
                        }
                    )
                for fault_index, fault in enumerate(self.config.scheduled_faults):
                    if fault_index in injected_scheduled_faults:
                        continue
                    if network.simulation_time_s + 1e-9 < fault.start_s:
                        continue
                    self.control.inject_fault(
                        fault.fault_type,
                        {
                            **fault.parameters,
                            "duration_s": fault.duration_s,
                        },
                    )
                    injected_scheduled_faults.add(fault_index)
                    self.events.append(
                        {
                            "simulation_time": network.simulation_time_s,
                            "event": "SCHEDULED_FAULT_INJECTED",
                            "detail": fault.fault_type,
                        }
                    )
                if isinstance(self.bus, EmulatedMessageBus):
                    self.bus.configure(self.control.channel_config)
                    if not self.control.broker_online and broker_outage_end_s is None:
                        broker_outage_end_s = (
                            network.simulation_time_s + self.control.broker_outage_duration_s
                        )
                        self.bus.set_broker_offline(
                            network.simulation_time_s,
                            self.control.broker_outage_duration_s,
                        )
                        self.events.append(
                            {
                                "simulation_time": network.simulation_time_s,
                                "event": "MQTT_BROKER_OFFLINE_INJECTED",
                            }
                        )
                    if broker_outage_end_s is not None and (
                        self.control.broker_online
                        or network.simulation_time_s >= broker_outage_end_s
                    ):
                        self.bus.recover_broker(network.simulation_time_s)
                        self.control.broker_online = True
                        broker_outage_end_s = None
                        self.events.append(
                            {
                                "simulation_time": network.simulation_time_s,
                                "event": "MQTT_BROKER_RECOVERED",
                            }
                        )
                    if not self.control.edge_online and edge_outage_end_s is None:
                        edge_outage_end_s = (
                            network.simulation_time_s + self.control.edge_outage_duration_s
                        )
                        self.bus.set_endpoint_offline(
                            "edge",
                            network.simulation_time_s,
                            self.control.edge_outage_duration_s,
                        )
                        self.events.append(
                            {
                                "simulation_time": network.simulation_time_s,
                                "event": "EDGE_OFFLINE_INJECTED",
                            }
                        )
                    if edge_outage_end_s is not None and (
                        self.control.edge_online or network.simulation_time_s >= edge_outage_end_s
                    ):
                        self.bus.recover_endpoint(
                            "edge",
                            network.simulation_time_s,
                        )
                        self.control.edge_online = True
                        edge_outage_end_s = None
                        self.events.append(
                            {
                                "simulation_time": network.simulation_time_s,
                                "event": "EDGE_COMMUNICATION_RECOVERED",
                            }
                        )
                    await self.bus.advance(network.simulation_time_s)
                if self.control.roadwork_active and not roadwork_applied:
                    await run_blocking(adapter.close_lane, roadwork_lane_id)
                    roadwork_applied = True
                    self.events.append(
                        {
                            "simulation_time": network.simulation_time_s,
                            "event": "ROADWORK_LANE_CLOSED",
                            "detail": roadwork_lane_id,
                        }
                    )
                elif not self.control.roadwork_active and roadwork_applied:
                    await run_blocking(adapter.reopen_lane, roadwork_lane_id)
                    roadwork_applied = False
                    self.events.append(
                        {
                            "simulation_time": network.simulation_time_s,
                            "event": "ROADWORK_LANE_REOPENED",
                            "detail": roadwork_lane_id,
                        }
                    )
                if disturbance_runtime is not None:
                    for disturbance in self.control.drain_pending_disturbances():
                        disturbance_runtime.schedule(disturbance)
                    disturbance_events = (
                        await run_blocking(
                            disturbance_runtime.tick,
                            network.simulation_time_s,
                            adapter,
                        )
                        if disturbance_runtime.needs_tick(network.simulation_time_s)
                        else []
                    )
                    self.events.extend(disturbance_events)
                    for event in disturbance_events:
                        if event.get("event") not in {
                            "ROADWORK_LANE_CLOSED",
                            "INCIDENT_STOP_SCHEDULED",
                            "EVENT_DISPERSAL_STARTED",
                        }:
                            continue
                        disturbance_id = event.get("disturbance_id")
                        if isinstance(disturbance_id, str):
                            detail = event.get("detail")
                            self.control.mark_disturbance_applied(
                                disturbance_id,
                                network.simulation_time_s,
                                str(detail) if detail is not None else None,
                            )
                self._apply_scheduled_cloud_outage(network.simulation_time_s)
                record_phase("disturbance", phase_started)
                phase_started = time.perf_counter()
                regional = await run_blocking(
                    aggregator.collect_regional,
                    network=network,
                    control_mode=(
                        distributed_control_mode
                        if isinstance(self.bus, MqttMessageBus)
                        else controller.machine.mode.value
                    ),
                    active_disturbances=(
                        disturbance_runtime.active_event_ids(network.simulation_time_s)
                        if disturbance_runtime is not None
                        else []
                    ),
                )
                record_phase("aggregation", phase_started)
                phase_started = time.perf_counter()
                vehicle_states = aggregator.last_vehicle_states
                for intersection_state in regional.intersection_states:
                    emergency_phase = intersection_state.emergency_priority_phase_id
                    if emergency_phase is None:
                        continue
                    detection = (
                        intersection_state.intersection_id,
                        emergency_phase,
                    )
                    if detection in emergency_priority_detections:
                        continue
                    emergency_priority_detections.add(detection)
                    self.events.append(
                        {
                            "simulation_time": network.simulation_time_s,
                            "event": "EMERGENCY_PRIORITY_DETECTED",
                            "detail": (
                                f"{intersection_state.intersection_id}:phase={emergency_phase}"
                            ),
                        }
                    )
                should_publish_state = (
                    isinstance(self.bus, MqttMessageBus)
                    or network.simulation_time_s >= next_cloud_time
                )
                if (
                    self.control.cloud_online or isinstance(self.bus, MqttMessageBus)
                ) and should_publish_state:
                    cloud_started = time.perf_counter()
                    if isinstance(self.bus, MqttMessageBus):
                        await self.bus.publish(
                            "traffic/development/sumo/sumo-runner-primary/observation",
                            regional.model_dump_json().encode("utf-8"),
                            qos=1,
                        )
                    else:
                        await edge_runtime.publish_state(regional)
                    cloud_latencies_ms.append((time.perf_counter() - cloud_started) * 1000)
                    if not isinstance(self.bus, MqttMessageBus):
                        next_cloud_time += self.config.cloud_interval_s
                    self.events.append(
                        {
                            "simulation_time": network.simulation_time_s,
                            "event": "EDGE_STATE_PUBLISHED",
                        }
                    )
                    if isinstance(self.bus, MqttMessageBus) and not pending_edge_actions:
                        with suppress(TimeoutError):
                            await asyncio.wait_for(
                                remote_action_event.wait(),
                                timeout=0.05,
                            )
                        remote_action_event.clear()
                step_remote_action_count = 0
                step_remote_rejection_count = 0
                step_signal_executed_count = 0
                step_signal_modified_count = 0
                step_signal_rejected_count = 0
                step_policy_selection_counts = {code: 0 for code in ("B0", "B1", "B2", "B3")}
                step_policy_candidate_scores: dict[str, list[float]] = {
                    code: [] for code in ("B0", "B1", "B2", "B3")
                }
                step_expected_gain_ratios: list[float] = []
                step_signal_rejection_reasons: dict[str, int] = {}
                for intersection_state in regional.intersection_states:
                    edge_started = time.perf_counter()
                    if isinstance(self.bus, MqttMessageBus):
                        action = pending_edge_actions.pop(
                            intersection_state.intersection_id,
                            None,
                        )
                        feedback = (
                            await run_blocking(
                                self._apply_remote_edge_action,
                                adapter,
                                edge_factory,
                                action,
                                intersection_state,
                            )
                            if action is not None
                            else None
                        )
                        if feedback is not None:
                            assert action is not None
                            distributed_control_mode = feedback.control_mode
                            remote_action_count += 1
                            step_remote_action_count += 1
                            remote_action_rejection_count += int(
                                feedback.execution_status == ExecutionStatus.REJECTED
                            )
                            step_remote_rejection_count += int(
                                feedback.execution_status == ExecutionStatus.REJECTED
                            )
                            if (
                                action.source_strategy_id is not None
                                and str(action.source_strategy_id) not in seen_strategy_ids
                            ):
                                strategy_id = str(action.source_strategy_id)
                                seen_strategy_ids.add(strategy_id)
                                self.events.append(
                                    {
                                        "simulation_time": (network.simulation_time_s),
                                        "event": "CLOUD_STRATEGY_APPLIED",
                                        "detail": (
                                            f"strategy_id={strategy_id},"
                                            f"intersection="
                                            f"{action.intersection_id}"
                                        ),
                                    }
                                )
                            if feedback.execution_status in {
                                ExecutionStatus.MODIFIED,
                                ExecutionStatus.REJECTED,
                            }:
                                self.events.append(
                                    {
                                        "simulation_time": (network.simulation_time_s),
                                        "event": (
                                            "SAFETY_ACTION_"
                                            f"{feedback.execution_status.value.upper()}"
                                        ),
                                        "detail": (
                                            f"intersection="
                                            f"{action.intersection_id},"
                                            f"reason="
                                            f"{feedback.rejection_reason or 'modified'}"
                                        ),
                                    }
                                )
                            remote_control_latencies_ms.append(feedback.command_latency_ms)
                            cloud_latency = action.expected_effect.get("cloud_decision_latency_ms")
                            edge_latency = action.expected_effect.get("edge_decision_latency_ms")
                            if isinstance(cloud_latency, int | float):
                                remote_cloud_latencies_ms.append(float(cloud_latency))
                            if isinstance(edge_latency, int | float):
                                remote_edge_latencies_ms.append(float(edge_latency))
                    else:
                        feedback = await run_blocking(
                            controller.control,
                            intersection_state,
                        )
                    edge_latencies_ms.append((time.perf_counter() - edge_started) * 1000)
                    if feedback is not None:
                        step_signal_executed_count += int(
                            feedback.execution_status == ExecutionStatus.EXECUTED
                        )
                        step_signal_modified_count += int(
                            feedback.execution_status == ExecutionStatus.MODIFIED
                        )
                        step_signal_rejected_count += int(
                            feedback.execution_status == ExecutionStatus.REJECTED
                        )
                        if edge_runtime.round_trip_latencies_ms:
                            feedback = feedback.model_copy(
                                update={
                                    "cloud_round_trip_latency_ms": (
                                        edge_runtime.round_trip_latencies_ms[-1]
                                    )
                                }
                            )
                        if feedback.execution_status == ExecutionStatus.REJECTED:
                            accumulator.unsafe_rejections += 1
                            for reason in (feedback.rejection_reason or "UNKNOWN").split(","):
                                reason = reason.strip() or "UNKNOWN"
                                step_signal_rejection_reasons[reason] = (
                                    step_signal_rejection_reasons.get(reason, 0) + 1
                                )
                        requested = feedback.requested_action
                        scores = requested.get("scores")
                        numeric_scores = (
                            {
                                str(phase_id): float(score)
                                for phase_id, score in scores.items()
                                if isinstance(score, int | float)
                            }
                            if isinstance(scores, dict)
                            else {}
                        )
                        selected_phase = requested.get("requested_phase_id")
                        latest_control_evidence[feedback.intersection_id] = {
                            "current_phase_id": intersection_state.current_phase_id,
                            "current_phase_elapsed_s": intersection_state.phase_elapsed,
                            "current_phase_remaining_s": intersection_state.phase_remaining,
                            "decision_action": str(
                                feedback.executed_action.get("action_type")
                                or requested.get("action_type")
                                or "hold_phase"
                            ),
                            "requested_phase_id": (
                                str(selected_phase) if selected_phase is not None else None
                            ),
                            "decision_status": feedback.execution_status.value,
                            "decision_reason_codes": [
                                str(code) for code in requested.get("reason_codes", [])
                            ],
                            "decision_explanation": str(requested.get("explanation") or ""),
                            "phase_scores": numeric_scores,
                            "selected_phase_score": numeric_scores.get(str(selected_phase)),
                            "selected_policy": requested.get("selected_policy"),
                            "expected_gain_ratio": requested.get("expected_gain_ratio"),
                            "control_mode": feedback.control_mode,
                        }
                        selected_policy = feedback.requested_action.get("selected_policy")
                        if (
                            isinstance(selected_policy, str)
                            and selected_policy in step_policy_selection_counts
                        ):
                            step_policy_selection_counts[selected_policy] += 1
                        candidate_scores = feedback.requested_action.get("candidate_policy_scores")
                        if isinstance(candidate_scores, dict):
                            for policy, value in candidate_scores.items():
                                if policy in step_policy_candidate_scores and isinstance(
                                    value, int | float
                                ):
                                    step_policy_candidate_scores[policy].append(float(value))
                        expected_gain = feedback.requested_action.get("expected_gain_ratio")
                        if isinstance(expected_gain, int | float):
                            step_expected_gain_ratios.append(float(expected_gain))
                        if self.config.publish_feedback_to_bus:
                            await edge_runtime.publish_feedback(feedback)
                if isinstance(self.bus, MqttMessageBus) and step_remote_action_count:
                    self.events.append(
                        {
                            "simulation_time": network.simulation_time_s,
                            "event": "EDGE_ACTION_BATCH_EXECUTED",
                            "detail": (
                                f"actions={step_remote_action_count},"
                                f"rejected={step_remote_rejection_count},"
                                f"mode={distributed_control_mode}"
                            ),
                        }
                    )
                speed_factors = [
                    strategy.speed_guidance_parameters.get("target_speed_factor", 1.0)
                    for strategy in controller.last_strategy_by_intersection.values()
                ]
                target_speed_factor_mean = (
                    statistics.fmean(speed_factors) if speed_factors else None
                )
                guidance_request_count = 0
                if isinstance(self.bus, MqttMessageBus):
                    guidance_count = await run_blocking(
                        self._apply_vehicle_commands,
                        adapter,
                        pending_vehicle_commands,
                    )
                    guidance_request_count = await self._publish_vehicle_messages(
                        self.bus,
                        vehicle_factory,
                        edge_factory,
                        vehicle_states,
                        controller,
                        simulation_time_s=network.simulation_time_s,
                    )
                    guidance_rejections = 0
                    guidance_modifications = 0
                else:
                    (
                        guidance_count,
                        guidance_rejections,
                        guidance_modifications,
                    ) = await run_blocking(
                        self._apply_guidance,
                        adapter,
                        controller,
                        guidance_agent,
                        vehicle_states,
                        simulation_time_s=network.simulation_time_s,
                    )
                accumulator.unsafe_rejections += guidance_rejections
                if guidance_rejections or guidance_modifications:
                    self.events.append(
                        {
                            "simulation_time": network.simulation_time_s,
                            "event": "VEHICLE_GUIDANCE_SAFETY_VALIDATED",
                            "detail": (
                                f"rejected={guidance_rejections},modified={guidance_modifications}"
                            ),
                        }
                    )
                record_phase("control", phase_started)
                phase_started = time.perf_counter()
                pedestrian_states = aggregator.last_pedestrian_states
                arrived_vehicle_ids = await run_blocking(adapter.get_arrived_vehicle_ids)
                completed_bicycle_total += sum(
                    vehicle_class_history.get(identifier) == "bicycle"
                    for identifier in arrived_vehicle_ids
                )
                completed_total += sum(
                    vehicle_class_history.get(identifier) != "bicycle"
                    for identifier in arrived_vehicle_ids
                )
                arrived_pedestrian_ids = await run_blocking(adapter.get_arrived_pedestrian_ids)
                completed_pedestrian_total += len(arrived_pedestrian_ids)
                vehicle_class_history.update(
                    {vehicle.vehicle_id: vehicle.vehicle_class for vehicle in vehicle_states}
                )
                current_crossings = {
                    pedestrian.pedestrian_id
                    for pedestrian in pedestrian_states
                    if pedestrian.crossing_id is not None
                }
                completed_crossings += len(current_crossings - crossing_pedestrians)
                crossing_pedestrians = current_crossings
                motor_vehicle_states = [
                    vehicle for vehicle in vehicle_states if vehicle.vehicle_class != "bicycle"
                ]
                bicycle_states = [
                    vehicle for vehicle in vehicle_states if vehicle.vehicle_class == "bicycle"
                ]
                if network.simulation_time_s + 1e-9 >= next_safety_sample_time:
                    conflicts = safety_monitor.observe(
                        network.simulation_time_s,
                        vehicle_states,
                        pedestrian_states,
                    )
                    next_safety_sample_time = (
                        network.simulation_time_s + self.config.surrogate_safety_interval_s
                    )
                else:
                    conflicts = []
                total_queue_m = sum(
                    lane.queue_length_m
                    for state in regional.intersection_states
                    for lane in state.lane_states
                )
                waiting = (
                    sum(vehicle.waiting_time_s for vehicle in motor_vehicle_states)
                    / len(motor_vehicle_states)
                    if motor_vehicle_states
                    else 0.0
                )
                stop_count = sum(1 for vehicle in motor_vehicle_states if vehicle.speed_m_s < 0.1)
                accelerations = [vehicle.acceleration_m_s2 for vehicle in motor_vehicle_states]
                ttc_values = [
                    conflict.ttc_s for conflict in conflicts if conflict.ttc_s is not None
                ]
                pet_values = [
                    conflict.pet_s for conflict in conflicts if conflict.pet_s is not None
                ]
                sample = MetricSample(
                    simulation_time_s=network.simulation_time_s,
                    mean_speed_m_s=network.mean_speed_m_s,
                    total_queue_vehicles=network.total_queue_vehicles,
                    total_queue_m=total_queue_m,
                    throughput_vehicles=completed_total,
                    completed_trips=completed_total,
                    waiting_time_s=waiting,
                    time_loss_s=0.0,
                    stop_count=stop_count,
                    spillback_intersections=len(regional.spillback_edges),
                    congested_intersections=len(regional.congested_intersections),
                    active_vehicle_count=len(motor_vehicle_states),
                    fuel_mg=sum(vehicle.fuel_mg_s for vehicle in motor_vehicle_states),
                    co2_mg=sum(vehicle.co2_mg_s for vehicle in motor_vehicle_states),
                    nox_mg=sum(vehicle.nox_mg_s for vehicle in motor_vehicle_states),
                    emergency_braking_count=sum(
                        acceleration < -4.5 for acceleration in accelerations
                    ),
                    acceleration_variance=(
                        statistics.pvariance(accelerations) if len(accelerations) > 1 else 0.0
                    ),
                    bicycle_active_count=len(bicycle_states),
                    bicycle_completed_trips=completed_bicycle_total,
                    bicycle_waiting_time_s=(
                        sum(vehicle.waiting_time_s for vehicle in bicycle_states)
                        / len(bicycle_states)
                        if bicycle_states
                        else 0.0
                    ),
                    bicycle_queue_count=sum(
                        state.bicycle_queue_count for state in regional.intersection_states
                    ),
                    pedestrian_active_count=len(pedestrian_states),
                    pedestrian_completed_trips=completed_pedestrian_total,
                    pedestrian_waiting_time_s=(
                        sum(pedestrian.waiting_time_s for pedestrian in pedestrian_states)
                        / len(pedestrian_states)
                        if pedestrian_states
                        else 0.0
                    ),
                    pedestrian_crossing_count=completed_crossings,
                    motor_motor_conflict_count=sum(
                        conflict.conflict_type == "motor_motor" for conflict in conflicts
                    ),
                    motor_bicycle_conflict_count=sum(
                        conflict.conflict_type == "motor_bicycle" for conflict in conflicts
                    ),
                    motor_pedestrian_conflict_count=sum(
                        conflict.conflict_type == "motor_pedestrian" for conflict in conflicts
                    ),
                    bicycle_pedestrian_conflict_count=sum(
                        conflict.conflict_type == "bicycle_pedestrian" for conflict in conflicts
                    ),
                    minimum_ttc_s=min(ttc_values) if ttc_values else None,
                    minimum_pet_s=min(pet_values) if pet_values else None,
                )
                accumulator.add(sample)
                sample_dict: dict[str, object] = {
                    **asdict(sample),
                    "completed_vehicles": completed_total + completed_bicycle_total,
                    "vehicle_trajectory_probes": (
                        [
                            {
                                "vehicle_id": vehicle.vehicle_id,
                                "road_id": vehicle.road_id,
                                "lane_id": vehicle.lane_id,
                                "lane_position_m": vehicle.lane_position_m,
                                "x_m": vehicle.x_m,
                                "y_m": vehicle.y_m,
                                "speed_m_s": vehicle.speed_m_s,
                                "waiting_time_s": vehicle.waiting_time_s,
                            }
                            for vehicle in sorted(
                                motor_vehicle_states,
                                key=lambda item: item.vehicle_id,
                            )[:16]
                        ]
                        if round(network.simulation_time_s) % 5 == 0
                        else []
                    ),
                    "guidance_count": guidance_count,
                    "guidance_request_count": guidance_request_count,
                    "guidance_rejection_count": guidance_rejections,
                    "guidance_modification_count": guidance_modifications,
                    "glosa_effectiveness_gate_active": getattr(
                        getattr(controller, "glosa_effectiveness_gate", None),
                        "active",
                        None,
                    ),
                    "glosa_effectiveness_gate_reason": getattr(
                        getattr(controller, "glosa_effectiveness_gate", None),
                        "reason",
                        "not_applicable",
                    ),
                    "glosa_speed_change_ratio": getattr(
                        getattr(controller, "glosa_effectiveness_gate", None),
                        "speed_change_ratio",
                        None,
                    ),
                    "glosa_queue_reduction_ratio": getattr(
                        getattr(controller, "glosa_effectiveness_gate", None),
                        "queue_reduction_ratio",
                        None,
                    ),
                    "glosa_minimum_target_speed_m_s": getattr(
                        controller,
                        "last_glosa_minimum_speed_m_s",
                        None,
                    ),
                    "glosa_mobility_regime": getattr(
                        getattr(controller, "glosa_mobility_classifier", None),
                        "regime",
                        "not_applicable",
                    ),
                    "glosa_mobility_baseline_speed_m_s": getattr(
                        getattr(controller, "glosa_mobility_classifier", None),
                        "baseline_mean_speed_m_s",
                        None,
                    ),
                    "glosa_intervention_enabled": getattr(
                        controller,
                        "last_glosa_intervention_enabled",
                        None,
                    ),
                    "target_speed_factor_mean": target_speed_factor_mean,
                    "signal_action_executed_count": step_signal_executed_count,
                    "signal_action_modified_count": step_signal_modified_count,
                    "signal_action_rejected_count": step_signal_rejected_count,
                    "signal_action_rejection_reasons": step_signal_rejection_reasons,
                    "control_evidence_by_intersection": {
                        intersection_id: dict(evidence)
                        for intersection_id, evidence in latest_control_evidence.items()
                    },
                    "selected_policy_counts": step_policy_selection_counts,
                    "candidate_policy_score_mean": {
                        policy: statistics.fmean(values)
                        for policy, values in step_policy_candidate_scores.items()
                        if values
                    },
                    "b3_expected_gain_ratio": (
                        statistics.fmean(step_expected_gain_ratios)
                        if step_expected_gain_ratios
                        else None
                    ),
                    **intersection_sample_fields(regional),
                    **prediction_sample_fields(controller.last_strategy_by_intersection),
                    "cpu_percent": process.cpu_percent(),
                    "memory_mb": process.memory_info().rss / 1024 / 1024,
                    "fallback_mode": (
                        distributed_control_mode
                        if isinstance(self.bus, MqttMessageBus)
                        else controller.machine.mode.value
                    ),
                    "cloud_online": self.control.cloud_online,
                    "mqtt_online": self.control.broker_online,
                }
                samples.append(sample_dict)
                if self.config.publish_runtime_telemetry_to_bus:
                    metric_snapshot = experiment_factory.build(
                        MetricSnapshot,
                        simulation_time=network.simulation_time_s,
                        ttl_s=10.0,
                        metrics={
                            key: value
                            for key, value in sample_dict.items()
                            if isinstance(value, float | int | str | bool)
                        },
                    )
                    await self.bus.publish(
                        (f"traffic/development/experiment/{self.config.experiment_id}/metric"),
                        metric_snapshot.model_dump_json().encode("utf-8"),
                        qos=0,
                    )
                    for event in self.events[published_event_index:]:
                        event_message = experiment_factory.build(
                            ExperimentEvent,
                            simulation_time=float(event["simulation_time"]),
                            ttl_s=3600.0,
                            event_type=str(event["event"]),
                            payload=dict(event),
                        )
                        await self.bus.publish(
                            (f"traffic/development/experiment/{self.config.experiment_id}/event"),
                            event_message.model_dump_json().encode("utf-8"),
                            qos=1,
                        )
                published_event_index = len(self.events)
                if self.persistence_callback is not None:
                    await self.persistence_callback(
                        "metric",
                        {
                            "experiment_id": self.config.experiment_id,
                            "simulation_time_s": network.simulation_time_s,
                            "values": sample_dict,
                        },
                    )
                    if network.simulation_time_s >= next_trajectory_time_s:
                        await self.persistence_callback(
                            "trajectory",
                            {
                                "experiment_id": self.config.experiment_id,
                                "simulation_time_s": network.simulation_time_s,
                                "samples": [
                                    {
                                        "participant_kind": "bicycle"
                                        if vehicle.vehicle_class == "bicycle"
                                        else "motor_vehicle",
                                        "vehicle_id": vehicle.vehicle_id,
                                        "vehicle_type": vehicle.vehicle_type,
                                        "road_id": vehicle.road_id,
                                        "lane_id": vehicle.lane_id,
                                        "lane_position_m": vehicle.lane_position_m,
                                        "x_m": vehicle.x_m,
                                        "y_m": vehicle.y_m,
                                        "speed_m_s": vehicle.speed_m_s,
                                        "acceleration_m_s2": (vehicle.acceleration_m_s2),
                                        "route_id": vehicle.route_id,
                                        "waiting_time_s": vehicle.waiting_time_s,
                                    }
                                    for vehicle in vehicle_states
                                ]
                                + [
                                    {
                                        "participant_kind": "pedestrian",
                                        "pedestrian_id": pedestrian.pedestrian_id,
                                        "person_type": pedestrian.pedestrian_type,
                                        "road_id": pedestrian.road_id,
                                        "lane_id": pedestrian.lane_id,
                                        "x_m": pedestrian.x_m,
                                        "y_m": pedestrian.y_m,
                                        "speed_m_s": pedestrian.speed_m_s,
                                        "waiting_time_s": pedestrian.waiting_time_s,
                                        "crossing_id": pedestrian.crossing_id or "",
                                        "walking_stage_index": (pedestrian.walking_stage_index),
                                        "waiting_area_id": (pedestrian.waiting_area_id or ""),
                                    }
                                    for pedestrian in pedestrian_states
                                ],
                            },
                        )
                        next_trajectory_time_s = network.simulation_time_s + trajectory_interval_s
                effective_digital_twin_interval_s: float | None = None
                if self.digital_twin_schedule_callback is not None:
                    effective_digital_twin_interval_s = self.digital_twin_schedule_callback(
                        network.simulation_time_s,
                        digital_twin_interval_s,
                    )
                elif network.simulation_time_s >= next_digital_twin_time_s:
                    effective_digital_twin_interval_s = current_digital_twin_interval_s()
                if (
                    self.digital_twin_callback is not None
                    and effective_digital_twin_interval_s is not None
                ):
                    self.digital_twin_callback(
                        DigitalTwinSourceFrame(
                            experiment_id=self.config.experiment_id,
                            scenario_id=self.config.scenario_id,
                            simulation_time_s=network.simulation_time_s,
                            tick_hz=1.0 / effective_digital_twin_interval_s,
                            vehicles=vehicle_states,
                            pedestrians=pedestrian_states,
                            traffic_lights=[
                                aggregator.last_intersection_snapshots[item]
                                for item in sorted(aggregator.last_intersection_snapshots)
                            ],
                            events=self.events[digital_twin_event_index:],
                            conflicts=[
                                {
                                    "conflict_id": (
                                        f"{self.config.experiment_id}:"
                                        f"{network.simulation_time_s:.3f}:{index}:"
                                        f"{conflict.participant_a_id}:"
                                        f"{conflict.participant_b_id}:"
                                        f"{conflict.conflict_type}"
                                    ),
                                    "participant_a_id": conflict.participant_a_id,
                                    "participant_b_id": conflict.participant_b_id,
                                    "conflict_type": conflict.conflict_type,
                                    "x_m": conflict.x_m,
                                    "y_m": conflict.y_m,
                                    "minimum_distance_m": conflict.minimum_distance_m,
                                    "relative_speed_m_s": conflict.relative_speed_m_s,
                                    "ttc_s": conflict.ttc_s,
                                    "pet_s": conflict.pet_s,
                                    "severity": conflict.severity,
                                }
                                for index, conflict in enumerate(conflicts)
                            ],
                            metrics={
                                **sample_dict,
                                "algorithm": self.config.algorithm,
                                "scenario_profile": self.config.scenario_profile_code,
                                "max_queue_vehicles": max(
                                    (state.total_queue for state in regional.intersection_states),
                                    default=0,
                                ),
                            },
                            intersection_metrics=[
                                {
                                    "intersection_id": state.intersection_id,
                                    **latest_control_evidence.get(state.intersection_id, {}),
                                    "phase_id": state.current_phase_id,
                                    "phase_state": state.phase_state,
                                    "queue_vehicles": state.total_queue,
                                    "mean_speed_m_s": state.mean_speed,
                                    "congestion_level": state.congestion_level,
                                    "spillback_risk": state.spillback_risk,
                                    "control_mode": state.local_control_mode,
                                    "incident_state": state.incident_state,
                                    "bicycle_count": sum(
                                        lane.bicycle_count + lane.electric_bicycle_count
                                        for lane in state.lane_states
                                    ),
                                    "bicycle_queue_count": state.bicycle_queue_count,
                                    "pedestrian_count": sum(
                                        lane.pedestrian_count for lane in state.lane_states
                                    ),
                                    "pedestrian_waiting_count": (state.pedestrian_waiting_count),
                                    "pedestrian_crossing_count": (state.crossing_pedestrian_count),
                                    "emergency_priority_phase_id": (
                                        state.emergency_priority_phase_id
                                    ),
                                    "approaches": [
                                        {
                                            "lane_id": lane.lane_id,
                                            "direction": lane.direction,
                                            "movement": lane.movement,
                                            "vehicle_count": lane.vehicle_count,
                                            "queue_vehicles": lane.queue_vehicle_count,
                                            "mean_speed_m_s": lane.mean_speed,
                                            "occupancy": lane.occupancy,
                                            "downstream_occupancy": lane.downstream_occupancy,
                                        }
                                        for lane in state.lane_states
                                    ],
                                }
                                for state in regional.intersection_states
                            ],
                        )
                    )
                    digital_twin_event_index = len(self.events)
                    if self.digital_twin_schedule_callback is None:
                        next_digital_twin_time_s = (
                            network.simulation_time_s + effective_digital_twin_interval_s
                        )
                if self.snapshot_callback is not None:
                    snapshot: dict[str, object] = {
                        "experiment_id": self.config.experiment_id,
                        "scenario_id": self.config.scenario_id,
                        "scenario_profile": self.config.scenario_profile_code,
                        "algorithm": self.config.algorithm,
                        "seed": self.config.seed,
                        "duration_s": self.config.duration_s,
                        "evaluation_start_simulation_time_s": (evaluation_start_simulation_time_s),
                        "simulation_time_s": network.simulation_time_s,
                        "simulation_rate": self.control.simulation_rate,
                        "performance": performance_snapshot(),
                    }
                    if self.snapshot_detail == "full":
                        current_max_queue = max(
                            (state.total_queue for state in regional.intersection_states),
                            default=0,
                        )
                        downstream_occupancies = [
                            lane.downstream_occupancy
                            for state in regional.intersection_states
                            for lane in state.lane_states
                        ]
                        snapshot.update(
                            {
                                "intersections": [
                                    {
                                        "intersection_id": state.intersection_id,
                                        **latest_control_evidence.get(state.intersection_id, {}),
                                        "phase_id": state.current_phase_id,
                                        "phase_state": state.phase_state,
                                        "queue_vehicles": state.total_queue,
                                        "mean_speed_m_s": state.mean_speed,
                                        "congestion_level": state.congestion_level,
                                        "spillback_risk": state.spillback_risk,
                                        "control_mode": state.local_control_mode,
                                        "incident_state": state.incident_state,
                                        "bicycle_count": sum(
                                            lane.bicycle_count + lane.electric_bicycle_count
                                            for lane in state.lane_states
                                        ),
                                        "bicycle_queue_count": state.bicycle_queue_count,
                                        "pedestrian_count": sum(
                                            lane.pedestrian_count for lane in state.lane_states
                                        ),
                                        "pedestrian_waiting_count": (
                                            state.pedestrian_waiting_count
                                        ),
                                        "pedestrian_crossing_count": (
                                            state.crossing_pedestrian_count
                                        ),
                                        "emergency_priority_phase_id": (
                                            state.emergency_priority_phase_id
                                        ),
                                        "lane_states": [
                                            {
                                                "lane_id": lane.lane_id,
                                                "direction": lane.direction,
                                                "movement": lane.movement,
                                                "vehicle_count": lane.vehicle_count,
                                                "queue_vehicle_count": (lane.queue_vehicle_count),
                                                "bicycle_count": lane.bicycle_count,
                                                "e_bike_count": (lane.electric_bicycle_count),
                                                "bicycle_queue_count": (lane.bicycle_queue_count),
                                                "pedestrian_count": lane.pedestrian_count,
                                                "pedestrian_waiting_count": (
                                                    lane.pedestrian_waiting_count
                                                ),
                                                "queue_length_m": (lane.queue_length_m),
                                                "mean_speed_m_s": lane.mean_speed,
                                                "occupancy": lane.occupancy,
                                                "downstream_occupancy": (lane.downstream_occupancy),
                                                "downstream_available_capacity": (
                                                    lane.downstream_available_capacity
                                                ),
                                            }
                                            for lane in state.lane_states
                                        ],
                                    }
                                    for state in regional.intersection_states
                                ],
                                "max_queue_vehicles": current_max_queue,
                                "downstream_occupancy": (
                                    statistics.fmean(downstream_occupancies)
                                    if downstream_occupancies
                                    else 0.0
                                ),
                                "cloud_decision_latency_ms": (
                                    remote_cloud_latencies_ms[-1]
                                    if remote_cloud_latencies_ms
                                    else (cloud_latencies_ms[-1] if cloud_latencies_ms else None)
                                ),
                                "edge_decision_latency_ms": (
                                    remote_edge_latencies_ms[-1]
                                    if remote_edge_latencies_ms
                                    else (edge_latencies_ms[-1] if edge_latencies_ms else None)
                                ),
                                "end_to_end_control_latency_ms": (
                                    remote_control_latencies_ms[-1]
                                    if remote_control_latencies_ms
                                    else None
                                ),
                                "mqtt_online": self.control.broker_online,
                                "active_disturbances": (regional.active_disturbances),
                                "spillback_edges": regional.spillback_edges,
                                "congested_intersection_ids": (regional.congested_intersections),
                                "recent_events": self.events[-60:],
                                **sample_dict,
                            }
                        )
                    self.snapshot_callback(snapshot)
                record_phase("telemetry", phase_started)
                phase_started = time.perf_counter()
                if self.step_barrier_callback is not None:
                    await self.step_barrier_callback(network.simulation_time_s)
                record_phase("barrier", phase_started)
                phase_history_ms["total"].append((time.perf_counter() - step_wall_started) * 1000.0)
                simulation_rate = self.control.simulation_rate
                if simulation_rate is None or last_paced_simulation_time is None:
                    await asyncio.sleep(0)
                else:
                    simulated_delta = max(
                        0.0,
                        network.simulation_time_s - last_paced_simulation_time,
                    )
                    wall_budget = simulated_delta / simulation_rate
                    await asyncio.sleep(
                        max(0.0, wall_budget - (time.perf_counter() - step_wall_started))
                    )
                last_paced_simulation_time = network.simulation_time_s
        finally:
            try:
                await run_blocking(adapter.stop_simulation)
                if controller is not None:
                    await run_blocking(controller.close)
            finally:
                executor.shutdown(wait=True, cancel_futures=True)
                await self.bus.disconnect()
        wall_duration = time.perf_counter() - started_wall
        metrics: dict[str, object] = {**accumulator.summary()}
        metrics["runner_performance"] = performance_snapshot()
        metrics.update(self._signal_control_metrics(samples))
        if controller is not None:
            metrics["algorithm_timeout_count"] = controller.algorithm_timeout_count
            metrics["algorithm_failure_count"] = controller.algorithm_failure_count
            metrics["algorithm_decision_latency_target_miss_count"] = (
                controller.algorithm_decision_latency_target_miss_count
            )
            metrics["algorithm_decision_latency_target_ms"] = (
                controller.algorithm_config.decision_latency_target_ms
            )
            metrics["algorithm_decision_elapsed_ms_max"] = (
                controller.algorithm_decision_elapsed_ms_max
            )
            metrics["algorithm_timeout_elapsed_ms_max"] = (
                controller.algorithm_timeout_elapsed_ms_max
            )
            metrics["algorithm_timeout_limit_ms"] = controller.algorithm_config.decision_timeout_ms
        metrics.update(self._trip_metrics(self.config.result_dir / "tripinfo.xml"))
        cloud_latency_source = (
            remote_cloud_latencies_ms
            if isinstance(self.bus, MqttMessageBus)
            else cloud_latencies_ms
        )
        edge_latency_source = (
            remote_edge_latencies_ms if isinstance(self.bus, MqttMessageBus) else edge_latencies_ms
        )
        cloud_latency_mean = statistics.fmean(cloud_latency_source) if cloud_latency_source else 0.0
        edge_latency_mean = statistics.fmean(edge_latency_source) if edge_latency_source else 0.0
        metrics["cloud_decision_latency_ms"] = cloud_latency_mean
        metrics["edge_decision_latency_ms"] = edge_latency_mean
        metrics["end_to_end_control_latency_ms"] = (
            statistics.fmean(remote_control_latencies_ms)
            if remote_control_latencies_ms
            else cloud_latency_mean + edge_latency_mean
        )
        metrics["remote_edge_action_count"] = remote_action_count
        metrics["remote_edge_action_rejection_count"] = remote_action_rejection_count
        cpu_values: list[float] = []
        memory_values: list[float] = []
        for realtime_sample in samples:
            cpu_value = realtime_sample.get("cpu_percent")
            memory_value = realtime_sample.get("memory_mb")
            if isinstance(cpu_value, int | float):
                cpu_values.append(float(cpu_value))
            if isinstance(memory_value, int | float):
                memory_values.append(float(memory_value))
        metrics["cpu_percent_mean"] = statistics.fmean(cpu_values) if cpu_values else 0.0
        metrics["memory_mb_peak"] = max(memory_values, default=0.0)
        metrics.update(self._fallback_metrics(samples))
        metrics.update(self._prediction_metrics(samples))
        metrics["data_write_latency_ms"] = (
            "pending_flush"
            if self.persistence_callback is not None
            else "not_applicable_no_persistence_sink"
        )
        remote_delivery_latencies_ms = [
            event.actual_latency_ms for event in remote_communication_events if not event.dropped
        ]
        if isinstance(self.bus, EmulatedMessageBus):
            records = self.bus.records
            metrics["mqtt_round_trip_latency_ms"] = (
                statistics.fmean(record.actual_latency_ms for record in records) if records else 0.0
            )
            metrics["communication_drop_count"] = sum(record.dropped for record in records)
        elif remote_communication_events:
            metrics["mqtt_round_trip_latency_ms"] = (
                statistics.fmean(remote_delivery_latencies_ms)
                if remote_delivery_latencies_ms
                else 0.0
            )
            metrics["communication_drop_count"] = sum(
                event.dropped for event in remote_communication_events
            )
        elif edge_runtime is not None and edge_runtime.round_trip_latencies_ms:
            metrics["mqtt_round_trip_latency_ms"] = statistics.fmean(
                edge_runtime.round_trip_latencies_ms
            )
            metrics["communication_drop_count"] = 0
        else:
            metrics["mqtt_round_trip_latency_ms"] = "not_available_no_correlated_strategy"
            metrics["communication_drop_count"] = "not_observable_from_mqtt"
        metrics["simulation_realtime_factor"] = (
            self.config.duration_s / wall_duration if wall_duration > 0 else 0.0
        )
        metrics["emergency_priority_detection_count"] = len(emergency_priority_detections)
        route_file = (
            "routes.rou.xml"
            if self.config.scenario_profile_code == "BASE"
            else f"routes.{self.config.scenario_profile_code}.rou.xml"
        )
        scenario_files = [
            self.config.config_file,
            self.config.selection_file,
            self.config.config_file.parent / "rongdong.multimodal.net.xml",
            self.config.config_file.parent / route_file,
            self.config.config_file.parent / "multimodal.rou.xml",
            self.config.config_file.parent / "vtypes.add.xml",
            self.config.config_file.parent / "functional_zones.add.xml",
        ]
        if self.config.scenario_definition_file is not None:
            scenario_files.append(self.config.scenario_definition_file)
        if (
            self.config.scenario_profile_code != "BASE"
            and self.config.scenario_profile_file is not None
        ):
            scenario_files.append(self.config.scenario_profile_file)
        manifest = build_manifest(
            self.config.scenario_id,
            [path.resolve() for path in scenario_files],
            workspace=Path.cwd(),
            provenance={
                "algorithm": self.config.algorithm,
                "algorithm_version": (
                    controller.algorithm_version(self.config.algorithm)
                    if controller is not None
                    else "not_available"
                ),
                "scenario_profile": self.config.scenario_profile_code,
                "seed": self.config.seed,
                "duration_s": self.config.duration_s,
                **runner_manifest_fields(self.config),
                "python": platform.python_version(),
                "sumo_home": str(self.sumo_home),
            },
        )
        self.events.extend(
            {
                "simulation_time": transition.simulation_time,
                "event": "EDGE_MODE_TRANSITION",
                "detail": (
                    f"{transition.previous.value}->{transition.current.value}:{transition.reason}"
                ),
            }
            for transition in (controller.machine.transitions if controller is not None else [])
        )
        communication_events = (
            (
                [
                    experiment_factory.build(
                        CommunicationEvent,
                        simulation_time=record.sent_at_s,
                        ttl_s=3600.0,
                        channel=record.channel,
                        source=record.source,
                        destination=record.destination,
                        message_type=record.message_type,
                        configured_latency_ms=record.configured_latency_ms,
                        actual_latency_ms=record.actual_latency_ms,
                        dropped=record.dropped,
                        duplicated=record.duplicated,
                        reordered=record.reordered,
                        corrupted=record.corrupted,
                        timeout=record.timeout,
                        recovery_time=record.recovery_time_s,
                    ).model_dump(mode="json")
                    for record in self.bus.records
                ]
                if isinstance(self.bus, EmulatedMessageBus)
                else [event.model_dump(mode="json") for event in remote_communication_events]
            )
            if self.config.include_communication_events
            else []
        )
        result: dict[str, object] = {
            "schema_version": "1.0",
            "experiment_id": self.config.experiment_id,
            "scenario_id": self.config.scenario_id,
            "scenario_profile": self.config.scenario_profile_code,
            "algorithm": self.config.algorithm,
            "algorithm_version": next(
                (
                    item["version"]
                    for item in controller.algorithm_registry.discover()
                    if item["name"] == self.config.algorithm
                ),
                "unknown",
            ),
            "seed": self.config.seed,
            "evaluation_start_simulation_time_s": evaluation_start_simulation_time_s,
            "actual_run": True,
            "message_transport": type(self.bus).__name__,
            "runner_options": runner_options(self.config),
            "metrics": metrics,
            "samples": samples,
            "events": self.events,
            "manifest": manifest,
            "communication_events": communication_events,
        }
        if self.persistence_callback is not None:
            for event in self.events:
                await self.persistence_callback(
                    "event",
                    {
                        "experiment_id": self.config.experiment_id,
                        "event_type": str(event["event"]),
                        "simulation_time_s": float(event["simulation_time"]),
                        "payload": event,
                    },
                )
        artifacts = generate_report(result, self.config.result_dir)
        result["artifacts"] = artifacts
        return result

    @staticmethod
    def _signal_control_metrics(
        samples: list[dict[str, object]],
    ) -> dict[str, float | int | str]:
        executed = sum(
            int(value)
            for sample in samples
            if isinstance((value := sample.get("signal_action_executed_count")), int | float)
        )
        modified = sum(
            int(value)
            for sample in samples
            if isinstance((value := sample.get("signal_action_modified_count")), int | float)
        )
        rejected = sum(
            int(value)
            for sample in samples
            if isinstance((value := sample.get("signal_action_rejected_count")), int | float)
        )
        policy_counts = {code: 0 for code in ("B0", "B1", "B2", "B3")}
        expected_gains: list[float] = []
        target_speed_factors: list[float] = []
        for sample in samples:
            selected = sample.get("selected_policy_counts")
            if isinstance(selected, dict):
                for policy, value in selected.items():
                    if policy in policy_counts and isinstance(value, int | float):
                        policy_counts[policy] += int(value)
            expected_gain = sample.get("b3_expected_gain_ratio")
            if isinstance(expected_gain, int | float):
                expected_gains.append(float(expected_gain))
            target_speed_factor = sample.get("target_speed_factor_mean")
            if isinstance(target_speed_factor, int | float):
                target_speed_factors.append(float(target_speed_factor))
        decided = executed + modified + rejected
        selected_total = sum(policy_counts.values())
        return {
            "signal_action_executed_count": executed,
            "signal_action_modified_count": modified,
            "signal_action_rejected_count": rejected,
            "signal_action_acceptance_rate": ((executed + modified) / decided if decided else 1.0),
            **{
                f"policy_{code.lower()}_selection_count": count
                for code, count in policy_counts.items()
            },
            "b3_policy_selection_rate": (
                policy_counts["B3"] / selected_total if selected_total else 0.0
            ),
            "b3_expected_gain_ratio_mean": (
                statistics.fmean(expected_gains) if expected_gains else "not_applicable"
            ),
            "target_speed_factor_mean": (
                statistics.fmean(target_speed_factors) if target_speed_factors else "not_applicable"
            ),
            "target_speed_factor_min": (
                min(target_speed_factors) if target_speed_factors else "not_applicable"
            ),
        }

    def _fallback_metrics(
        self,
        samples: list[dict[str, object]],
    ) -> dict[str, float | str]:
        if self.config.algorithm != "coordinated-max-pressure":
            return {
                "fallback_activation_time_s": "not_applicable",
                "fallback_duration_s": 0.0,
                "recovery_time_s": "not_applicable",
            }
        fallback_indices = [
            index
            for index, sample in enumerate(samples)
            if sample.get("fallback_mode") != "CLOUD_COORDINATED"
        ]
        if not fallback_indices:
            return {
                "fallback_activation_time_s": "not_triggered",
                "fallback_duration_s": 0.0,
                "recovery_time_s": "not_triggered",
            }
        first_index = fallback_indices[0]
        first_time = float(cast(float | int | str, samples[first_index]["simulation_time_s"]))
        duration = 0.0
        for index in fallback_indices:
            current = float(cast(float | int | str, samples[index]["simulation_time_s"]))
            if index + 1 < len(samples):
                duration += max(
                    0.0,
                    float(
                        cast(
                            float | int | str,
                            samples[index + 1]["simulation_time_s"],
                        )
                    )
                    - current,
                )
        recovered = next(
            (
                sample
                for sample in samples[first_index + 1 :]
                if sample.get("fallback_mode") == "CLOUD_COORDINATED"
            ),
            None,
        )
        return {
            "fallback_activation_time_s": first_time,
            "fallback_duration_s": duration,
            "recovery_time_s": (
                float(
                    cast(
                        float | int | str,
                        recovered["simulation_time_s"],
                    )
                )
                - first_time
                if recovered is not None
                else "not_recovered_within_run"
            ),
        }

    def _prediction_metrics(
        self,
        samples: list[dict[str, object]],
    ) -> dict[str, float | str]:
        if self.config.algorithm != "coordinated-max-pressure":
            return {
                "prediction_status": "not_applicable",
                "prediction_model_id": "not_applicable",
                "prediction_horizon_s": "not_applicable",
                "prediction_ready_ratio": "not_applicable",
                "prediction_confidence_mean": "not_applicable",
                "prediction_queue_mae_vehicles": "not_applicable",
            }
        ready = [sample for sample in samples if sample.get("prediction_status") == "ready"]
        confidences = [
            float(value)
            for sample in samples
            if isinstance((value := sample.get("prediction_confidence")), int | float)
        ]
        by_time = {
            float(cast(float | int | str, sample["simulation_time_s"])): sample
            for sample in samples
        }
        absolute_errors: list[float] = []
        for sample in ready:
            predicted = sample.get("predicted_queue_vehicles")
            horizon = sample.get("prediction_horizon_s")
            if not isinstance(predicted, int | float) or not isinstance(horizon, int | float):
                continue
            simulation_time = float(cast(float | int | str, sample["simulation_time_s"]))
            target = by_time.get(simulation_time + float(horizon))
            if target is None:
                continue
            actual_by_intersection = target.get("intersection_queue_vehicles")
            if not isinstance(actual_by_intersection, dict):
                continue
            actual = sum(
                float(value)
                for value in actual_by_intersection.values()
                if isinstance(value, int | float)
            )
            absolute_errors.append(abs(float(predicted) - actual))
        latest_prediction = next(
            (
                sample
                for sample in reversed(samples)
                if sample.get("prediction_model_id") not in {None, "not_available"}
            ),
            {},
        )
        return {
            "prediction_status": str(latest_prediction.get("prediction_status", "not_available")),
            "prediction_model_id": str(
                latest_prediction.get("prediction_model_id", "not_available")
            ),
            "prediction_horizon_s": (
                float(horizon)
                if isinstance(
                    (horizon := latest_prediction.get("prediction_horizon_s")),
                    int | float,
                )
                else "not_available"
            ),
            "prediction_ready_ratio": len(ready) / len(samples) if samples else 0.0,
            "prediction_confidence_mean": (statistics.fmean(confidences) if confidences else 0.0),
            "prediction_queue_mae_vehicles": (
                statistics.fmean(absolute_errors)
                if absolute_errors
                else "not_available_horizon_not_observed"
            ),
        }

    def _apply_scheduled_cloud_outage(self, simulation_time_s: float) -> None:
        start = self.config.cloud_outage_start_s
        duration = self.config.cloud_outage_duration_s
        if start is None or duration is None:
            return
        should_be_online = not start <= simulation_time_s < start + duration
        if should_be_online == self.control.cloud_online:
            return
        self.control.cloud_online = should_be_online
        self.events.append(
            {
                "simulation_time": simulation_time_s,
                "event": ("CLOUD_RECOVERED" if should_be_online else "CLOUD_OFFLINE_INJECTED"),
            }
        )

    @staticmethod
    def _trip_metrics(path: Path) -> dict[str, float | int | str]:
        if not path.is_file():
            return {
                "mean_travel_time": "not_available",
            }
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError:
            return {
                "mean_travel_time": "not_available_incomplete_tripinfo",
            }
        completed = [
            trip for trip in root.findall("tripinfo") if float(trip.get("arrival", "-1")) >= 0
        ]
        if not completed:
            return {
                "mean_travel_time": "not_available_no_completed_trip",
            }
        return {
            "mean_travel_time": statistics.fmean(
                float(trip.get("duration", "0")) for trip in completed
            ),
            "mean_waiting_time_completed": statistics.fmean(
                float(trip.get("waitingTime", "0")) for trip in completed
            ),
            "mean_time_loss_completed": statistics.fmean(
                float(trip.get("timeLoss", "0")) for trip in completed
            ),
            "completed_trip_stop_count": sum(
                int(trip.get("waitingCount", "0")) for trip in completed
            ),
        }

    @staticmethod
    def _roadwork_lane(topology: NetworkTopology) -> str:
        speed_limits = topology.speed_limits_m_s
        candidate_lanes = sorted(
            lane_id for lane_id in speed_limits if not str(lane_id).startswith(":")
        )
        if not candidate_lanes:
            raise RuntimeError("scenario has no lane available for roadwork injection")
        return str(candidate_lanes[len(candidate_lanes) // 2])

    def _disturbance_runtime(
        self,
        fallback_roadwork_lane: str,
        topology: NetworkTopology,
    ) -> DisturbanceRuntime | None:
        definition = self.config.scenario_definition_file
        if definition is None or not definition.is_file():
            return None
        scenario = ScenarioConfig.from_yaml(definition)
        if self.config.scenario_profile_code != "BASE":
            profile_file = self.config.scenario_profile_file
            if profile_file is None or not profile_file.is_file():
                raise FileNotFoundError(f"scenario profile file is unavailable: {profile_file}")
            profile_set = ScenarioProfileSet.from_yaml(profile_file)
            if profile_set.base_scenario_id != self.config.scenario_id:
                raise ValueError("scenario profile set does not belong to the requested scenario")
            profile = profile_set.get(self.config.scenario_profile_code)
            scenario = scenario.model_copy(
                update={
                    "flow_multiplier": profile.flow_multiplier,
                    "connected_vehicle_penetration": (profile.connected_vehicle_penetration),
                    "disturbances": profile.physical_disturbances(),
                    "communication": scenario.communication.model_copy(
                        update={"profile": profile.communication_profile}
                    ),
                }
            )
        if self.config.disturbance_time_scale != 1.0:
            scale = self.config.disturbance_time_scale
            scenario = scenario.model_copy(
                update={
                    "disturbances": [
                        disturbance.model_copy(
                            update={
                                "simulation_time_s": (disturbance.simulation_time_s * scale),
                                "duration_s": disturbance.duration_s * scale,
                            }
                        )
                        for disturbance in scenario.disturbances
                    ]
                }
            )
        return DisturbanceRuntime(
            scenario,
            seed=self.config.seed,
            fallback_roadwork_lane=fallback_roadwork_lane,
            preferred_route_edges={
                str(lane_id).rsplit("_", 1)[0] for lane_id in topology.speed_limits_m_s
            },
        )

    @staticmethod
    def _apply_remote_edge_action(
        adapter: TraciSumoAdapter,
        factory: MessageFactory,
        action: EdgeControlAction,
        state: IntersectionState,
    ) -> ExecutionFeedback:
        """Apply one independently validated edge action to the SUMO owner."""

        executed: dict[str, str | float | None] = {}
        rejection: str | None = None
        status = ExecutionStatus.EXECUTED
        stale = action.simulation_time < state.simulation_time - 2.0
        if action.validation_status == ValidationStatus.REJECTED:
            rejection = ",".join(action.rejection_reasons) or "EDGE_REJECTED"
            status = ExecutionStatus.REJECTED
        elif stale:
            rejection = "ACTION_EXPIRED_IN_SIMULATION_TIME"
            status = ExecutionStatus.REJECTED
        elif action.action_type == ActionType.EXTEND_GREEN:
            if action.requested_duration is None:
                rejection = "MISSING_PHASE_DURATION"
                status = ExecutionStatus.REJECTED
            else:
                adapter.set_phase_duration(
                    action.intersection_id,
                    action.requested_duration,
                )
                executed = {
                    "action_type": action.action_type.value,
                    "duration_s": action.requested_duration,
                }
        elif action.action_type in {
            ActionType.REQUEST_NEXT_PHASE,
            ActionType.TERMINATE_PHASE,
        }:
            adapter.set_phase_duration(action.intersection_id, 0.1)
            executed = {
                "action_type": "terminate_for_safe_program_transition",
                "target_phase_id": action.requested_phase_id,
            }
        elif action.action_type in {
            ActionType.HOLD_PHASE,
            ActionType.FALLBACK_FIXED_TIME,
            ActionType.CHANGE_CYCLE_TARGET,
        }:
            executed = {"action_type": action.action_type.value}
        else:
            rejection = f"UNSUPPORTED_REMOTE_ACTION:{action.action_type.value}"
            status = ExecutionStatus.REJECTED
        if (
            status == ExecutionStatus.EXECUTED
            and action.validation_status == ValidationStatus.MODIFIED
        ):
            status = ExecutionStatus.MODIFIED
        control_mode = str(
            action.expected_effect.get(
                "control_mode",
                EdgeMode.EDGE_AUTONOMOUS.value,
            )
        )
        return factory.build(
            ExecutionFeedback,
            simulation_time=state.simulation_time,
            ttl_s=30.0,
            trace_id=action.trace_id,
            correlation_id=str(action.message_id),
            action_id=action.action_id,
            strategy_id=action.source_strategy_id,
            intersection_id=action.intersection_id,
            requested_action=action.model_dump(mode="json"),
            executed_action=executed,
            execution_status=status,
            rejection_reason=rejection,
            control_mode=control_mode,
            command_latency_ms=max(
                0.0,
                (time.time() - action.created_at.timestamp()) * 1000.0,
            ),
            cloud_round_trip_latency_ms=None,
            actual_start_time=state.simulation_time,
            actual_end_time=None,
            observed_effect={},
        )

    @staticmethod
    def _apply_vehicle_commands(
        adapter: TraciSumoAdapter,
        commands: dict[str, VehicleGuidanceCommand],
    ) -> int:
        active = set(adapter.get_vehicle_ids())
        applied = 0
        for vehicle_id, command in list(commands.items()):
            commands.pop(vehicle_id, None)
            if vehicle_id not in active or command.applied_speed_m_s is None:
                continue
            adapter.apply_speed_guidance(vehicle_id, command.applied_speed_m_s)
            applied += 1
        return applied

    @staticmethod
    async def _publish_vehicle_messages(
        bus: MessageBus,
        vehicle_factory: MessageFactory,
        edge_factory: MessageFactory,
        vehicles: list[VehicleSnapshot],
        controller: EdgeController,
        *,
        simulation_time_s: float,
    ) -> int:
        if controller.control_algorithm != "coordinated-max-pressure":
            return 0
        strategies = list(controller.last_strategy_by_intersection.values())
        target_factor = (
            sum(
                strategy.speed_guidance_parameters.get(
                    "target_speed_factor",
                    1.0,
                )
                for strategy in strategies
            )
            / len(strategies)
            if strategies
            else None
        )
        if target_factor is None or target_factor >= 0.999:
            return 0
        published = 0
        for vehicle in vehicles:
            connected = "connected_vehicle" in vehicle.vehicle_type
            if not connected:
                continue
            state = vehicle_factory.build(
                VehicleState,
                simulation_time=simulation_time_s,
                ttl_s=2.0,
                vehicle_id=vehicle.vehicle_id,
                vehicle_type=vehicle.vehicle_type,
                connected=True,
                road_id=vehicle.road_id,
                lane_id=vehicle.lane_id,
                position_xy=PositionXY(x=vehicle.x_m, y=vehicle.y_m),
                lane_position=vehicle.lane_position_m,
                speed=vehicle.speed_m_s,
                acceleration=vehicle.acceleration_m_s2,
                heading=vehicle.heading_deg % 360.0,
                route_id=vehicle.route_id,
                next_intersection_id=vehicle.next_intersection_id,
                distance_to_stop_line=vehicle.distance_to_stop_line_m,
                turn_direction="unknown",
                waiting_time=vehicle.waiting_time_s,
                stop_count=int(vehicle.waiting_time_s > 0),
                emission_estimate=EmissionEstimate(
                    co2_mg_s=vehicle.co2_mg_s,
                    nox_mg_s=vehicle.nox_mg_s,
                ),
                fuel_consumption_estimate=vehicle.fuel_mg_s,
            )
            await bus.publish(
                (f"traffic/development/vehicle/{vehicle.vehicle_id}/telemetry"),
                state.model_dump_json().encode("utf-8"),
                qos=0,
            )
            if target_factor is None:
                continue
            lane_speed = controller.topology.speed_limits_m_s.get(
                vehicle.lane_id,
                max(vehicle.speed_m_s, 0.1),
            )
            guidance = edge_factory.build(
                SpeedGuidance,
                simulation_time=simulation_time_s,
                ttl_s=2.0,
                trace_id=state.trace_id,
                correlation_id=str(state.message_id),
                vehicle_id=vehicle.vehicle_id,
                recommended_speed_m_s=lane_speed * target_factor,
                speed_limit_m_s=lane_speed,
                valid_until_simulation_time=simulation_time_s + 2.0,
                reason_codes=["CLOUD_SPEED_TARGET", "EDGE_SPEED_LIMIT_LOOKUP"],
            )
            await bus.publish(
                (f"traffic/development/vehicle/{vehicle.vehicle_id}/guidance"),
                guidance.model_dump_json().encode("utf-8"),
                qos=1,
            )
            published += 1
        return published

    @staticmethod
    def _apply_guidance(
        adapter: TraciSumoAdapter,
        controller: EdgeController,
        guidance_agent: VehicleGuidanceAgent,
        vehicles: list[VehicleSnapshot],
        *,
        simulation_time_s: float,
    ) -> tuple[int, int, int]:
        if controller.control_algorithm != "coordinated-max-pressure":
            return 0, 0, 0
        strategies = list(controller.last_strategy_by_intersection.values())
        if not strategies:
            for vehicle in vehicles:
                if "connected_vehicle" in vehicle.vehicle_type:
                    adapter.release_speed_guidance(vehicle.vehicle_id)
            return 0, 0, 0
        target_factor = sum(
            strategy.speed_guidance_parameters.get("target_speed_factor", 1.0)
            for strategy in strategies
        ) / len(strategies)
        actionable_factor = (
            1.0 - controller.algorithm_config.minimum_actionable_speed_reduction_ratio
        )
        acceleration_only = target_factor >= actionable_factor
        motor_vehicles = [
            vehicle
            for vehicle in vehicles
            if getattr(vehicle, "vehicle_class", "passenger") != "bicycle"
        ]
        mean_speed_m_s = (
            sum(vehicle.speed_m_s for vehicle in motor_vehicles) / len(motor_vehicles)
            if motor_vehicles
            else 0.0
        )
        queue_vehicles = sum(vehicle.speed_m_s < 0.1 for vehicle in motor_vehicles)
        gate = getattr(controller, "glosa_effectiveness_gate", None)
        if gate is None:
            gate = GlosaEffectivenessGate(
                window_s=controller.algorithm_config.glosa_effectiveness_window_s,
                cooldown_s=controller.algorithm_config.glosa_effectiveness_cooldown_s,
                minimum_speed_loss_ratio=(
                    controller.algorithm_config.glosa_minimum_speed_loss_ratio
                ),
                minimum_queue_reduction_ratio=(
                    controller.algorithm_config.glosa_minimum_queue_reduction_ratio
                ),
            )
            controller.glosa_effectiveness_gate = gate
        effectiveness_gate_active = gate.observe(
            simulation_time_s=simulation_time_s,
            mean_speed_m_s=mean_speed_m_s,
            queue_vehicles=queue_vehicles,
        )
        classifier = getattr(controller, "glosa_mobility_classifier", None)
        if classifier is None:
            classifier = GlosaMobilityRegimeClassifier(
                window_s=(controller.algorithm_config.glosa_mobility_classification_window_s),
                high_mobility_speed_threshold_m_s=(
                    controller.algorithm_config.high_mobility_speed_threshold_m_s
                ),
            )
            controller.glosa_mobility_classifier = classifier
        mobility_regime = classifier.observe(
            simulation_time_s=simulation_time_s,
            mean_speed_m_s=mean_speed_m_s,
        )
        # A high-mobility classification is only an eligibility signal. The
        # rolling effectiveness gate must still be able to suspend GLOSA when
        # speed loss stops paying back in lower queues later in a long run.
        glosa_enabled = mobility_regime == "high_mobility" and effectiveness_gate_active
        controller.last_glosa_intervention_enabled = glosa_enabled
        minimum_glosa_speed_m_s = (
            controller.algorithm_config.high_mobility_minimum_glosa_speed_m_s
            if mobility_regime == "high_mobility"
            else controller.algorithm_config.minimum_glosa_speed_m_s
        )
        maximum_queue_discharge_speed_m_s = (
            controller.algorithm_config.high_mobility_maximum_queue_discharge_speed_m_s
            if mobility_regime == "high_mobility"
            else controller.algorithm_config.maximum_queue_discharge_guidance_speed_m_s
        )
        queue_discharge_target_speed_m_s = (
            controller.algorithm_config.high_mobility_queue_discharge_target_speed_m_s
            if mobility_regime == "high_mobility"
            else controller.algorithm_config.queue_discharge_target_speed_m_s
        )
        controller.last_glosa_minimum_speed_m_s = minimum_glosa_speed_m_s
        controller.last_queue_discharge_target_speed_m_s = queue_discharge_target_speed_m_s
        green_lane_ids: set[str] = set()
        red_lane_time_to_green_s: dict[str, float] = {}
        if acceleration_only:
            for state in controller.last_state_by_intersection.values():
                phases = controller.topology.phases.get(state.intersection_id, [])
                phase_by_id = {phase.phase_id: phase for phase in phases}
                active_phase = phase_by_id.get(state.current_phase_id)
                if active_phase is not None:
                    green_lane_ids.update(
                        movement.incoming_lane_id for movement in active_phase.movements
                    )
                phase_order = getattr(
                    controller.topology,
                    "phase_order",
                    {},
                ).get(
                    state.intersection_id,
                    [],
                )
                if state.current_phase_id not in phase_order:
                    continue
                phase_durations = getattr(
                    controller.topology,
                    "phase_durations_s",
                    {},
                ).get(
                    state.intersection_id,
                    {},
                )
                current_index = phase_order.index(state.current_phase_id)
                eta_s = max(0.0, state.phase_remaining)
                for offset in range(1, len(phase_order) + 1):
                    phase_id = phase_order[(current_index + offset) % len(phase_order)]
                    phase = phase_by_id.get(phase_id)
                    if phase is not None:
                        for movement in phase.movements:
                            lane_id = movement.incoming_lane_id
                            if lane_id in green_lane_ids:
                                continue
                            previous_eta = red_lane_time_to_green_s.get(lane_id)
                            if previous_eta is None or eta_s < previous_eta:
                                red_lane_time_to_green_s[lane_id] = eta_s
                    eta_s += max(0.0, phase_durations.get(phase_id, 0.0))
        applied_count = 0
        rejected_count = 0
        modified_count = 0
        for vehicle in vehicles:
            if "connected_vehicle" not in vehicle.vehicle_type:
                continue
            lane_speed = controller.topology.speed_limits_m_s.get(
                vehicle.lane_id,
                max(vehicle.speed_m_s, 0.1),
            )
            requested_speed = lane_speed * target_factor
            queue_discharge = acceleration_only and (
                vehicle.lane_id in green_lane_ids
                and vehicle.speed_m_s
                >= controller.algorithm_config.minimum_moving_guidance_speed_m_s
                and vehicle.speed_m_s <= maximum_queue_discharge_speed_m_s
            )
            time_to_green_s = red_lane_time_to_green_s.get(vehicle.lane_id)
            distance_to_stop_line_m = max(
                0.0,
                float(getattr(vehicle, "distance_to_stop_line_m", 0.0)),
            )
            glosa_target_speed_m_s = (
                distance_to_stop_line_m / time_to_green_s
                if time_to_green_s is not None and time_to_green_s > 0.0
                else None
            )
            glosa_approach = bool(
                acceleration_only
                and glosa_enabled
                and glosa_target_speed_m_s is not None
                and controller.algorithm_config.minimum_glosa_distance_m
                <= distance_to_stop_line_m
                <= controller.algorithm_config.maximum_glosa_distance_m
                and time_to_green_s is not None
                and time_to_green_s <= controller.algorithm_config.maximum_glosa_time_to_green_s
                and glosa_target_speed_m_s >= minimum_glosa_speed_m_s
                and glosa_target_speed_m_s <= vehicle.speed_m_s * actionable_factor
            )
            if queue_discharge:
                requested_speed = min(
                    requested_speed,
                    queue_discharge_target_speed_m_s,
                )
            elif glosa_approach and glosa_target_speed_m_s is not None:
                requested_speed = glosa_target_speed_m_s
            if acceleration_only and not queue_discharge and not glosa_approach:
                adapter.release_speed_guidance(vehicle.vehicle_id)
                continue
            if (
                queue_discharge
                and requested_speed - vehicle.speed_m_s
                < controller.algorithm_config.minimum_guidance_acceleration_gain_m_s
            ):
                adapter.release_speed_guidance(vehicle.vehicle_id)
                continue
            decision = ControlDecision(
                status=DecisionStatus.OK,
                intersection_id="vehicle-guidance",
                requested_phase_id=None,
                action_type="apply_speed_guidance",
                requested_duration_s=None,
                scores={"recommended_speed_m_s": requested_speed},
                reason_codes=[
                    "GREEN_QUEUE_DISCHARGE" if queue_discharge else "RED_APPROACH_ARRIVAL_ALIGNMENT"
                ],
                explanation=(
                    "Signal timing and cloud targets converted to a per-vehicle speed request."
                ),
            )
            safety = controller.safety.validate(
                decision,
                SafetyContext(
                    experiment_id=controller.factory.experiment_id,
                    simulation_time=simulation_time_s,
                    action_expires_at_sim_time=simulation_time_s + 1.0,
                    current_phase_id="vehicle-guidance",
                    current_phase_elapsed_s=0.0,
                    min_green_s=1.0,
                    max_green_s=1.0,
                    valid_phase_ids={"vehicle-guidance"},
                    road_speed_limit_m_s=lane_speed,
                    current_vehicle_speed_m_s=vehicle.speed_m_s,
                ),
            )
            if safety.outcome == SafetyOutcome.REJECTED or safety.validated is None:
                adapter.release_speed_guidance(vehicle.vehicle_id)
                rejected_count += 1
                continue
            modified_count += int(safety.outcome == SafetyOutcome.MODIFIED)
            safe_speed = safety.validated.scores["recommended_speed_m_s"]
            result = guidance_agent.apply(
                safe_speed,
                VehicleDynamics(
                    connected=True,
                    current_speed_m_s=vehicle.speed_m_s,
                    speed_limit_m_s=lane_speed,
                ),
            )
            if result.executed and result.applied_speed_m_s is not None:
                adapter.apply_speed_guidance(
                    vehicle.vehicle_id,
                    result.applied_speed_m_s,
                )
                applied_count += 1
            else:
                adapter.release_speed_guidance(vehicle.vehicle_id)
        return applied_count, rejected_count, modified_count


def smoke_config(
    algorithm: str,
    *,
    duration_s: float = 30.0,
    seed: int = 42,
    result_root: Path = Path("results/smoke"),
) -> ExperimentConfig:
    """Build a unique local smoke-experiment request."""

    experiment_id = f"smoke-{algorithm}-{uuid4().hex[:8]}"
    return ExperimentConfig(
        experiment_id=experiment_id,
        scenario_id="xiongan_rongdong_20",
        algorithm=algorithm,
        seed=seed,
        duration_s=duration_s,
        config_file=Path("scenarios/generated/xiongan_rongdong_20/xiongan_rongdong_20.sumocfg"),
        selection_file=Path(
            "scenarios/generated/xiongan_rongdong_20/controlled_intersections.json"
        ),
        result_dir=result_root / experiment_id,
        scenario_definition_file=Path("scenarios/configs/xiongan_rongdong_20.yaml"),
    )
