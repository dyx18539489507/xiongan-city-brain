"""B3 predictive policy-portfolio controller for cloud-edge coordination."""

from __future__ import annotations

from traffic_platform.algorithm_sdk.types import (
    ControlDecision,
    ControlObservation,
    DecisionStatus,
)
from traffic_platform.algorithms.max_pressure import (
    MaxPressureController,
    active_green_bounds,
)
from traffic_platform.contracts.models import CloudStrategy


class CoordinatedMaxPressureController(MaxPressureController):
    """Select among B0-B3 candidates, then apply predictive coordination."""

    name = "coordinated-max-pressure"
    version = "4.34.0"

    def __init__(self) -> None:
        super().__init__()
        self._pending_targets: dict[str, tuple[str, int]] = {}
        self._committed_targets: dict[str, str] = {}

    def reset(self, seed: int) -> None:
        super().reset(seed)
        self._pending_targets.clear()
        self._committed_targets.clear()

    def decide(self, state: ControlObservation) -> ControlDecision:
        """Apply cloud weights when valid and remain locally autonomous otherwise."""

        config, topology = self.require_initialized()
        intersection = state.intersection
        intersection_id = intersection.intersection_id
        current = intersection.current_phase_id
        phases = topology.phases.get(intersection_id, [])
        local_scores = self.score_phases(state)
        preserve_pressure_phase = config.predictive_pressure_retention_ratio >= 1.0
        min_green_s, max_green_s = active_green_bounds(
            intersection_id,
            current,
            config,
            topology,
        )
        pressure_best = (
            max(local_scores, key=lambda phase_id: local_scores[phase_id])
            if local_scores
            else current
        )
        pressure_target = (
            pressure_best
            if pressure_best != current and intersection.phase_elapsed >= min_green_s
            else current
        )
        strategy = state.cloud_strategy
        simulation_time = intersection.simulation_time
        cloud_valid = (
            strategy is not None
            and strategy.experiment_id == state.intersection.experiment_id
            and strategy.valid_from <= simulation_time <= strategy.valid_until
        )
        scores = dict(local_scores)
        mobility_scores: dict[str, float] = {}
        selected_forecast = None
        prediction_ready = False
        if cloud_valid and strategy is not None:
            selected_forecast = min(
                strategy.forecasts,
                key=lambda item: abs(item.horizon_s - config.prediction_horizon_s),
                default=None,
            )
            prediction_ready = bool(
                selected_forecast is not None
                and selected_forecast.confidence >= config.minimum_prediction_confidence
            )
            lane_by_id = {lane.lane_id: lane for lane in intersection.lane_states}
            scored_phases = (
                [phase for phase in phases if phase.phase_id == pressure_target]
                if preserve_pressure_phase
                else phases
            )
            for phase in scored_phases:
                related_lanes = [
                    lane_by_id[lane_id]
                    for lane_id in {movement.incoming_lane_id for movement in phase.movements}
                    if lane_id in lane_by_id
                ]
                approaching_vehicles = sum(
                    max(0, lane.vehicle_count - lane.queue_vehicle_count) for lane in related_lanes
                )
                observed_arrivals_s = sum(
                    state.predicted_arrivals.get(lane.lane_id, 0.0) for lane in related_lanes
                )
                downstream_occupancy = max(
                    (lane.downstream_occupancy for lane in related_lanes),
                    default=0.0,
                )
                release_capacity_factor = max(
                    0.0,
                    1.0 - config.capacity_weight * downstream_occupancy,
                )
                cloud_ratio = strategy.target_green_ratios.get(phase.phase_id, 0.0)
                release_gate = strategy.upstream_release_limit
                predicted_arrivals = (
                    selected_forecast.phase_arrivals.get(phase.phase_id, 0.0)
                    if prediction_ready and selected_forecast is not None
                    else 0.0
                )
                predicted_queue = (
                    selected_forecast.phase_queues.get(phase.phase_id, 0.0)
                    if prediction_ready and selected_forecast is not None
                    else 0.0
                )
                forecast_arrivals_s = predicted_arrivals / max(
                    float(selected_forecast.horizon_s) if selected_forecast is not None else 1.0,
                    1.0,
                )
                arrival_bonus = min(8.0, approaching_vehicles * 0.5 + observed_arrivals_s * 2.0)
                mobility_bonus = min(
                    8.0,
                    sum(
                        max(0, lane.vehicle_count - lane.queue_vehicle_count)
                        * min(
                            1.0,
                            lane.mean_speed
                            / max(topology.speed_limits_m_s.get(lane.lane_id, 1.0), 1.0),
                        )
                        for lane in related_lanes
                    ),
                )
                mobility_scores[phase.phase_id] = mobility_bonus
                forecast_arrival_bonus = min(6.0, forecast_arrivals_s * 2.0)
                queue_bonus = min(6.0, predicted_queue)
                spillback_penalty = (
                    max(selected_forecast.spillback_risk, downstream_occupancy) * 10.0
                    if prediction_ready and selected_forecast is not None
                    else downstream_occupancy * 10.0
                )
                scores[phase.phase_id] = (
                    local_scores.get(phase.phase_id, 0.0) * release_gate
                    + config.cloud_weight
                    * cloud_ratio
                    * min(8.0, approaching_vehicles + predicted_queue)
                    + config.arrival_weight * (arrival_bonus + mobility_bonus)
                    + config.mobility_preservation_weight * mobility_bonus
                    + config.prediction_weight * forecast_arrival_bonus
                    + config.predicted_queue_weight * queue_bonus
                ) * release_capacity_factor - config.predicted_spillback_weight * spillback_penalty
            progression_scores = self._progression_scores(state, strategy)
            for phase_id, bonus in progression_scores.items():
                if preserve_pressure_phase and phase_id != pressure_target:
                    continue
                scores[phase_id] = (
                    scores.get(phase_id, 0.0)
                    + config.cloud_weight * bonus * config.progression_tiebreak_weight
                )
        queues = {
            lane.lane_id: float(lane.queue_vehicle_count) for lane in intersection.lane_states
        }
        phase_demand = {
            phase.phase_id: sum(
                queues.get(movement.incoming_lane_id, 0.0) for movement in phase.movements
            )
            for phase in phases
        }
        if pressure_best != current and intersection.phase_elapsed >= min_green_s:
            baseline_action = "request_next_phase"
            baseline_target = pressure_best
            baseline_duration: float | None = min_green_s
            baseline_reason = "MAX_PRESSURE_SWITCH"
        elif (
            pressure_best == current
            and intersection.phase_elapsed < max_green_s
            and local_scores.get(current, 0.0) > 0.0
        ):
            baseline_action = "extend_green"
            baseline_target = current
            baseline_duration = config.extension_s
            baseline_reason = "MAX_PRESSURE_EXTEND"
        else:
            baseline_action = "hold_phase"
            baseline_target = current
            baseline_duration = None
            baseline_reason = "MIN_MAX_GREEN_OR_NO_POSITIVE_PRESSURE"
        current_demand = phase_demand.get(current, 0.0)
        actuated_best = (
            max(phase_demand, key=lambda phase_id: phase_demand[phase_id])
            if phase_demand
            else current
        )
        actuated_target = (
            current
            if current_demand > 0.0 and intersection.phase_elapsed < max_green_s
            else actuated_best
            if actuated_best != current and intersection.phase_elapsed >= min_green_s
            else current
        )
        candidate_phases = {
            "B0": current,
            "B1": actuated_target,
            "B2": baseline_target,
        }
        baseline_policy = "B2"
        baseline_phase = candidate_phases[baseline_policy]
        baseline_pressure = local_scores.get(baseline_phase, 0.0)
        pressure_floor = max(0.0, baseline_pressure) * config.predictive_pressure_retention_ratio
        eligible_phases = [
            phase.phase_id
            for phase in phases
            if local_scores.get(phase.phase_id, 0.0) >= pressure_floor
        ]
        unconstrained_phase = (
            max(
                scores,
                key=lambda phase_id: (
                    scores[phase_id],
                    mobility_scores.get(phase_id, 0.0),
                ),
            )
            if scores
            else current
        )
        forecast_challenges_pressure_guard = bool(
            preserve_pressure_phase
            and baseline_pressure > 0.0
            and prediction_ready
            and selected_forecast is not None
            and any(
                phase.phase_id not in eligible_phases
                and (
                    selected_forecast.phase_arrivals.get(phase.phase_id, 0.0) > 0.0
                    or selected_forecast.phase_queues.get(phase.phase_id, 0.0) > 0.0
                )
                for phase in phases
            )
        )
        pressure_guard_applied = (
            unconstrained_phase not in eligible_phases or forecast_challenges_pressure_guard
        )
        candidate_phases["B3"] = (
            baseline_phase
            if preserve_pressure_phase
            else max(
                eligible_phases,
                key=lambda phase_id: (
                    scores.get(phase_id, local_scores.get(phase_id, 0.0)),
                    mobility_scores.get(phase_id, 0.0),
                ),
            )
            if eligible_phases and mobility_scores
            else max(scores, key=lambda phase_id: scores[phase_id])
            if scores
            else current
        )
        candidate_policy_scores = {
            policy: local_scores.get(phase_id, 0.0) for policy, phase_id in candidate_phases.items()
        }
        candidate_policy_scores["B3"] = scores.get(
            candidate_phases["B3"],
            local_scores.get(candidate_phases["B3"], 0.0),
        )
        baseline_score = candidate_policy_scores[baseline_policy]
        predictive_score = candidate_policy_scores["B3"]
        expected_gain_ratio = (predictive_score - baseline_score) / max(
            abs(baseline_score),
            1.0,
        )
        predictive_pressure = local_scores.get(candidate_phases["B3"], 0.0)
        pressure_guard_passed = predictive_pressure >= (
            max(0.0, baseline_pressure) * config.predictive_pressure_retention_ratio
        )
        total_queue = sum(phase_demand.values())
        predictive_wins = (
            prediction_ready
            and total_queue >= config.low_demand_queue_threshold
            and expected_gain_ratio >= config.policy_gain_threshold
            and pressure_guard_passed
            and candidate_phases["B3"] != current
        )
        committed_target = self._committed_targets.get(intersection_id)
        if committed_target == current or (
            committed_target is not None and committed_target not in eligible_phases
        ):
            self._committed_targets.pop(intersection_id, None)
            committed_target = None
        if committed_target is None and predictive_wins:
            if preserve_pressure_phase or self._confirm_target(
                intersection_id,
                candidate_phases["B3"],
                required_steps=config.policy_switch_confirmation_steps,
            ):
                committed_target = candidate_phases["B3"]
                self._committed_targets[intersection_id] = committed_target
        elif committed_target is None:
            self._pending_targets.pop(intersection_id, None)
        selected_policy = (
            "B3" if predictive_wins or committed_target is not None else baseline_policy
        )
        best = committed_target or candidate_phases[selected_policy]
        selection_confidence = (
            selected_forecast.confidence
            if prediction_ready and selected_forecast is not None
            else 0.0
        )
        switch_confirmed = committed_target is not None
        if selected_policy == "B3":
            duration: float | None
            if best != current and intersection.phase_elapsed >= min_green_s and switch_confirmed:
                action = "request_next_phase"
                target = best
                duration = min_green_s
            elif best != current:
                action = baseline_action
                target = baseline_target
                duration = baseline_duration
            elif (
                best == current
                and intersection.phase_elapsed < max_green_s
                and local_scores.get(current, 0.0) > 0.0
            ):
                action = "extend_green"
                target = current
                duration = config.extension_s
            else:
                action = "hold_phase"
                target = current
                duration = None
        else:
            action = baseline_action
            target = baseline_target
            duration = baseline_duration
        self.observe(state)
        self.decisions += 1
        reasons = [
            "CLOUD_TARGET_APPLIED" if cloud_valid else "EDGE_AUTONOMOUS",
            f"POLICY_PORTFOLIO_SELECTED:{selected_policy}",
        ]
        if pressure_guard_applied or not pressure_guard_passed:
            reasons.append("CURRENT_PRESSURE_DOMINANCE_GUARD")
        elif selected_policy != "B3":
            reasons.append("PREDICTIVE_GAIN_BELOW_GATE")
        elif preserve_pressure_phase:
            reasons.append("PREDICTION_CONFIRMS_PRESSURE_PHASE")
        if selected_policy == "B3" and best != current and not switch_confirmed:
            reasons.append("SWITCH_AWAITING_CONFIRMATION")
        elif selected_policy == "B3" and best != current:
            reasons.append("SWITCH_TARGET_COMMITTED")
        if selected_policy != "B3":
            reasons.append(baseline_reason)
        if cloud_valid and strategy is not None and strategy.target_offsets:
            reasons.append("GREEN_WAVE_PHASE_ALIGNMENT")
        if cloud_valid:
            reasons.append(
                "PREDICTION_ENHANCED" if prediction_ready else "PREDICTION_FALLBACK_CURRENT_STATE"
            )
        if prediction_ready and selected_forecast is not None:
            reasons.extend(
                [
                    f"PREDICTION_MODEL:{selected_forecast.model_id}",
                    f"PREDICTION_HORIZON:{selected_forecast.horizon_s}s",
                ]
            )
        return ControlDecision(
            status=DecisionStatus.OK,
            intersection_id=state.intersection.intersection_id,
            requested_phase_id=target,
            action_type=action,
            requested_duration_s=duration,
            scores=scores,
            candidate_policy_scores=candidate_policy_scores,
            selected_policy=selected_policy,
            expected_gain_ratio=expected_gain_ratio,
            selection_confidence=selection_confidence,
            reason_codes=reasons,
            explanation=(
                "B3 evaluates B0 fixed, B1 actuated, B2 pressure and B3 predictive "
                "candidates, preserving the B2 pressure-optimal signal phase by default "
                "and applying prediction only when confidence and gain clear explicit gates."
            ),
        )

    def _confirm_target(
        self,
        intersection_id: str,
        target_phase_id: str,
        *,
        required_steps: int,
    ) -> bool:
        previous_target, previous_count = self._pending_targets.get(
            intersection_id,
            (target_phase_id, 0),
        )
        count = previous_count + 1 if previous_target == target_phase_id else 1
        self._pending_targets[intersection_id] = (target_phase_id, count)
        return count >= required_steps

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
