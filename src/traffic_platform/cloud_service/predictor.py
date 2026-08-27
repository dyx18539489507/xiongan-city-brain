"""Lightweight online graph-temporal forecasting for B3 predictive coordination."""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import pairwise

import numpy as np

from traffic_platform.contracts.models import (
    IntersectionState,
    LaneState,
    RegionalState,
    TrafficForecast,
)

MODEL_ID = "online-graph-rls-v1"


@dataclass(slots=True)
class _RecursiveLeastSquares:
    """Small deterministic online regressor suitable for cloud or edge CPU inference."""

    feature_count: int
    forgetting_factor: float = 0.985
    theta: np.ndarray = field(init=False)
    covariance: np.ndarray = field(init=False)
    samples: int = 0
    absolute_error_ema: float = 0.0

    def __post_init__(self) -> None:
        self.theta = np.zeros(self.feature_count, dtype=np.float64)
        self.covariance = np.eye(self.feature_count, dtype=np.float64) * 250.0

    def predict(self, features: np.ndarray) -> float:
        return float(max(0.0, self.theta @ features))

    def update(self, features: np.ndarray, target: float) -> None:
        prediction = float(self.theta @ features)
        projected = self.covariance @ features
        denominator = self.forgetting_factor + float(features @ projected)
        gain = projected / max(denominator, 1e-9)
        error = float(target) - prediction
        self.theta += gain * error
        self.covariance = (
            self.covariance - np.outer(gain, features) @ self.covariance
        ) / self.forgetting_factor
        self.samples += 1
        self.absolute_error_ema = (
            abs(error)
            if self.samples == 1
            else 0.85 * self.absolute_error_ema + 0.15 * abs(error)
        )


@dataclass(slots=True)
class _PhaseModel:
    arrival_model: _RecursiveLeastSquares = field(
        default_factory=lambda: _RecursiveLeastSquares(7)
    )
    queue_model: _RecursiveLeastSquares = field(
        default_factory=lambda: _RecursiveLeastSquares(7)
    )
    previous_features: np.ndarray | None = None


class LightweightGraphTemporalPredictor:
    """Learn per-phase temporal dynamics with neighboring-intersection risk features."""

    def __init__(
        self,
        *,
        corridor_intersection_ids: tuple[str, ...] = (),
        horizons_s: tuple[int, ...] = (30, 60, 120),
    ) -> None:
        self.horizons_s = horizons_s
        self._models: dict[tuple[str, str], _PhaseModel] = {}
        self._neighbors: dict[str, set[str]] = {}
        for left, right in pairwise(corridor_intersection_ids):
            self._neighbors.setdefault(left, set()).add(right)
            self._neighbors.setdefault(right, set()).add(left)

    def forecasts(self, regional: RegionalState) -> dict[str, list[TrafficForecast]]:
        """Update online models, then return bounded multi-horizon forecasts."""

        risk_by_id = {
            state.intersection_id: max(state.congestion_level, state.spillback_risk)
            for state in regional.intersection_states
        }
        result: dict[str, list[TrafficForecast]] = {}
        for state in regional.intersection_states:
            neighbor_ids = self._neighbors.get(state.intersection_id, set())
            neighbor_risk = (
                sum(risk_by_id.get(identifier, 0.0) for identifier in neighbor_ids)
                / len(neighbor_ids)
                if neighbor_ids
                else risk_by_id.get(state.intersection_id, 0.0)
            )
            result[state.intersection_id] = self._forecast_intersection(
                state,
                neighbor_risk,
            )
        return result

    def _forecast_intersection(
        self,
        state: IntersectionState,
        neighbor_risk: float,
    ) -> list[TrafficForecast]:
        phase_lanes: dict[str, list[LaneState]] = {}
        for lane in state.lane_states:
            if lane.movement:
                phase_lanes.setdefault(lane.movement, []).append(lane)

        phase_inputs: dict[str, tuple[np.ndarray, float, float, float]] = {}
        for phase_id, lanes in phase_lanes.items():
            queue = float(sum(lane.queue_vehicle_count for lane in lanes))
            arrival_s = float(sum(lane.arrival_rate for lane in lanes)) / 3600.0
            discharge_s = float(sum(lane.discharge_rate for lane in lanes)) / 3600.0
            occupancy = sum(lane.occupancy for lane in lanes) / len(lanes)
            downstream = sum(lane.downstream_occupancy for lane in lanes) / len(lanes)
            features = np.array(
                [
                    1.0,
                    min(queue / 20.0, 2.0),
                    min(arrival_s / 2.0, 2.0),
                    min(discharge_s / 2.0, 2.0),
                    occupancy,
                    downstream,
                    neighbor_risk,
                ],
                dtype=np.float64,
            )
            phase_inputs[phase_id] = (features, queue, arrival_s, discharge_s)

        predictions: dict[str, tuple[float, float, float, int]] = {}
        for phase_id, (features, queue, arrival_s, _discharge_s) in phase_inputs.items():
            model = self._models.setdefault(
                (state.intersection_id, phase_id),
                _PhaseModel(),
            )
            if model.previous_features is not None:
                model.arrival_model.update(model.previous_features, arrival_s)
                model.queue_model.update(model.previous_features, queue)
            learned_arrival = model.arrival_model.predict(features)
            learned_queue = model.queue_model.predict(features)
            samples = min(model.arrival_model.samples, model.queue_model.samples)
            if samples < 3:
                learned_arrival = arrival_s
                learned_queue = queue
            residual_scale = model.queue_model.absolute_error_ema / max(queue + 1.0, 1.0)
            confidence = min(0.95, 0.35 + 0.08 * samples) * max(
                0.35,
                1.0 - min(0.65, residual_scale),
            )
            predictions[phase_id] = (
                max(0.0, learned_arrival),
                max(0.0, learned_queue),
                confidence,
                samples,
            )
            model.previous_features = features

        forecasts: list[TrafficForecast] = []
        for horizon_s in self.horizons_s:
            phase_arrivals: dict[str, float] = {}
            phase_queues: dict[str, float] = {}
            confidences: list[float] = []
            sample_counts: list[int] = []
            for phase_id, (arrival_s, learned_queue, confidence, samples) in predictions.items():
                _, current_queue, _, discharge_s = phase_inputs[phase_id]
                phase_arrivals[phase_id] = round(arrival_s * horizon_s, 4)
                net_flow_queue = current_queue + (arrival_s - discharge_s) * horizon_s
                blended_queue = 0.55 * max(0.0, net_flow_queue) + 0.45 * learned_queue
                phase_queues[phase_id] = round(max(0.0, blended_queue), 4)
                confidences.append(confidence)
                sample_counts.append(samples)
            predicted_queue = sum(phase_queues.values())
            spillback = min(
                1.0,
                max(
                    state.spillback_risk,
                    neighbor_risk * 0.55 + min(1.0, predicted_queue / 60.0) * 0.45,
                ),
            )
            forecasts.append(
                TrafficForecast(
                    horizon_s=horizon_s,
                    phase_arrivals=phase_arrivals,
                    phase_queues=phase_queues,
                    spillback_risk=round(spillback, 4),
                    confidence=round(
                        sum(confidences) / len(confidences) if confidences else 0.0,
                        4,
                    ),
                    model_id=MODEL_ID,
                    sample_count=min(sample_counts, default=0),
                    generated_at_sim_time=state.simulation_time,
                )
            )
        return forecasts
