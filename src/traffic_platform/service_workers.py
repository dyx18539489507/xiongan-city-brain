"""Independent MQTT/Redis service processes used by Docker Compose."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import signal
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

from traffic_platform.algorithm_sdk.types import (
    AlgorithmConfig,
    ControlDecision,
    DecisionStatus,
    NetworkTopology,
    PhaseDefinition,
    PhaseMovement,
)
from traffic_platform.cloud_service.coordinator import (
    CoordinatorConfig,
    RegionalCoordinator,
)
from traffic_platform.common.runtime_registry import RuntimeRegistry
from traffic_platform.contracts.factory import MessageFactory
from traffic_platform.contracts.idempotency import IdempotencyGuard
from traffic_platform.contracts.models import (
    ActionType,
    CloudStrategy,
    CommunicationEvent,
    EdgeControlAction,
    ExecutionFeedback,
    ExecutionStatus,
    ExperimentEvent,
    IntersectionState,
    MetricSnapshot,
    RegionalState,
    ServiceHeartbeat,
    SourceType,
    SpeedGuidance,
    TrafficMessage,
    ValidationStatus,
    VehicleGuidanceCommand,
    VehicleState,
)
from traffic_platform.edge_service.controller import EdgeController
from traffic_platform.edge_service.state_machine import (
    EdgeDegradationMachine,
)
from traffic_platform.messaging.base import MessageBus
from traffic_platform.messaging.factory import message_bus_from_environment
from traffic_platform.observability.logging import get_logger
from traffic_platform.report_service.generator import generate_report
from traffic_platform.safety_kernel import SafetyContext, SafetyKernel, SafetyOutcome
from traffic_platform.sumo_adapter import TraciSumoAdapter
from traffic_platform.vehicle_agent.agent import VehicleDynamics, VehicleGuidanceAgent

logger = get_logger(__name__)


class _RemoteActuationAdapter:
    """Capture safety-approved edge actions without owning a SUMO connection."""

    def __init__(self) -> None:
        self.last_duration: dict[str, float] = {}

    def set_phase_duration(
        self,
        intersection_id: str,
        duration_s: float,
    ) -> None:
        self.last_duration[intersection_id] = duration_s


class ServiceWorker:
    """Long-running role process with real broker and Redis lifecycles."""

    def __init__(
        self,
        role: str,
        bus: MessageBus,
        registry: RuntimeRegistry,
        *,
        environment: str,
        instance_id: str,
    ) -> None:
        self.role = role
        self.bus = bus
        self.registry = registry
        self.environment = environment
        self.instance_id = instance_id
        self.boot_id = uuid4().hex[:8]
        self.message_source_id = f"{instance_id}-{self.boot_id}"
        self.stop_event = asyncio.Event()
        self.factory = MessageFactory(
            source_id=self.message_source_id,
            source_type=_source_type(role),
            scenario_id="system",
            experiment_id="system",
            environment=environment,
        )
        self.guard = IdempotencyGuard()
        self.message_count = 0
        self._vehicle_states: dict[str, VehicleState] = {}
        self._vehicle_agent = VehicleGuidanceAgent()
        self._safety = SafetyKernel()
        self._coordinators: dict[tuple[str, str], RegionalCoordinator] = {}
        self._edge_machines: dict[str, EdgeDegradationMachine] = {}
        self._edge_transition_offsets: dict[str, int] = {}
        self._edge_controllers: dict[str, EdgeController] = {}
        self._edge_strategies: dict[str, dict[str, CloudStrategy]] = {}
        self._edge_control_lock = asyncio.Lock()
        self._last_cloud_decision_time: dict[tuple[str, str], float] = {}
        self._message_factories: dict[tuple[str, str], MessageFactory] = {}

    def _factory_for(
        self,
        scenario_id: str,
        experiment_id: str,
    ) -> MessageFactory:
        """Reuse one sequence-number authority per service and experiment."""

        key = (scenario_id, experiment_id)
        factory = self._message_factories.get(key)
        if factory is None:
            factory = MessageFactory(
                source_id=self.message_source_id,
                source_type=_source_type(self.role),
                scenario_id=scenario_id,
                experiment_id=experiment_id,
                environment=self.environment,
            )
            self._message_factories[key] = factory
        return factory

    async def run(self) -> None:
        """Connect dependencies, serve role subscriptions and stop gracefully."""

        await self.registry.ping()
        await self.bus.connect()
        await self._subscribe_role()
        heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(),
            name=f"{self.role}-heartbeat",
        )
        try:
            await self.stop_event.wait()
        finally:
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
            for controller in self._edge_controllers.values():
                controller.close()
            await self.bus.disconnect()
            await self.registry.close()

    def stop(self) -> None:
        """Request cooperative service shutdown."""

        self.stop_event.set()

    async def _subscribe_role(self) -> None:
        if self.role == "cloud-service":
            await self.bus.subscribe(
                f"traffic/{self.environment}/edge/+/state",
                self._cloud_state,
                qos=1,
            )
        elif self.role == "rsu-service":
            await self.bus.subscribe(
                f"traffic/{self.environment}/sumo/+/observation",
                self._rsu_observation,
                qos=1,
            )
        elif self.role == "edge-service":
            await self.bus.subscribe(
                f"traffic/{self.environment}/cloud/strategy/+",
                self._edge_strategy,
                qos=1,
            )
            await self.bus.subscribe(
                f"traffic/{self.environment}/rsu/+/state",
                self._edge_regional_state,
                qos=1,
            )
            await self.bus.subscribe(
                f"traffic/{self.environment}/vehicle/+/state",
                self._edge_vehicle_state,
                qos=0,
            )
        elif self.role == "vehicle-agent":
            await self.bus.subscribe(
                f"traffic/{self.environment}/vehicle/+/telemetry",
                self._vehicle_state,
                qos=0,
            )
            await self.bus.subscribe(
                f"traffic/{self.environment}/vehicle/+/guidance",
                self._vehicle_guidance,
                qos=1,
            )
        elif self.role in {"report-service", "sumo-runner"}:
            await self.bus.subscribe(
                f"traffic/{self.environment}/experiment/+/event",
                self._record_event,
                qos=1,
            )
            if self.role == "report-service":
                await self.bus.subscribe(
                    f"traffic/{self.environment}/experiment/+/metric",
                    self._record_metric,
                    qos=0,
                )
                await self.bus.subscribe(
                    f"traffic/{self.environment}/experiment/+/communication",
                    self._record_communication,
                    qos=1,
                )
            else:
                await self.bus.subscribe(
                    f"traffic/{self.environment}/edge/+/action/+",
                    self._record_sumo_action,
                    qos=1,
                )
                await self.bus.subscribe(
                    f"traffic/{self.environment}/vehicle/+/command",
                    self._record_sumo_vehicle_command,
                    qos=1,
                )
        else:
            raise ValueError(f"unsupported service worker role: {self.role}")

    async def _rsu_observation(self, _topic: str, payload: bytes) -> None:
        """Validate the SUMO sensor gateway payload and publish an RSU state."""

        observation = RegionalState.model_validate_json(payload)
        if not await self._communication_allowed(observation, channel="sumo_rsu"):
            return
        self.guard.accept(observation, check_order=False)
        self.message_count += 1
        factory = self._factory_for(
            observation.scenario_id,
            observation.experiment_id,
        )
        state = factory.build(
            RegionalState,
            simulation_time=observation.simulation_time,
            ttl_s=3.0,
            trace_id=observation.trace_id,
            correlation_id=str(observation.message_id),
            intersection_states=observation.intersection_states,
            network_mean_speed=observation.network_mean_speed,
            total_queue=observation.total_queue,
            congested_intersections=observation.congested_intersections,
            spillback_edges=observation.spillback_edges,
            risk_levels=observation.risk_levels,
            active_disturbances=observation.active_disturbances,
        )
        await self.registry.set_latest(
            "rsu-regional-state",
            state.experiment_id,
            state.model_dump(mode="json"),
            ttl_s=30,
        )
        await self.bus.publish(
            f"traffic/{self.environment}/rsu/{self.instance_id}/state",
            state.model_dump_json().encode("utf-8"),
            qos=1,
        )

    async def _cloud_state(self, _topic: str, payload: bytes) -> None:
        state = RegionalState.model_validate_json(payload)
        if not await self._communication_allowed(state, channel="cloud_edge"):
            return
        self.guard.accept(state)
        self.message_count += 1
        coordinator_key = (state.scenario_id, state.experiment_id)
        await self.registry.set_latest(
            "cloud-regional-state",
            state.experiment_id,
            state.model_dump(mode="json"),
            ttl_s=30,
        )
        decision_interval_s = float(os.environ.get("CLOUD_DECISION_INTERVAL_S", "5.0"))
        previous_decision_time = self._last_cloud_decision_time.get(coordinator_key)
        if (
            previous_decision_time is not None
            and state.simulation_time - previous_decision_time < decision_interval_s
        ):
            return
        self._last_cloud_decision_time[coordinator_key] = state.simulation_time
        coordinator = self._coordinators.get(coordinator_key)
        if coordinator is None:
            factory = MessageFactory(
                source_id=self.message_source_id,
                source_type=SourceType.CLOUD,
                scenario_id=state.scenario_id,
                experiment_id=state.experiment_id,
                environment=self.environment,
            )
            selection_path = (
                Path("scenarios")
                / "generated"
                / state.scenario_id
                / "controlled_intersections.json"
            )
            coordinator_config = (
                CoordinatorConfig.from_selection(
                    json.loads(selection_path.read_text(encoding="utf-8"))
                )
                if selection_path.is_file()
                else CoordinatorConfig()
            )
            coordinator = RegionalCoordinator(factory, coordinator_config)
            self._coordinators[coordinator_key] = coordinator
        strategies = coordinator.strategies(state)
        persisted_strategies: list[CloudStrategy] = []
        for strategy in strategies:
            version_key = f"{state.experiment_id}:{strategy.target_intersection_id}"
            previous = await self.registry.get_latest(
                "cloud-version",
                version_key,
            )
            previous_version = (
                int(previous.get("strategy_version", 0)) if previous is not None else 0
            )
            strategy = strategy.model_copy(
                update={
                    "strategy_version": max(
                        strategy.strategy_version,
                        previous_version + 1,
                    ),
                    "cloud_decision_latency_ms": coordinator.last_decision_ms,
                }
            )
            await self.registry.set_latest(
                "cloud-version",
                version_key,
                {
                    "strategy_version": strategy.strategy_version,
                    "cloud_boot_id": self.boot_id,
                },
            )
            await self.bus.publish(
                (f"traffic/{self.environment}/cloud/strategy/{strategy.target_intersection_id}"),
                strategy.model_dump_json().encode("utf-8"),
                qos=1,
            )
            persisted_strategies.append(strategy)
        await self.registry.set_latest(
            "cloud-decision",
            state.experiment_id,
            {
                "simulation_time": state.simulation_time,
                "strategy_count": len(persisted_strategies),
                "decision_latency_ms": coordinator.last_decision_ms,
                "cloud_boot_id": self.boot_id,
            },
        )

    async def _edge_strategy(self, _topic: str, payload: bytes) -> None:
        strategy = CloudStrategy.model_validate_json(payload)
        if not await self._communication_allowed(
            strategy,
            channel="cloud_edge",
        ):
            return
        self.guard.accept(strategy, check_order=False)
        self.message_count += 1
        async with self._edge_control_lock:
            await self._apply_edge_strategy(strategy)

    async def _apply_edge_strategy(self, strategy: CloudStrategy) -> None:
        """Apply one strategy atomically with regional-state edge control."""

        machine = await self._edge_machine(
            strategy.experiment_id,
            strategy.simulation_time,
            cloud_available=True,
        )
        live_simulation_time = max(
            strategy.simulation_time,
            machine.last_simulation_time or strategy.simulation_time,
        )
        accepted = machine.accept_strategy(
            strategy,
            simulation_time=live_simulation_time,
            experiment_id=strategy.experiment_id,
        )
        if not accepted:
            return
        machine.tick(live_simulation_time)
        self._edge_strategies.setdefault(strategy.experiment_id, {})[
            strategy.target_intersection_id
        ] = strategy
        controller = self._edge_controllers.get(strategy.experiment_id)
        if controller is not None:
            controller.machine = machine
            controller.last_strategy_by_intersection[strategy.target_intersection_id] = strategy
        await self.registry.set_latest(
            "edge-strategy",
            strategy.target_intersection_id,
            strategy.model_dump(mode="json"),
        )
        await self._persist_edge_machine(
            strategy.scenario_id,
            strategy.experiment_id,
            machine,
        )
        await self._publish_edge_guidance(strategy)

    async def _edge_regional_state(self, _topic: str, payload: bytes) -> None:
        state = RegionalState.model_validate_json(payload)
        if not await self._communication_allowed(state, channel="sumo_edge"):
            return
        self.guard.accept(state, check_order=False)
        self.message_count += 1
        async with self._edge_control_lock:
            await self._apply_edge_regional_state(state)

    async def _apply_edge_regional_state(self, state: RegionalState) -> None:
        """Control one regional snapshot atomically with strategy updates."""

        machine = await self._edge_machine(
            state.experiment_id,
            state.simulation_time,
            cloud_available=False,
        )
        machine.tick(state.simulation_time)
        controller = self._edge_controllers.get(state.experiment_id)
        if controller is None:
            controller = self._build_remote_controller(state, machine)
            self._edge_controllers[state.experiment_id] = controller
        else:
            controller.machine = machine
        await self._persist_edge_machine(
            state.scenario_id,
            state.experiment_id,
            machine,
        )
        reported_intersections = [
            intersection.model_copy(update={"local_control_mode": machine.mode.value})
            for intersection in state.intersection_states
        ]
        factory = self._factory_for(state.scenario_id, state.experiment_id)
        edge_state = factory.build(
            RegionalState,
            simulation_time=state.simulation_time,
            ttl_s=3.0,
            trace_id=state.trace_id,
            correlation_id=str(state.message_id),
            intersection_states=reported_intersections,
            network_mean_speed=state.network_mean_speed,
            total_queue=state.total_queue,
            congested_intersections=state.congested_intersections,
            spillback_edges=state.spillback_edges,
            risk_levels=state.risk_levels,
            active_disturbances=state.active_disturbances,
        )
        await self.bus.publish(
            f"traffic/{self.environment}/edge/{self.instance_id}/state",
            edge_state.model_dump_json().encode("utf-8"),
            qos=1,
        )
        for reported in reported_intersections:
            await self.bus.publish(
                (
                    f"traffic/{self.environment}/edge/{self.instance_id}/"
                    f"intersection/{reported.intersection_id}/state"
                ),
                reported.model_dump_json().encode("utf-8"),
                qos=0,
            )
            feedback = controller.control(reported)
            if feedback is not None:
                await self._publish_edge_action(feedback, reported)

    def _build_remote_controller(
        self,
        state: RegionalState,
        machine: EdgeDegradationMachine,
    ) -> EdgeController:
        phases: dict[str, list[PhaseDefinition]] = {}
        speed_limits: dict[str, float] = {}
        conflicts: dict[str, set[tuple[str, str]]] = {}
        for intersection in state.intersection_states:
            grouped: dict[str, list[PhaseMovement]] = {}
            for lane in intersection.lane_states:
                if lane.movement == "out":
                    continue
                grouped.setdefault(lane.movement, []).append(
                    PhaseMovement(
                        incoming_lane_id=lane.lane_id,
                        outgoing_lane_id=(lane.downstream_lane_id or lane.lane_id),
                    )
                )
                speed_limits[lane.lane_id] = max(lane.mean_speed, 13.9)
            phases[intersection.intersection_id] = [
                PhaseDefinition(phase_id=phase_id, movements=movements)
                for phase_id, movements in sorted(grouped.items())
            ]
            phase_ids = set(grouped)
            conflicts[intersection.intersection_id] = {
                (left, right) for left in phase_ids for right in phase_ids if left != right
            }
        topology = NetworkTopology(
            intersection_ids=[item.intersection_id for item in state.intersection_states],
            phases=phases,
            downstream_intersections={
                item.intersection_id: [] for item in state.intersection_states
            },
            speed_limits_m_s=speed_limits,
            conflicting_phase_pairs=conflicts,
            pedestrian_phase_ids={
                item.intersection_id: set() for item in state.intersection_states
            },
            clearance_phase_ids={item.intersection_id: set() for item in state.intersection_states},
        )
        factory = self._factory_for(state.scenario_id, state.experiment_id)
        controller = EdgeController(
            cast(TraciSumoAdapter, _RemoteActuationAdapter()),
            factory,
            topology,
            algorithm_config=AlgorithmConfig(),
            control_algorithm=os.environ.get(
                "EDGE_CONTROL_ALGORITHM",
                "coordinated-max-pressure",
            ),
            isolate_algorithms=False,
        )
        controller.machine = machine
        controller.last_strategy_by_intersection.update(
            self._edge_strategies.get(state.experiment_id, {})
        )
        return controller

    async def _publish_edge_action(
        self,
        feedback: ExecutionFeedback,
        state: IntersectionState,
    ) -> None:
        requested = feedback.requested_action
        action_type = ActionType(str(requested["action_type"]))
        status = {
            ExecutionStatus.EXECUTED: ValidationStatus.ACCEPTED,
            ExecutionStatus.MODIFIED: ValidationStatus.MODIFIED,
            ExecutionStatus.REJECTED: ValidationStatus.REJECTED,
            ExecutionStatus.FAILED: ValidationStatus.REJECTED,
        }[feedback.execution_status]
        factory = self._factory_for(state.scenario_id, state.experiment_id)
        command = factory.build(
            EdgeControlAction,
            simulation_time=state.simulation_time,
            ttl_s=2.0,
            trace_id=feedback.trace_id,
            correlation_id=str(state.message_id),
            action_id=feedback.action_id,
            intersection_id=state.intersection_id,
            requested_phase_id=requested.get("requested_phase_id"),
            action_type=action_type,
            requested_duration=requested.get("requested_duration_s"),
            source_strategy_id=feedback.strategy_id,
            validation_status=status,
            rejection_reasons=([feedback.rejection_reason] if feedback.rejection_reason else []),
            applied_at=None,
            expected_effect={
                **feedback.executed_action,
                "control_mode": feedback.control_mode,
                "edge_decision_latency_ms": feedback.command_latency_ms,
                "cloud_decision_latency_ms": (
                    strategy.cloud_decision_latency_ms
                    if (
                        strategy := self._edge_strategies.get(
                            state.experiment_id,
                            {},
                        ).get(state.intersection_id)
                    )
                    is not None
                    else "not_available"
                ),
            },
        )
        await self.bus.publish(
            (f"traffic/{self.environment}/edge/{self.instance_id}/action/{state.intersection_id}"),
            command.model_dump_json().encode("utf-8"),
            qos=1,
        )

    async def _edge_vehicle_state(self, _topic: str, payload: bytes) -> None:
        state = VehicleState.model_validate_json(payload)
        if not await self._communication_allowed(
            state,
            channel="edge_vehicle",
        ):
            return
        self.guard.accept(state, check_order=False)
        self._vehicle_states[state.vehicle_id] = state

    async def _publish_edge_guidance(self, strategy: CloudStrategy) -> None:
        factor = strategy.speed_guidance_parameters.get(
            "target_speed_factor",
            1.0,
        )
        factory = self._factory_for(strategy.scenario_id, strategy.experiment_id)
        for vehicle in list(self._vehicle_states.values()):
            if vehicle.experiment_id != strategy.experiment_id or not vehicle.connected:
                continue
            guidance = factory.build(
                SpeedGuidance,
                simulation_time=strategy.simulation_time,
                ttl_s=2.0,
                trace_id=strategy.trace_id,
                correlation_id=str(strategy.message_id),
                vehicle_id=vehicle.vehicle_id,
                recommended_speed_m_s=max(0.0, vehicle.speed * factor),
                speed_limit_m_s=max(vehicle.speed, 0.1),
                valid_until_simulation_time=strategy.simulation_time + 2.0,
                reason_codes=[
                    "CLOUD_SPEED_TARGET",
                    "EDGE_VEHICLE_STATE_LIMIT",
                ],
            )
            await self.bus.publish(
                (f"traffic/{self.environment}/vehicle/{vehicle.vehicle_id}/guidance"),
                guidance.model_dump_json().encode("utf-8"),
                qos=1,
            )

    async def _edge_machine(
        self,
        experiment_id: str,
        simulation_time: float,
        *,
        cloud_available: bool,
    ) -> EdgeDegradationMachine:
        machine = self._edge_machines.get(experiment_id)
        if machine is not None:
            return machine
        machine = EdgeDegradationMachine()
        snapshot = await self.registry.get_latest(
            "edge-degradation",
            experiment_id,
        )
        if snapshot is not None:
            machine.restore(
                snapshot,
                experiment_id=experiment_id,
                simulation_time=simulation_time,
                cloud_available=cloud_available,
            )
        self._edge_machines[experiment_id] = machine
        self._edge_transition_offsets[experiment_id] = 0
        return machine

    async def _persist_edge_machine(
        self,
        scenario_id: str,
        experiment_id: str,
        machine: EdgeDegradationMachine,
    ) -> None:
        await self.registry.set_latest(
            "edge-degradation",
            experiment_id,
            machine.snapshot(experiment_id=experiment_id),
        )
        offset = self._edge_transition_offsets.get(experiment_id, 0)
        for transition in machine.transitions[offset:]:
            factory = self._factory_for(scenario_id, experiment_id)
            event = factory.build(
                ExperimentEvent,
                simulation_time=transition.simulation_time,
                ttl_s=3600.0,
                event_type="EDGE_MODE_TRANSITION",
                payload={
                    "previous": transition.previous.value,
                    "current": transition.current.value,
                    "reason": transition.reason,
                },
            )
            await self.bus.publish(
                (f"traffic/{self.environment}/experiment/{experiment_id}/event"),
                event.model_dump_json().encode("utf-8"),
                qos=1,
            )
        self._edge_transition_offsets[experiment_id] = len(machine.transitions)

    async def _vehicle_state(self, _topic: str, payload: bytes) -> None:
        state = VehicleState.model_validate_json(payload)
        if not await self._communication_allowed(
            state,
            channel="edge_vehicle",
        ):
            return
        self.guard.accept(state, check_order=False)
        self.message_count += 1
        reported = state.model_copy(
            update={
                "message_id": uuid4(),
                "source_id": self.message_source_id,
                "sequence_number": self.message_count,
                "correlation_id": str(state.message_id),
            }
        )
        self._vehicle_states[state.vehicle_id] = reported
        await self.bus.publish(
            (f"traffic/{self.environment}/vehicle/{state.vehicle_id}/state"),
            reported.model_dump_json().encode("utf-8"),
            qos=0,
        )

    async def _vehicle_guidance(self, _topic: str, payload: bytes) -> None:
        guidance = SpeedGuidance.model_validate_json(payload)
        if not await self._communication_allowed(
            guidance,
            channel="edge_vehicle",
        ):
            return
        self.guard.accept(guidance, check_order=False)
        state = self._vehicle_states.get(guidance.vehicle_id)
        reasons: list[str] = []
        applied: float | None = None
        executed = False
        validation_status = "rejected"
        if guidance.valid_until_simulation_time <= guidance.simulation_time:
            reasons.append("GUIDANCE_EXPIRED")
        elif state is None:
            reasons.append("VEHICLE_STATE_NOT_AVAILABLE")
        elif not state.connected:
            reasons.append("VEHICLE_NOT_CONNECTED")
        else:
            decision = ControlDecision(
                status=DecisionStatus.OK,
                intersection_id="vehicle-guidance",
                requested_phase_id=None,
                action_type="apply_speed_guidance",
                scores={"recommended_speed_m_s": guidance.recommended_speed_m_s},
                reason_codes=guidance.reason_codes,
                explanation="Vehicle service validates one edge speed target.",
            )
            safety = self._safety.validate(
                decision,
                SafetyContext(
                    experiment_id=guidance.experiment_id,
                    simulation_time=guidance.simulation_time,
                    action_expires_at_sim_time=guidance.valid_until_simulation_time,
                    current_phase_id="vehicle-guidance",
                    current_phase_elapsed_s=0.0,
                    min_green_s=1.0,
                    max_green_s=1.0,
                    valid_phase_ids={"vehicle-guidance"},
                    road_speed_limit_m_s=guidance.speed_limit_m_s,
                    current_vehicle_speed_m_s=state.speed,
                ),
            )
            if safety.outcome == SafetyOutcome.REJECTED or safety.validated is None:
                reasons.extend(safety.reasons)
                safe_speed = guidance.recommended_speed_m_s
            else:
                reasons.extend(safety.reasons)
                safe_speed = safety.validated.scores["recommended_speed_m_s"]
            result = self._vehicle_agent.apply(
                safe_speed,
                VehicleDynamics(
                    connected=state.connected,
                    current_speed_m_s=state.speed,
                    speed_limit_m_s=guidance.speed_limit_m_s,
                ),
            )
            if safety.outcome != SafetyOutcome.REJECTED:
                applied = result.applied_speed_m_s
                executed = result.executed
                reasons.extend(result.reasons)
                validation_status = (
                    "modified"
                    if safety.outcome == SafetyOutcome.MODIFIED
                    or result.reasons != ("GUIDANCE_ACCEPTED",)
                    else "accepted"
                )
        factory = self._factory_for(guidance.scenario_id, guidance.experiment_id)
        command = factory.build(
            VehicleGuidanceCommand,
            simulation_time=guidance.simulation_time,
            ttl_s=2.0,
            trace_id=guidance.trace_id,
            correlation_id=str(guidance.message_id),
            vehicle_id=guidance.vehicle_id,
            requested_speed_m_s=guidance.recommended_speed_m_s,
            applied_speed_m_s=applied,
            executed=executed,
            validation_status=validation_status,
            validation_reasons=reasons,
        )
        await self.bus.publish(
            (f"traffic/{self.environment}/vehicle/{guidance.vehicle_id}/command"),
            command.model_dump_json().encode("utf-8"),
            qos=1,
        )
        self.message_count += 1

    async def _communication_allowed(
        self,
        message: TrafficMessage,
        *,
        channel: str,
    ) -> bool:
        """Apply live real-MQTT faults shared through Redis.

        The deterministic simulation-time channel remains the benchmark model.
        This adapter makes the same operator controls observable on independently
        deployed MQTT workers without coupling their internal implementations.
        """

        try:
            profile = await self.registry.get_latest(
                "communication-fault-profile",
                "active",
            )
        except (OSError, RuntimeError, TimeoutError) as exc:
            logger.warning(
                "communication_fault_profile_unavailable",
                role=self.role,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return True
        if profile is None:
            return True
        raw_faults = profile.get("faults", [])
        if not isinstance(raw_faults, list):
            return True
        now = datetime.now(UTC)
        configured_latency_ms = 0.0
        packet_loss_rate = 0.0
        forced_offline = False
        recovery_time_s: float | None = None
        for raw_fault in raw_faults:
            if not isinstance(raw_fault, dict):
                continue
            expires_at = raw_fault.get("expires_at")
            if not isinstance(expires_at, str):
                continue
            try:
                expires_at_utc = datetime.fromisoformat(expires_at)
            except ValueError:
                continue
            experiment_ids = raw_fault.get("experiment_ids")
            if isinstance(experiment_ids, list):
                scoped_ids = {str(experiment_id) for experiment_id in experiment_ids}
                if message.experiment_id not in scoped_ids:
                    continue
            elif expires_at_utc <= now:
                # Compatibility cleanup for profiles written before faults
                # were explicitly scoped to experiment IDs.
                continue
            expires_at_simulation_time = raw_fault.get("expires_at_simulation_time")
            if isinstance(expires_at_simulation_time, int | float):
                if message.simulation_time >= float(expires_at_simulation_time):
                    continue
            elif expires_at_utc <= now:
                continue
            fault_type = str(raw_fault.get("fault_type", ""))
            target = str(raw_fault.get("target", ""))
            parameters = raw_fault.get("parameters", {})
            if not isinstance(parameters, dict):
                parameters = {}
            channel_targeted = target in {channel, "all", "*"}
            if (
                (fault_type == "cloud_offline" and self.role == "cloud-service")
                or (fault_type == "edge_offline" and self.role == "edge-service")
                or fault_type in {"mqtt_broker_offline", "broker_offline"}
            ):
                forced_offline = True
                recovery_time_s = max(
                    recovery_time_s or 0.0,
                    (expires_at_utc - now).total_seconds(),
                )
            elif fault_type == "communication_latency" and channel_targeted:
                configured_latency_ms = max(
                    configured_latency_ms,
                    float(parameters.get("latency_ms", 0.0)),
                )
            elif fault_type == "packet_loss" and channel_targeted:
                packet_loss_rate = max(
                    packet_loss_rate,
                    float(parameters.get("packet_loss_rate", 0.0)),
                )
        digest = hashlib.sha256(
            (f"{message.message_id}:{self.role}:{channel}:{message.sequence_number}").encode()
        ).digest()
        draw = int.from_bytes(digest[:8], "big") / (2**64 - 1)
        dropped = forced_offline or draw < packet_loss_rate
        started = time.perf_counter()
        if configured_latency_ms > 0 and not dropped:
            await asyncio.sleep(configured_latency_ms / 1000.0)
        actual_latency_ms = (time.perf_counter() - started) * 1000.0
        if configured_latency_ms > 0 or packet_loss_rate > 0 or forced_offline:
            await self.registry.set_latest(
                "communication-event",
                str(message.message_id),
                {
                    "message_id": str(message.message_id),
                    "simulation_time": message.simulation_time,
                    "channel": channel,
                    "destination_role": self.role,
                    "configured_latency_ms": configured_latency_ms,
                    "actual_latency_ms": actual_latency_ms,
                    "packet_loss_rate": packet_loss_rate,
                    "dropped": dropped,
                    "offline": forced_offline,
                },
                ttl_s=3600,
            )
            factory = self._factory_for(message.scenario_id, message.experiment_id)
            communication_event = factory.build(
                CommunicationEvent,
                simulation_time=message.simulation_time,
                ttl_s=3600.0,
                trace_id=message.trace_id,
                correlation_id=str(message.message_id),
                channel=channel,
                source=message.source_id,
                destination=self.role,
                message_type=type(message).__name__,
                configured_latency_ms=configured_latency_ms,
                actual_latency_ms=actual_latency_ms,
                dropped=dropped,
                duplicated=False,
                reordered=False,
                corrupted=False,
                timeout=False,
                recovery_time=recovery_time_s,
            )
            await self.bus.publish(
                (f"traffic/{self.environment}/experiment/{message.experiment_id}/communication"),
                communication_event.model_dump_json().encode("utf-8"),
                qos=1,
            )
        if dropped:
            logger.warning(
                "mqtt_message_fault_dropped",
                role=self.role,
                channel=channel,
                message_id=str(message.message_id),
                simulation_time=message.simulation_time,
                packet_loss_rate=packet_loss_rate,
                offline=forced_offline,
            )
        return not dropped

    async def _record_event(self, topic: str, payload: bytes) -> None:
        event = ExperimentEvent.model_validate_json(payload)
        self.guard.accept(event, check_order=False)
        self.message_count += 1
        await self.registry.set_latest(
            f"{self.role}-event",
            topic.rsplit("/", 2)[-2],
            {"topic": topic, "payload": event.model_dump(mode="json")},
        )
        if self.role == "report-service" and event.event_type == "REPORT_READY":
            await self._generate_independent_report(event)

    async def _record_metric(self, topic: str, payload: bytes) -> None:
        metric = MetricSnapshot.model_validate_json(payload)
        self.guard.accept(metric, check_order=False)
        self.message_count += 1
        await self.registry.set_latest(
            "report-metric",
            metric.experiment_id,
            {"topic": topic, "payload": metric.model_dump(mode="json")},
            ttl_s=300,
        )

    async def _record_communication(self, topic: str, payload: bytes) -> None:
        event = CommunicationEvent.model_validate_json(payload)
        self.guard.accept(event, check_order=False)
        self.message_count += 1
        await self.registry.set_latest(
            "report-communication",
            event.experiment_id,
            {"topic": topic, "payload": event.model_dump(mode="json")},
            ttl_s=3600,
        )

    async def _record_sumo_action(self, topic: str, payload: bytes) -> None:
        """Validate and retain the latest command at the remote SUMO boundary."""

        action = EdgeControlAction.model_validate_json(payload)
        self.guard.accept(action, check_order=False)
        self.message_count += 1
        await self.registry.set_latest(
            "sumo-action",
            action.experiment_id,
            {
                "topic": topic,
                "message_id": str(action.message_id),
                "trace_id": action.trace_id,
                "intersection_id": action.intersection_id,
                "validation_status": action.validation_status.value,
                "simulation_time": action.simulation_time,
            },
            ttl_s=3600,
        )

    async def _record_sumo_vehicle_command(
        self,
        topic: str,
        payload: bytes,
    ) -> None:
        """Validate and retain the latest vehicle command at the SUMO boundary."""

        command = VehicleGuidanceCommand.model_validate_json(payload)
        self.guard.accept(command, check_order=False)
        self.message_count += 1
        await self.registry.set_latest(
            "sumo-vehicle-command",
            command.experiment_id,
            {
                "topic": topic,
                "message_id": str(command.message_id),
                "trace_id": command.trace_id,
                "vehicle_id": command.vehicle_id,
                "executed": command.executed,
                "simulation_time": command.simulation_time,
            },
            ttl_s=3600,
        )

    async def _generate_independent_report(
        self,
        event: ExperimentEvent,
    ) -> None:
        result_value = event.payload.get("result_file")
        if not isinstance(result_value, str):
            raise ValueError("REPORT_READY event has no result_file")
        result_path = Path(result_value).resolve()
        results_root = Path(os.environ.get("RESULTS_ROOT", "/workspace/results")).resolve()
        if results_root not in result_path.parents:
            raise ValueError("report result path is outside RESULTS_ROOT")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if not isinstance(result, dict):
            raise ValueError("experiment result must be a JSON object")
        output_dir = result_path.parent / "report-service"
        artifacts = await asyncio.to_thread(
            generate_report,
            result,
            output_dir,
        )
        await self.registry.set_latest(
            "report-artifact",
            event.experiment_id,
            artifacts,
            ttl_s=86_400,
        )

    async def _heartbeat_loop(self) -> None:
        while True:
            mqtt_connected = bool(getattr(self.bus, "connected", True))
            heartbeat = self.factory.build(
                ServiceHeartbeat,
                simulation_time=0.0,
                ttl_s=15.0,
                service_role=self.role,
                instance_id=self.instance_id,
                status="healthy" if mqtt_connected else "degraded",
                dependencies={
                    "mqtt": "connected" if mqtt_connected else "reconnecting",
                    "redis": "connected",
                },
            )
            topic = (
                f"traffic/{self.environment}/edge/{self.instance_id}/heartbeat"
                if self.role == "edge-service"
                else f"traffic/{self.environment}/service/{self.role}/heartbeat"
            )
            try:
                await self.bus.publish(
                    topic,
                    heartbeat.model_dump_json().encode("utf-8"),
                    qos=1,
                    retain=True,
                )
                mqtt_connected = True
            except (OSError, RuntimeError, TimeoutError) as exc:
                mqtt_connected = False
                logger.warning(
                    "service_heartbeat_mqtt_unavailable",
                    role=self.role,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
            try:
                await self.registry.heartbeat(
                    self.role,
                    self.instance_id,
                    {
                        "status": ("healthy" if mqtt_connected else "degraded"),
                        "message_count": self.message_count,
                        "dependencies": {
                            "mqtt": ("connected" if mqtt_connected else "reconnecting"),
                            "redis": "connected",
                        },
                        "edge_modes": {
                            experiment_id: machine.mode.value
                            for experiment_id, machine in list(self._edge_machines.items())
                        },
                    },
                )
            except (OSError, RuntimeError, TimeoutError) as exc:
                logger.warning(
                    "service_heartbeat_redis_unavailable",
                    role=self.role,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
            await asyncio.sleep(5.0)


async def run_service_worker(role: str) -> None:
    """Build and serve one environment-configured independent role."""

    environment = os.environ.get("ENVIRONMENT", "development")
    worker = ServiceWorker(
        role,
        message_bus_from_environment(os.environ, seed=0),
        RuntimeRegistry(os.environ.get("REDIS_URL", "redis://localhost:6379/0")),
        environment=environment,
        instance_id=os.environ.get(
            "SERVICE_INSTANCE_ID",
            f"{role}-{uuid4().hex[:8]}",
        ),
    )
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(signum, worker.stop)
    await worker.run()


def _source_type(role: str) -> SourceType:
    return {
        "cloud-service": SourceType.CLOUD,
        "rsu-service": SourceType.RSU,
        "edge-service": SourceType.EDGE,
        "vehicle-agent": SourceType.VEHICLE,
        "report-service": SourceType.REPORT,
        "sumo-runner": SourceType.EXPERIMENT,
    }[role]
