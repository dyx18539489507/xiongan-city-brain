"""Explainable downstream-aware Phase 1 cloud coordination strategy."""

import time
from dataclasses import dataclass
from itertools import pairwise
from typing import Any
from uuid import UUID

from traffic_platform.cloud_service.predictor import LightweightGraphTemporalPredictor
from traffic_platform.contracts.factory import MessageFactory
from traffic_platform.contracts.models import (
    CloudStrategy,
    IntersectionState,
    RegionalState,
    TrafficForecast,
)


@dataclass(frozen=True, slots=True)
class CoordinatorConfig:
    """Cloud strategy thresholds and slow-timescale targets."""

    downstream_occupancy_threshold: float = 0.82
    queue_risk_threshold: float = 0.65
    nominal_cycle_s: float = 90.0
    strategy_horizon_s: float = 15.0
    minimum_release_limit: float = 0.2
    minimum_cycle_s: float = 60.0
    maximum_cycle_s: float = 120.0
    progression_speed_m_s: float = 11.0
    offset_smoothing: float = 0.35
    guidance_activation_risk: float = 0.65
    minimum_speed_factor: float = 0.82
    speed_reduction_gain: float = 0.18
    corridor_intersection_ids: tuple[str, ...] = ()
    corridor_segment_distances_m: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if not 0 < self.downstream_occupancy_threshold <= 1:
            raise ValueError("downstream_occupancy_threshold must be a ratio")
        if not 0 < self.queue_risk_threshold <= 1:
            raise ValueError("queue_risk_threshold must be a ratio")
        if not 0 <= self.minimum_release_limit <= 1:
            raise ValueError("minimum_release_limit must be a ratio")
        if not 0 < self.minimum_cycle_s <= self.nominal_cycle_s <= self.maximum_cycle_s:
            raise ValueError("cycle bounds must contain nominal_cycle_s")
        if self.progression_speed_m_s <= 0:
            raise ValueError("progression_speed_m_s must be positive")
        if not 0 < self.offset_smoothing <= 1:
            raise ValueError("offset_smoothing must be a ratio")
        if not 0 <= self.guidance_activation_risk <= 1:
            raise ValueError("guidance_activation_risk must be a ratio")
        if not 0 < self.minimum_speed_factor <= 1:
            raise ValueError("minimum_speed_factor must be a ratio")
        if not 0 <= self.speed_reduction_gain <= 1:
            raise ValueError("speed_reduction_gain must be a ratio")
        if (
            self.corridor_intersection_ids
            and len(self.corridor_segment_distances_m) != len(self.corridor_intersection_ids) - 1
        ):
            raise ValueError("corridor distances must align with consecutive IDs")

    @classmethod
    def from_selection(cls, selection: dict[str, Any]) -> "CoordinatorConfig":
        """Build corridor geometry from the traceable scenario selection."""

        corridor = tuple(str(value) for value in selection.get("core_corridor", []))
        distance_by_pair = {
            frozenset((str(item["source"]), str(item["target"]))): float(item["road_distance_m"])
            for item in selection.get("topology_edges", [])
        }
        distances = tuple(
            distance_by_pair[frozenset((left, right))] for left, right in pairwise(corridor)
        )
        return cls(
            corridor_intersection_ids=corridor,
            corridor_segment_distances_m=distances,
        )


class RegionalCoordinator:
    """Generate regional targets without directly switching traffic lights."""

    def __init__(
        self,
        message_factory: MessageFactory,
        config: CoordinatorConfig | None = None,
    ) -> None:
        self.message_factory = message_factory
        self.config = config or CoordinatorConfig()
        self._version_by_intersection: dict[str, int] = {}
        self.acknowledged_strategy_ids: set[UUID] = set()
        self.last_decision_ms: float | None = None
        self._last_offset_by_intersection: dict[str, float] = {}
        self.predictor = LightweightGraphTemporalPredictor(
            corridor_intersection_ids=self.config.corridor_intersection_ids,
        )

    def strategies(self, state: RegionalState) -> list[CloudStrategy]:
        """Create one explainable, versioned target per intersection."""

        started = time.perf_counter()
        cycle = self._adaptive_cycle(state)
        offsets = self._dynamic_offsets(state, cycle)
        forecasts_by_intersection = self.predictor.forecasts(state)
        result = [
            self._strategy_for(
                intersection,
                state,
                cycle,
                offsets,
                forecasts_by_intersection.get(intersection.intersection_id, []),
            )
            for intersection in state.intersection_states
        ]
        self.last_decision_ms = (time.perf_counter() - started) * 1000
        return result

    def _strategy_for(
        self,
        intersection: IntersectionState,
        regional: RegionalState,
        target_cycle_s: float,
        offsets: dict[str, float],
        forecasts: list[TrafficForecast],
    ) -> CloudStrategy:
        downstream_occupancies = [lane.downstream_occupancy for lane in intersection.lane_states]
        max_downstream = max(downstream_occupancies, default=0.0)
        queue_risk = max(intersection.congestion_level, intersection.spillback_risk)
        propagation_risk = max(max_downstream, queue_risk)
        constrained = max_downstream >= self.config.downstream_occupancy_threshold
        release_limit = (
            max(
                self.config.minimum_release_limit,
                1.0 - max_downstream,
            )
            if constrained
            else 1.0
        )
        phases = sorted({lane.movement for lane in intersection.lane_states if lane.movement}) or [
            intersection.current_phase_id
        ]
        raw_weights: dict[str, float] = {}
        for phase in phases:
            related = [lane for lane in intersection.lane_states if lane.movement == phase]
            demand = sum(lane.queue_vehicle_count + lane.arrival_rate / 3600 for lane in related)
            usable = sum(
                lane.downstream_available_capacity * (1 - lane.downstream_occupancy)
                for lane in related
            )
            raw_weights[phase] = max(0.01, demand + usable)
        total = sum(raw_weights.values())
        green_budget = 0.82
        green_ratios = {
            phase: green_budget * weight / total for phase, weight in raw_weights.items()
        }
        priority = {
            lane.downstream_lane_id or lane.lane_id: max(
                0.0,
                lane.downstream_available_capacity * (1 - lane.downstream_occupancy),
            )
            for lane in intersection.lane_states
        }
        reasons = ["REGIONAL_STATE_EVALUATED"]
        if constrained:
            reasons.extend(["DOWNSTREAM_OCCUPANCY_HIGH", "UPSTREAM_RELEASE_SUPPRESSED"])
        if intersection.spillback_risk >= self.config.queue_risk_threshold:
            reasons.append("SPILLBACK_RISK_HIGH")
        if intersection.intersection_id in offsets:
            reasons.extend(["DYNAMIC_CYCLE_ADAPTED", "GREEN_WAVE_OFFSET_UPDATED"])
        prediction_ready = bool(
            forecasts
            and max(getattr(item, "sample_count", 0) for item in forecasts) >= 3
        )
        reasons.append(
            "PREDICTION_MODEL_READY" if prediction_ready else "PREDICTION_MODEL_WARMING_UP"
        )
        self._version_by_intersection[intersection.intersection_id] = (
            self._version_by_intersection.get(intersection.intersection_id, 0) + 1
        )
        target_speed_factor = (
            max(
                self.config.minimum_speed_factor,
                1.0 - self.config.speed_reduction_gain * propagation_risk,
            )
            if propagation_risk >= self.config.guidance_activation_risk
            else 1.0
        )
        return self.message_factory.build(
            CloudStrategy,
            simulation_time=regional.simulation_time,
            ttl_s=self.config.strategy_horizon_s,
            trace_id=regional.trace_id,
            correlation_id=str(regional.message_id),
            strategy_version=self._version_by_intersection[intersection.intersection_id],
            generated_at_sim_time=regional.simulation_time,
            valid_from=regional.simulation_time,
            valid_until=regional.simulation_time + self.config.strategy_horizon_s,
            target_intersection_id=intersection.intersection_id,
            target_cycle_length=target_cycle_s,
            target_green_ratios=green_ratios,
            target_offsets=(
                {intersection.intersection_id: offsets[intersection.intersection_id]}
                if intersection.intersection_id in offsets
                else {}
            ),
            upstream_release_limit=release_limit,
            downstream_priority=priority,
            recommended_phase_plan=phases,
            speed_guidance_parameters={
                "target_speed_factor": target_speed_factor,
                "horizon_s": 10.0,
                "activation_risk": self.config.guidance_activation_risk,
            },
            confidence=max(0.4, 1.0 - 0.3 * propagation_risk),
            forecasts=forecasts,
            prediction_status="ready" if prediction_ready else "warming_up",
            reason_codes=reasons,
            fallback_policy="edge_max_pressure",
        )

    def _adaptive_cycle(self, regional: RegionalState) -> float:
        if not regional.intersection_states:
            return self.config.nominal_cycle_s
        risk = sum(
            max(state.congestion_level, state.spillback_risk)
            for state in regional.intersection_states
        ) / len(regional.intersection_states)
        requested = self.config.nominal_cycle_s * (0.8 + 0.4 * risk)
        return round(
            min(self.config.maximum_cycle_s, max(self.config.minimum_cycle_s, requested)),
            1,
        )

    def _dynamic_offsets(
        self,
        regional: RegionalState,
        cycle_s: float,
    ) -> dict[str, float]:
        state_by_id = {state.intersection_id: state for state in regional.intersection_states}
        offsets: dict[str, float] = {}
        cumulative_distance = 0.0
        for index, intersection_id in enumerate(self.config.corridor_intersection_ids):
            if index > 0:
                cumulative_distance += self.config.corridor_segment_distances_m[index - 1]
            if intersection_id not in state_by_id:
                continue
            risk = state_by_id[intersection_id].spillback_risk
            raw = (
                cumulative_distance / self.config.progression_speed_m_s + risk * 0.12 * cycle_s
            ) % cycle_s
            previous = self._last_offset_by_intersection.get(intersection_id, raw)
            smoothed = (
                previous * (1.0 - self.config.offset_smoothing) + raw * self.config.offset_smoothing
            ) % cycle_s
            offsets[intersection_id] = round(smoothed, 1)
        self._last_offset_by_intersection.update(offsets)
        return offsets

    def acknowledge(self, strategy_id: UUID) -> None:
        """Reserved hook for persistent strategy execution acknowledgements."""

        self.acknowledged_strategy_ids.add(strategy_id)
