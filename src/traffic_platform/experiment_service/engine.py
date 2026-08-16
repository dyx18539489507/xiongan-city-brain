"""Actual SUMO-cloud-edge-vehicle experiment runner."""

import asyncio
import json
import os
import platform
import statistics
import time
import xml.etree.ElementTree as ET
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
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
from traffic_platform.vehicle_agent.agent import VehicleDynamics, VehicleGuidanceAgent


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

    def __post_init__(self) -> None:
        """Reject non-causal schedule scaling at configuration time."""

        if self.disturbance_time_scale <= 0:
            raise ValueError("disturbance_time_scale must be positive")


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
            tuple[float, dict[str, float | str | bool]],
        ] = {}
        self._pending_disturbances: list[Disturbance] = []
        self._dynamic_disturbance_counter = 0

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

        duration_s = float(parameters.get("duration_s", 30.0))
        if duration_s <= 0:
            raise ValueError("fault duration_s must be positive")
        if fault_type in {"incident", "flow_surge", "large_event"}:
            self._dynamic_disturbance_counter += 1
            self._pending_disturbances.append(
                Disturbance.model_validate(
                    {
                        "event_id": (f"live_{fault_type}_{self._dynamic_disturbance_counter:04d}"),
                        "type": ("incident" if fault_type == "incident" else "event_dispersal"),
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
                        "parameters": {
                            "flow_multiplier": float(
                                parameters.get(
                                    "flow_multiplier",
                                    2.5 if fault_type == "large_event" else 1.8,
                                )
                            )
                        },
                    },
                    strict=True,
                )
            )
        self._active_faults[fault_type] = (
            self.simulation_time_s + duration_s,
            dict(parameters),
        )
        self._recompute_fault_state()

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
        for fault_type, (_expires_at, parameters) in self._active_faults.items():
            if fault_type == "cloud_offline":
                self.cloud_online = False
            elif fault_type == "edge_offline":
                self.edge_online = False
                self.edge_outage_duration_s = float(parameters.get("duration_s", 30.0))
            elif fault_type in {"mqtt_broker_offline", "broker_offline"}:
                self.broker_online = False
                self.broker_outage_duration_s = float(parameters.get("duration_s", 30.0))
            elif fault_type == "roadwork":
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
        expired = [
            fault_type
            for fault_type, (expires_at, _parameters) in self._active_faults.items()
            if simulation_time_s >= expires_at
        ]
        if expired:
            for fault_type in expired:
                del self._active_faults[fault_type]
            self._recompute_fault_state()
        return expired

    def clear_faults(self) -> None:
        """Restore normal cloud, road and communication conditions."""

        self._active_faults.clear()
        self._recompute_fault_state()


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
        digital_twin_callback: Callable[[DigitalTwinSourceFrame], None] | None = None,
        persistence_callback: (Callable[[str, dict[str, object]], Awaitable[None]] | None) = None,
    ) -> None:
        self.config = config
        self.sumo_home = sumo_home
        self.bus = bus or EmulatedMessageBus(seed=config.seed)
        self.control = control or ExperimentControl()
        self.snapshot_callback = snapshot_callback
        self.digital_twin_callback = digital_twin_callback
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
            label=f"experiment-{self.config.experiment_id[:12]}",
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
            await asyncio.to_thread(
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
                ],
            )
            aggregator = EdgeStateAggregator(
                adapter,
                rsu_factory if isinstance(self.bus, MqttMessageBus) else edge_factory,
                intersection_ids,
            )
            topology = aggregator.build_topology()
            controller = EdgeController(
                adapter,
                edge_factory,
                topology,
                algorithm_config=AlgorithmConfig(),
                degradation_config=self.config.degradation_config,
                control_algorithm=self.config.algorithm,
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
            last_paced_simulation_time: float | None = None
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
                network = await asyncio.to_thread(adapter.step)
                if network.simulation_time_s > self.config.duration_s:
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
                    adapter.close_lane(roadwork_lane_id)
                    roadwork_applied = True
                    self.events.append(
                        {
                            "simulation_time": network.simulation_time_s,
                            "event": "ROADWORK_LANE_CLOSED",
                            "detail": roadwork_lane_id,
                        }
                    )
                elif not self.control.roadwork_active and roadwork_applied:
                    adapter.reopen_lane(roadwork_lane_id)
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
                    self.events.extend(
                        disturbance_runtime.tick(
                            network.simulation_time_s,
                            adapter,
                        )
                    )
                self._apply_scheduled_cloud_outage(network.simulation_time_s)
                regional = aggregator.collect_regional(
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
                for intersection_state in regional.intersection_states:
                    edge_started = time.perf_counter()
                    if isinstance(self.bus, MqttMessageBus):
                        action = pending_edge_actions.pop(
                            intersection_state.intersection_id,
                            None,
                        )
                        feedback = (
                            self._apply_remote_edge_action(
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
                        feedback = controller.control(intersection_state)
                    edge_latencies_ms.append((time.perf_counter() - edge_started) * 1000)
                    if feedback is not None:
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
                guidance_request_count = 0
                if isinstance(self.bus, MqttMessageBus):
                    guidance_count = self._apply_vehicle_commands(
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
                    ) = self._apply_guidance(
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
                pedestrian_states = adapter.get_pedestrian_states()
                arrived_vehicle_ids = adapter.get_arrived_vehicle_ids()
                completed_bicycle_total += sum(
                    vehicle_class_history.get(identifier) == "bicycle"
                    for identifier in arrived_vehicle_ids
                )
                completed_total += sum(
                    vehicle_class_history.get(identifier) != "bicycle"
                    for identifier in arrived_vehicle_ids
                )
                completed_pedestrian_total += len(adapter.get_arrived_pedestrian_ids())
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
                conflicts = safety_monitor.observe(
                    network.simulation_time_s,
                    vehicle_states,
                    pedestrian_states,
                )
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
                    "guidance_count": guidance_count,
                    "guidance_request_count": guidance_request_count,
                    "guidance_rejection_count": guidance_rejections,
                    "guidance_modification_count": guidance_modifications,
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
                if (
                    self.digital_twin_callback is not None
                    and network.simulation_time_s >= next_digital_twin_time_s
                ):
                    self.digital_twin_callback(
                        DigitalTwinSourceFrame(
                            experiment_id=self.config.experiment_id,
                            scenario_id=self.config.scenario_id,
                            simulation_time_s=network.simulation_time_s,
                            tick_hz=dashboard_hz,
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
                                }
                                for state in regional.intersection_states
                            ],
                        )
                    )
                    digital_twin_event_index = len(self.events)
                    next_digital_twin_time_s = network.simulation_time_s + digital_twin_interval_s
                if self.snapshot_callback is not None:
                    current_max_queue = max(
                        (state.total_queue for state in regional.intersection_states),
                        default=0,
                    )
                    downstream_occupancies = [
                        lane.downstream_occupancy
                        for state in regional.intersection_states
                        for lane in state.lane_states
                    ]
                    self.snapshot_callback(
                        {
                            "experiment_id": self.config.experiment_id,
                            "scenario_id": self.config.scenario_id,
                            "scenario_profile": self.config.scenario_profile_code,
                            "algorithm": self.config.algorithm,
                            "intersections": [
                                {
                                    "intersection_id": state.intersection_id,
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
                            "simulation_rate": self.control.simulation_rate,
                            "active_disturbances": (regional.active_disturbances),
                            "spillback_edges": regional.spillback_edges,
                            "congested_intersection_ids": (regional.congested_intersections),
                            "recent_events": self.events[-60:],
                            **sample_dict,
                        }
                    )
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
            adapter.stop_simulation()
            if controller is not None:
                controller.close()
            await self.bus.disconnect()
        wall_duration = time.perf_counter() - started_wall
        metrics = accumulator.summary()
        if controller is not None:
            metrics["algorithm_timeout_count"] = controller.algorithm_timeout_count
            metrics["algorithm_failure_count"] = controller.algorithm_failure_count
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
                "algorithm_version": "1.0.0",
                "scenario_profile": self.config.scenario_profile_code,
                "seed": self.config.seed,
                "duration_s": self.config.duration_s,
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
        result: dict[str, object] = {
            "schema_version": "1.0",
            "experiment_id": self.config.experiment_id,
            "scenario_id": self.config.scenario_id,
            "scenario_profile": self.config.scenario_profile_code,
            "algorithm": self.config.algorithm,
            "seed": self.config.seed,
            "actual_run": True,
            "message_transport": type(self.bus).__name__,
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
        strategies = list(controller.last_strategy_by_intersection.values())
        if not strategies:
            return 0, 0, 0
        target_factor = sum(
            strategy.speed_guidance_parameters.get("target_speed_factor", 1.0)
            for strategy in strategies
        ) / len(strategies)
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
            decision = ControlDecision(
                status=DecisionStatus.OK,
                intersection_id="vehicle-guidance",
                requested_phase_id=None,
                action_type="apply_speed_guidance",
                requested_duration_s=None,
                scores={"recommended_speed_m_s": requested_speed},
                reason_codes=["CLOUD_SPEED_TARGET"],
                explanation="Cloud target converted to a per-vehicle speed request.",
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
