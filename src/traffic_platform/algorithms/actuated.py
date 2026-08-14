"""B1 local vehicle-presence actuated controller."""

from traffic_platform.algorithm_sdk.base import BaseTrafficController
from traffic_platform.algorithm_sdk.types import (
    ControlDecision,
    ControlObservation,
    DecisionStatus,
)


class ActuatedController(BaseTrafficController):
    """Extend a demanded green or request the most queued compatible phase."""

    name = "actuated-control"
    version = "1.0.0"

    def decide(self, state: ControlObservation) -> ControlDecision:
        """Use detected queue presence while respecting configured green bounds."""

        config, topology = self.require_initialized()
        self.observe(state)
        intersection = state.intersection
        phases = topology.phases.get(intersection.intersection_id, [])
        queues = {lane.lane_id: float(lane.queue_vehicle_count) for lane in intersection.lane_states}
        phase_demand = {
            phase.phase_id: sum(queues.get(m.incoming_lane_id, 0.0) for m in phase.movements)
            for phase in phases
        }
        current_demand = phase_demand.get(intersection.current_phase_id, 0.0)
        best_phase = (
            max(phase_demand, key=lambda phase_id: phase_demand[phase_id])
            if phase_demand
            else None
        )
        if current_demand > 0 and intersection.phase_elapsed < config.max_green_s:
            action = "extend_green"
            target = intersection.current_phase_id
            duration = config.extension_s
            reason = "CURRENT_GREEN_HAS_DEMAND"
        elif best_phase is not None and best_phase != intersection.current_phase_id:
            action = "request_next_phase"
            target = best_phase
            duration = config.min_green_s
            reason = "QUEUED_PHASE_REQUESTED"
        else:
            action = "hold_phase"
            target = intersection.current_phase_id
            duration = None
            reason = "NO_COMPETING_DEMAND"
        self.decisions += 1
        return ControlDecision(
            status=DecisionStatus.OK,
            intersection_id=intersection.intersection_id,
            requested_phase_id=target,
            action_type=action,
            requested_duration_s=duration,
            scores=phase_demand,
            reason_codes=[reason],
            explanation="B1 compares detected queue presence by compatible phase.",
        )
