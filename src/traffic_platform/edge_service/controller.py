"""Edge algorithm selection, safety validation, SUMO actuation and feedback."""

import time
from dataclasses import dataclass
from uuid import uuid4

from traffic_platform.algorithm_sdk.base import TrafficControlAlgorithm
from traffic_platform.algorithm_sdk.isolation import IsolatedAlgorithmRunner
from traffic_platform.algorithm_sdk.types import (
    AlgorithmConfig,
    ControlDecision,
    ControlObservation,
    DecisionStatus,
    NetworkTopology,
)
from traffic_platform.algorithms import builtin_registry
from traffic_platform.common.errors import ErrorCode, PlatformError
from traffic_platform.contracts.factory import MessageFactory
from traffic_platform.contracts.models import (
    CloudStrategy,
    ExecutionFeedback,
    ExecutionStatus,
    IntersectionState,
)
from traffic_platform.edge_service.state_machine import (
    DegradationConfig,
    EdgeDegradationMachine,
    EdgeMode,
)
from traffic_platform.safety_kernel import SafetyContext, SafetyKernel, SafetyOutcome
from traffic_platform.sumo_adapter import TraciSumoAdapter
from traffic_platform.vehicle_agent.agent import (
    GlosaEffectivenessGate,
    GlosaMobilityRegimeClassifier,
)


@dataclass(slots=True)
class PendingSignalTransition:
    """A safety-cleared path from one green phase to the requested green phase."""

    source_phase_id: str
    target_phase_id: str
    clearance_path: list[str]
    stage_index: int = 0


class EdgeController:
    """Enforce safety > local invariants > cloud target > local objective."""

    def __init__(
        self,
        adapter: TraciSumoAdapter,
        factory: MessageFactory,
        topology: NetworkTopology,
        *,
        algorithm_config: AlgorithmConfig | None = None,
        degradation_config: DegradationConfig | None = None,
        control_algorithm: str = "coordinated-max-pressure",
        isolate_algorithms: bool = True,
    ) -> None:
        self.adapter = adapter
        self.factory = factory
        self.topology = topology
        self.algorithm_config = algorithm_config or AlgorithmConfig()
        if control_algorithm not in {
            "fixed-time",
            "actuated-control",
            "max-pressure",
            "coordinated-max-pressure",
        }:
            raise ValueError(f"unsupported edge control algorithm: {control_algorithm}")
        self.control_algorithm = control_algorithm
        self.isolate_algorithms = isolate_algorithms
        self.machine = EdgeDegradationMachine(degradation_config)
        self.safety = SafetyKernel()
        algorithm_names = {
            "fixed-time": (),
            "actuated-control": ("actuated-control",),
            "max-pressure": ("max-pressure",),
            "coordinated-max-pressure": (
                "max-pressure",
                "coordinated-max-pressure",
            ),
        }[control_algorithm]
        self.algorithm_registry = builtin_registry()
        self.safe_fallback = self.algorithm_registry.create("fixed-time")
        self.safe_fallback.initialize(self.algorithm_config, topology)
        self.safe_fallback.reset(0)
        if isolate_algorithms:
            self.algorithms: dict[str, TrafficControlAlgorithm] = {
                name: IsolatedAlgorithmRunner(
                    name,
                    self.algorithm_config,
                    topology,
                )
                for name in algorithm_names
            }
        else:
            self.algorithms = {}
            for name in algorithm_names:
                algorithm = self.algorithm_registry.create(name)
                algorithm.initialize(self.algorithm_config, topology)
                algorithm.reset(0)
                self.algorithms[name] = algorithm
        self.algorithm_timeout_count = 0
        self.algorithm_failure_count = 0
        self.algorithm_decision_latency_target_miss_count = 0
        self.algorithm_decision_elapsed_ms_max = 0.0
        self.algorithm_timeout_elapsed_ms_max = 0.0
        self.last_strategy_by_intersection: dict[str, CloudStrategy] = {}
        self.last_state_by_intersection: dict[str, IntersectionState] = {}
        self.pending_transitions: dict[str, PendingSignalTransition] = {}
        self.glosa_effectiveness_gate = GlosaEffectivenessGate(
            window_s=self.algorithm_config.glosa_effectiveness_window_s,
            cooldown_s=self.algorithm_config.glosa_effectiveness_cooldown_s,
            minimum_speed_loss_ratio=(self.algorithm_config.glosa_minimum_speed_loss_ratio),
            minimum_queue_reduction_ratio=(
                self.algorithm_config.glosa_minimum_queue_reduction_ratio
            ),
        )
        self.glosa_mobility_classifier = GlosaMobilityRegimeClassifier(
            window_s=self.algorithm_config.glosa_mobility_classification_window_s,
            high_mobility_speed_threshold_m_s=(
                self.algorithm_config.high_mobility_speed_threshold_m_s
            ),
        )

    def accept_cloud_strategy(self, strategy: CloudStrategy) -> bool:
        """Validate version/experiment/time and store one cloud target."""

        accepted = self.machine.accept_strategy(
            strategy,
            simulation_time=strategy.simulation_time,
            experiment_id=self.factory.experiment_id,
        )
        if accepted:
            self.last_strategy_by_intersection[strategy.target_intersection_id] = strategy
        return accepted

    def control(
        self,
        state: IntersectionState,
    ) -> ExecutionFeedback | None:
        """Run one local decision, safety check and auditable SUMO command."""

        self.last_state_by_intersection[state.intersection_id] = state
        control_started = time.perf_counter()
        mode = self.machine.tick(state.simulation_time)
        strategy = self.last_strategy_by_intersection.get(state.intersection_id)
        if strategy is not None and not (
            strategy.valid_from <= state.simulation_time <= strategy.valid_until
        ):
            strategy = None
        pending = self.pending_transitions.get(state.intersection_id)
        if pending is not None:
            return self._continue_signal_transition(
                state,
                pending,
                strategy,
                mode,
                control_started,
            )
        if state.current_phase_id in self.topology.clearance_phase_ids.get(
            state.intersection_id,
            set(),
        ):
            return self._transition_feedback(
                state,
                strategy,
                mode,
                control_started,
                requested_action={
                    "action_type": "hold_clearance",
                    "requested_phase_id": state.current_phase_id,
                    "reason_codes": ["NATIVE_CLEARANCE_ACTIVE"],
                },
                executed_action={"action_type": "hold_clearance"},
                status=ExecutionStatus.EXECUTED,
                rejection_reason=None,
                observed_effect={"clearance_preserved": "true"},
            )
        algorithm_name = self._algorithm_for(mode, strategy is not None)
        algorithm = (
            self.safe_fallback
            if algorithm_name == "fixed-time"
            else self.algorithms[algorithm_name]
        )
        observation = ControlObservation(
            intersection=state,
            cloud_strategy=strategy if algorithm_name == "coordinated-max-pressure" else None,
            predicted_arrivals={
                lane.lane_id: lane.arrival_rate / 3600.0 for lane in state.lane_states
            },
        )
        try:
            decision = (
                algorithm.decide(observation)
                if self.isolate_algorithms
                else self.algorithm_registry.decide_with_timeout(
                    algorithm,
                    observation,
                    self.algorithm_config.decision_timeout_ms,
                )
            )
            decision_elapsed_ms = getattr(algorithm, "last_decision_ms", None)
            if isinstance(decision_elapsed_ms, int | float):
                self.algorithm_decision_elapsed_ms_max = max(
                    self.algorithm_decision_elapsed_ms_max,
                    float(decision_elapsed_ms),
                )
                if decision_elapsed_ms > self.algorithm_config.decision_latency_target_ms:
                    self.algorithm_decision_latency_target_miss_count += 1
        except Exception as exc:
            if isinstance(exc, PlatformError) and exc.code == ErrorCode.ALGORITHM_TIMEOUT:
                self.algorithm_timeout_count += 1
                elapsed_ms = exc.details.get("elapsed_ms")
                if isinstance(elapsed_ms, int | float):
                    if elapsed_ms > self.algorithm_config.decision_latency_target_ms:
                        self.algorithm_decision_latency_target_miss_count += 1
                    self.algorithm_timeout_elapsed_ms_max = max(
                        self.algorithm_timeout_elapsed_ms_max,
                        float(elapsed_ms),
                    )
            else:
                self.algorithm_failure_count += 1
            self.machine.tick(
                state.simulation_time,
                local_healthy=False,
            )
            decision = self.safe_fallback.decide(observation)
            mode = EdgeMode.FIXED_TIME_SAFE
        valid_phases = set(
            self.topology.phase_order.get(
                state.intersection_id,
                [phase.phase_id for phase in self.topology.phases.get(state.intersection_id, [])],
            )
        )
        current_definition = next(
            (
                phase
                for phase in self.topology.phases.get(state.intersection_id, [])
                if phase.phase_id == state.current_phase_id
            ),
            None,
        )
        if mode == EdgeMode.RECOVERY_SYNC and decision.requested_phase_id != state.current_phase_id:
            decision = ControlDecision(
                status=DecisionStatus.HOLD,
                intersection_id=state.intersection_id,
                requested_phase_id=state.current_phase_id,
                action_type="hold_phase",
                requested_duration_s=None,
                scores=decision.scores,
                candidate_policy_scores=decision.candidate_policy_scores,
                selected_policy=decision.selected_policy,
                expected_gain_ratio=decision.expected_gain_ratio,
                selection_confidence=decision.selection_confidence,
                reason_codes=[*decision.reason_codes, "RECOVERY_NO_PHASE_JUMP"],
                explanation=(
                    f"{decision.explanation} Recovery synchronization holds the "
                    "current phase until stable."
                ),
            )
        safety = self.safety.validate(
            decision,
            SafetyContext(
                experiment_id=self.factory.experiment_id,
                strategy_experiment_id=(strategy.experiment_id if strategy is not None else None),
                simulation_time=state.simulation_time,
                action_expires_at_sim_time=state.simulation_time + 2.0,
                current_phase_id=state.current_phase_id,
                current_phase_elapsed_s=state.phase_elapsed,
                min_green_s=(
                    current_definition.min_green_s
                    if current_definition is not None
                    else self.algorithm_config.min_green_s
                ),
                max_green_s=(
                    current_definition.max_green_s
                    if current_definition is not None
                    else self.algorithm_config.max_green_s
                ),
                valid_phase_ids=valid_phases,
                conflicting_phase_pairs=self.topology.conflicting_phase_pairs.get(
                    state.intersection_id,
                    set(),
                ),
                pedestrian_clearance_ok=(
                    state.current_phase_id
                    not in self.topology.pedestrian_phase_ids.get(
                        state.intersection_id,
                        set(),
                    )
                    or state.phase_elapsed
                    >= (
                        current_definition.min_green_s
                        if current_definition is not None
                        else self.algorithm_config.min_green_s
                    )
                ),
                signal_healthy=state.phase_state != "",
                downstream_spillback=state.spillback_risk >= 0.98,
                emergency_requested_phase_id=state.emergency_priority_phase_id,
            ),
        )
        executed: dict[str, str | float | None] = {}
        status = ExecutionStatus.REJECTED
        rejection: str | None = None
        if safety.outcome == SafetyOutcome.REJECTED or safety.validated is None:
            rejection = ",".join(safety.reasons)
        else:
            validated = safety.validated
            if (
                validated.action_type == "extend_green"
                and validated.requested_duration_s is not None
            ):
                self.adapter.set_phase_duration(
                    state.intersection_id,
                    validated.requested_duration_s,
                )
                executed = {
                    "action_type": "extend_green",
                    "duration_s": validated.requested_duration_s,
                }
            elif validated.action_type == "request_next_phase":
                target = validated.requested_phase_id
                clearance_path = (
                    self.topology.clearance_paths.get(
                        state.intersection_id,
                        {},
                    )
                    .get(state.current_phase_id, {})
                    .get(target or "")
                )
                if target is None or clearance_path is None:
                    rejection = "NO_SAFE_CLEARANCE_PATH"
                elif not clearance_path:
                    self.adapter.set_traffic_light_phase(
                        state.intersection_id,
                        int(target),
                    )
                    executed = {
                        "action_type": "activate_requested_green",
                        "target_phase_id": target,
                    }
                else:
                    first_clearance = clearance_path[0]
                    self.adapter.set_traffic_light_phase(
                        state.intersection_id,
                        int(first_clearance),
                    )
                    self._hold_clearance_for_required_duration(
                        state.intersection_id,
                        first_clearance,
                    )
                    self.pending_transitions[state.intersection_id] = PendingSignalTransition(
                        source_phase_id=state.current_phase_id,
                        target_phase_id=target,
                        clearance_path=list(clearance_path),
                    )
                    executed = {
                        "action_type": "begin_safe_phase_transition",
                        "clearance_phase_id": first_clearance,
                        "target_phase_id": target,
                    }
            else:
                executed = {"action_type": validated.action_type}
            if rejection is None:
                status = (
                    ExecutionStatus.MODIFIED
                    if safety.outcome == SafetyOutcome.MODIFIED
                    else ExecutionStatus.EXECUTED
                )
        return self.factory.build(
            ExecutionFeedback,
            simulation_time=state.simulation_time,
            ttl_s=30.0,
            correlation_id=str(state.message_id),
            action_id=uuid4(),
            strategy_id=strategy.strategy_id if strategy is not None else None,
            intersection_id=state.intersection_id,
            requested_action=decision.model_dump(mode="json"),
            executed_action=executed,
            execution_status=status,
            rejection_reason=rejection,
            control_mode=mode.value,
            command_latency_ms=(time.perf_counter() - control_started) * 1000.0,
            cloud_round_trip_latency_ms=None,
            actual_start_time=state.simulation_time,
            actual_end_time=None,
            observed_effect={},
        )

    def close(self) -> None:
        """Close every algorithm plugin during graceful service shutdown."""

        for algorithm in self.algorithms.values():
            algorithm.close()
        self.safe_fallback.close()

    def algorithm_version(self, name: str) -> str:
        """Return the version of an algorithm available to this controller."""

        if name == "fixed-time":
            return self.safe_fallback.version
        return self.algorithms[name].version

    def _hold_clearance_for_required_duration(
        self,
        intersection_id: str,
        phase_id: str,
    ) -> None:
        required_s = self.topology.phase_durations_s.get(intersection_id, {}).get(
            phase_id,
            1.0,
        )
        # One extra simulation step gives the edge loop time to advance the
        # transition after the complete clearance duration has elapsed.
        self.adapter.set_phase_duration(intersection_id, required_s + 1.0)

    def _continue_signal_transition(
        self,
        state: IntersectionState,
        pending: PendingSignalTransition,
        strategy: CloudStrategy | None,
        mode: EdgeMode,
        control_started: float,
    ) -> ExecutionFeedback:
        if state.current_phase_id == pending.target_phase_id:
            self.pending_transitions.pop(state.intersection_id, None)
            return self._transition_feedback(
                state,
                strategy,
                mode,
                control_started,
                requested_action={
                    "action_type": "complete_safe_phase_transition",
                    "requested_phase_id": pending.target_phase_id,
                },
                executed_action={
                    "action_type": "target_phase_active",
                    "target_phase_id": pending.target_phase_id,
                },
                status=ExecutionStatus.EXECUTED,
                rejection_reason=None,
                observed_effect={"target_phase_observed": "true"},
            )

        expected = pending.clearance_path[pending.stage_index]
        if state.current_phase_id != expected:
            self.pending_transitions.pop(state.intersection_id, None)
            return self._transition_feedback(
                state,
                strategy,
                mode,
                control_started,
                requested_action={
                    "action_type": "continue_safe_phase_transition",
                    "requested_phase_id": pending.target_phase_id,
                },
                executed_action={"action_type": "transition_aborted"},
                status=ExecutionStatus.REJECTED,
                rejection_reason="TRANSITION_STATE_MISMATCH",
                observed_effect={
                    "expected_phase_id": expected,
                    "observed_phase_id": state.current_phase_id,
                },
            )

        required_s = self.topology.phase_durations_s.get(
            state.intersection_id,
            {},
        ).get(expected, 1.0)
        if state.phase_elapsed < required_s:
            return self._transition_feedback(
                state,
                strategy,
                mode,
                control_started,
                requested_action={
                    "action_type": "continue_safe_phase_transition",
                    "requested_phase_id": pending.target_phase_id,
                },
                executed_action={
                    "action_type": "hold_clearance",
                    "clearance_phase_id": expected,
                    "remaining_clearance_s": max(0.0, required_s - state.phase_elapsed),
                },
                status=ExecutionStatus.EXECUTED,
                rejection_reason=None,
                observed_effect={"clearance_elapsed_s": state.phase_elapsed},
            )

        pending.stage_index += 1
        if pending.stage_index < len(pending.clearance_path):
            next_phase = pending.clearance_path[pending.stage_index]
            action_type = "advance_clearance"
        else:
            next_phase = pending.target_phase_id
            action_type = "activate_requested_green"
        self.adapter.set_traffic_light_phase(state.intersection_id, int(next_phase))
        if next_phase != pending.target_phase_id:
            self._hold_clearance_for_required_duration(
                state.intersection_id,
                next_phase,
            )
        return self._transition_feedback(
            state,
            strategy,
            mode,
            control_started,
            requested_action={
                "action_type": "continue_safe_phase_transition",
                "requested_phase_id": pending.target_phase_id,
            },
            executed_action={
                "action_type": action_type,
                "phase_id": next_phase,
                "target_phase_id": pending.target_phase_id,
            },
            status=ExecutionStatus.EXECUTED,
            rejection_reason=None,
            observed_effect={"completed_clearance_phase_id": expected},
        )

    def _transition_feedback(
        self,
        state: IntersectionState,
        strategy: CloudStrategy | None,
        mode: EdgeMode,
        control_started: float,
        *,
        requested_action: dict[str, object],
        executed_action: dict[str, object],
        status: ExecutionStatus,
        rejection_reason: str | None,
        observed_effect: dict[str, object],
    ) -> ExecutionFeedback:
        return self.factory.build(
            ExecutionFeedback,
            simulation_time=state.simulation_time,
            ttl_s=30.0,
            correlation_id=str(state.message_id),
            action_id=uuid4(),
            strategy_id=strategy.strategy_id if strategy is not None else None,
            intersection_id=state.intersection_id,
            requested_action=requested_action,
            executed_action=executed_action,
            execution_status=status,
            rejection_reason=rejection_reason,
            control_mode=mode.value,
            command_latency_ms=(time.perf_counter() - control_started) * 1000.0,
            cloud_round_trip_latency_ms=None,
            actual_start_time=state.simulation_time,
            actual_end_time=None,
            observed_effect=observed_effect,
        )

    def _algorithm_for(self, mode: EdgeMode, has_strategy: bool) -> str:
        if self.control_algorithm == "fixed-time":
            return "fixed-time"
        if self.control_algorithm == "actuated-control":
            return "actuated-control"
        if self.control_algorithm == "max-pressure":
            return "max-pressure"
        if mode == EdgeMode.FIXED_TIME_SAFE:
            return "fixed-time"
        if mode in {EdgeMode.CLOUD_COORDINATED, EdgeMode.HOLD_LAST_VALID} and has_strategy:
            return "coordinated-max-pressure"
        return "max-pressure"
