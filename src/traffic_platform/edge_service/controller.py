"""Edge algorithm selection, safety validation, SUMO actuation and feedback."""

import time
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
        self.machine = EdgeDegradationMachine(degradation_config)
        self.safety = SafetyKernel()
        algorithm_names = (
            "fixed-time",
            "actuated-control",
            "max-pressure",
            "coordinated-max-pressure",
        )
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
            registry = builtin_registry()
            self.algorithms = {}
            for name in algorithm_names:
                algorithm = registry.create(name)
                algorithm.initialize(self.algorithm_config, topology)
                algorithm.reset(0)
                self.algorithms[name] = algorithm
        self.algorithm_timeout_count = 0
        self.algorithm_failure_count = 0
        self.last_strategy_by_intersection: dict[str, CloudStrategy] = {}

    def accept_cloud_strategy(self, strategy: CloudStrategy) -> bool:
        """Validate version/experiment/time and store one cloud target."""

        accepted = self.machine.accept_strategy(
            strategy,
            simulation_time=strategy.simulation_time,
            experiment_id=self.factory.experiment_id,
        )
        if accepted:
            self.last_strategy_by_intersection[
                strategy.target_intersection_id
            ] = strategy
        return accepted

    def control(
        self,
        state: IntersectionState,
    ) -> ExecutionFeedback | None:
        """Run one local decision, safety check and auditable SUMO command."""

        control_started = time.perf_counter()
        mode = self.machine.tick(state.simulation_time)
        strategy = self.last_strategy_by_intersection.get(state.intersection_id)
        if strategy is not None and not (
            strategy.valid_from <= state.simulation_time <= strategy.valid_until
        ):
            strategy = None
        algorithm_name = self._algorithm_for(mode, strategy is not None)
        algorithm = self.algorithms[algorithm_name]
        observation = ControlObservation(
            intersection=state,
            cloud_strategy=strategy if algorithm_name == "coordinated-max-pressure" else None,
            predicted_arrivals={
                lane.lane_id: lane.arrival_rate / 3600.0 for lane in state.lane_states
            },
        )
        try:
            decision = algorithm.decide(observation)
        except Exception as exc:
            if isinstance(exc, PlatformError) and exc.code == ErrorCode.ALGORITHM_TIMEOUT:
                self.algorithm_timeout_count += 1
            else:
                self.algorithm_failure_count += 1
            self.machine.tick(
                state.simulation_time,
                local_healthy=False,
            )
            decision = self.algorithms["fixed-time"].decide(observation)
            mode = EdgeMode.FIXED_TIME_SAFE
        valid_phases = {
            phase.phase_id
            for phase in self.topology.phases.get(state.intersection_id, [])
        }
        current_definition = next(
            (
                phase
                for phase in self.topology.phases.get(state.intersection_id, [])
                if phase.phase_id == state.current_phase_id
            ),
            None,
        )
        if (
            mode == EdgeMode.RECOVERY_SYNC
            and decision.requested_phase_id != state.current_phase_id
        ):
            decision = ControlDecision(
                status=DecisionStatus.HOLD,
                intersection_id=state.intersection_id,
                requested_phase_id=state.current_phase_id,
                action_type="hold_phase",
                requested_duration_s=None,
                scores=decision.scores,
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
                strategy_experiment_id=(
                    strategy.experiment_id if strategy is not None else None
                ),
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
                # Ending the current phase lets the loaded SUMO program traverse its
                # yellow/all-red phases; the edge never jumps directly to a green.
                self.adapter.set_phase_duration(state.intersection_id, 0.1)
                executed = {
                    "action_type": "terminate_for_safe_program_transition",
                    "target_phase_id": validated.requested_phase_id,
                }
            else:
                executed = {"action_type": validated.action_type}
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
