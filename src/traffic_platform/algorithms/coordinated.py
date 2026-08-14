"""B3 cloud-target-weighted local maximum-pressure controller."""

from traffic_platform.algorithm_sdk.types import (
    ControlDecision,
    ControlObservation,
    DecisionStatus,
)
from traffic_platform.algorithms.max_pressure import MaxPressureController
from traffic_platform.contracts.models import CloudStrategy


class CoordinatedMaxPressureController(MaxPressureController):
    """Blend local pressure with valid regional release and capacity targets."""

    name = "coordinated-max-pressure"
    version = "1.0.0"

    def decide(self, state: ControlObservation) -> ControlDecision:
        """Apply cloud weights when valid and remain locally autonomous otherwise."""

        config, topology = self.require_initialized()
        local_scores = self.score_phases(state)
        strategy = state.cloud_strategy
        simulation_time = state.intersection.simulation_time
        cloud_valid = (
            strategy is not None
            and strategy.experiment_id == state.intersection.experiment_id
            and strategy.valid_from <= simulation_time <= strategy.valid_until
        )
        scores = dict(local_scores)
        if cloud_valid and strategy is not None:
            phases = topology.phases.get(state.intersection.intersection_id, [])
            for phase in phases:
                arrival = sum(
                    state.predicted_arrivals.get(m.incoming_lane_id, 0.0) for m in phase.movements
                )
                capacity = sum(
                    lane.downstream_available_capacity
                    for lane in state.intersection.lane_states
                    if any(m.incoming_lane_id == lane.lane_id for m in phase.movements)
                )
                cloud_ratio = strategy.target_green_ratios.get(phase.phase_id, 0.0)
                release_gate = strategy.upstream_release_limit
                scores[phase.phase_id] = (
                    local_scores.get(phase.phase_id, 0.0) * release_gate
                    + config.cloud_weight * cloud_ratio * 10.0
                    + config.arrival_weight * arrival
                    + config.capacity_weight * capacity
                )
            progression_scores = self._progression_scores(state, strategy)
            for phase_id, bonus in progression_scores.items():
                scores[phase_id] = scores.get(phase_id, 0.0) + config.cloud_weight * bonus
        current = state.intersection.current_phase_id
        best = max(scores, key=lambda phase_id: scores[phase_id]) if scores else current
        if best != current and state.intersection.phase_elapsed >= config.min_green_s:
            action = "request_next_phase"
            duration = config.min_green_s
        elif best == current and state.intersection.phase_elapsed < config.max_green_s:
            action = "extend_green"
            duration = config.extension_s
        else:
            action = "hold_phase"
            duration = None
        self.observe(state)
        self.decisions += 1
        reasons = ["CLOUD_TARGET_APPLIED" if cloud_valid else "EDGE_AUTONOMOUS"]
        if cloud_valid and strategy is not None and strategy.target_offsets:
            reasons.append("GREEN_WAVE_PHASE_ALIGNMENT")
        return ControlDecision(
            status=DecisionStatus.OK,
            intersection_id=state.intersection.intersection_id,
            requested_phase_id=best,
            action_type=action,
            requested_duration_s=duration,
            scores=scores,
            reason_codes=reasons,
            explanation=(
                "B3 blends local pressure, predicted arrivals, downstream capacity and "
                "a valid slow-timescale cloud release, cycle and progression target."
            ),
        )

    @staticmethod
    def _progression_scores(
        state: ControlObservation,
        strategy: CloudStrategy,
    ) -> dict[str, float]:
        """Reward phases whose planned green window contains the cycle position."""

        intersection_id = state.intersection.intersection_id
        if intersection_id not in strategy.target_offsets:
            return {}
        cycle_s = strategy.target_cycle_length
        position_s = state.intersection.simulation_time % cycle_s
        cursor_s = strategy.target_offsets[intersection_id] % cycle_s
        scores: dict[str, float] = {}
        for phase_id in strategy.recommended_phase_plan:
            green_s = strategy.target_green_ratios.get(phase_id, 0.0) * cycle_s
            if green_s <= 0:
                continue
            center_s = (cursor_s + green_s / 2.0) % cycle_s
            distance_s = abs(position_s - center_s)
            circular_distance_s = min(distance_s, cycle_s - distance_s)
            half_window_s = max(3.0, green_s / 2.0)
            scores[phase_id] = 10.0 * max(
                0.0,
                1.0 - circular_distance_s / half_window_s,
            )
            cursor_s = (cursor_s + green_s) % cycle_s
        return scores
