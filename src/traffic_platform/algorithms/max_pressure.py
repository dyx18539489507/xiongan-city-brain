"""B2 downstream-aware maximum-pressure controller."""

from traffic_platform.algorithm_sdk.base import BaseTrafficController
from traffic_platform.algorithm_sdk.types import (
    ControlDecision,
    ControlObservation,
    DecisionStatus,
    PhaseDefinition,
)
from traffic_platform.contracts.models import LaneState


def phase_pressure(
    phase: PhaseDefinition,
    lanes: dict[str, LaneState],
    downstream_saturation_threshold: float,
) -> float:
    """Calculate queue differential, blocking saturated downstream movements."""

    pressure = 0.0
    for movement in phase.movements:
        incoming = lanes.get(movement.incoming_lane_id)
        outgoing = lanes.get(movement.outgoing_lane_id)
        if incoming is None:
            continue
        downstream_occupancy = max(
            outgoing.occupancy if outgoing is not None else 0.0,
            incoming.downstream_occupancy,
        )
        if downstream_occupancy >= downstream_saturation_threshold:
            continue
        downstream_queue = float(outgoing.queue_vehicle_count) if outgoing else 0.0
        capacity_factor = max(0.0, 1.0 - downstream_occupancy)
        pressure += max(0.0, incoming.queue_vehicle_count - downstream_queue) * capacity_factor
    return pressure


class MaxPressureController(BaseTrafficController):
    """Select the highest safe queue differential with a switch penalty."""

    name = "max-pressure"
    version = "1.0.0"

    def score_phases(self, state: ControlObservation) -> dict[str, float]:
        """Return interpretable phase scores for tests and coordinated reuse."""

        config, topology = self.require_initialized()
        intersection = state.intersection
        lanes = {lane.lane_id: lane for lane in intersection.lane_states}
        scores: dict[str, float] = {}
        for phase in topology.phases.get(intersection.intersection_id, []):
            score = phase_pressure(phase, lanes, config.downstream_saturation_threshold)
            if phase.phase_id != intersection.current_phase_id:
                score -= config.switch_penalty
            scores[phase.phase_id] = score
        return scores

    def decide(self, state: ControlObservation) -> ControlDecision:
        """Select the maximum-pressure phase without bypassing safety validation."""

        config, _ = self.require_initialized()
        self.observe(state)
        scores = self.score_phases(state)
        current = state.intersection.current_phase_id
        best = max(scores, key=lambda phase_id: scores[phase_id]) if scores else current
        if best != current and state.intersection.phase_elapsed >= config.min_green_s:
            action = "request_next_phase"
            duration = config.min_green_s
            reason = "MAX_PRESSURE_SWITCH"
        elif (
            best == current
            and state.intersection.phase_elapsed < config.max_green_s
            and scores.get(current, 0.0) > 0
        ):
            action = "extend_green"
            duration = config.extension_s
            reason = "MAX_PRESSURE_EXTEND"
        else:
            action = "hold_phase"
            duration = None
            reason = "MIN_MAX_GREEN_OR_NO_POSITIVE_PRESSURE"
        self.decisions += 1
        return ControlDecision(
            status=DecisionStatus.OK,
            intersection_id=state.intersection.intersection_id,
            requested_phase_id=best,
            action_type=action,
            requested_duration_s=duration,
            scores=scores,
            reason_codes=[reason],
            explanation="B2 scores incoming queue minus usable downstream capacity.",
        )
