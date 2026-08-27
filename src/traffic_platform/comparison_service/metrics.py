"""Transparent rolling deltas for two synchronized SUMO truth streams."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from statistics import fmean
from typing import Any, Literal

from traffic_platform.realtime.models import DigitalTwinSourceFrame

Verdict = Literal["warming_up", "improved", "mixed", "stable", "worse", "invalid"]


@dataclass(frozen=True, slots=True)
class _MetricDefinition:
    key: str
    unit: str
    higher_better: bool
    aggregate: Literal["mean", "latest"] = "mean"
    absolute_threshold: float = 0.0
    relative_threshold: float = 0.05


_NETWORK_METRICS = (
    _MetricDefinition("mean_speed_m_s", "m/s", True, absolute_threshold=0.25),
    _MetricDefinition("total_queue_vehicles", "veh", False, absolute_threshold=1.0),
    _MetricDefinition("max_queue_vehicles", "veh", False, absolute_threshold=1.0),
    _MetricDefinition("waiting_time_s", "s", False, absolute_threshold=1.0),
    _MetricDefinition(
        "completed_trips",
        "trips",
        True,
        aggregate="latest",
        absolute_threshold=1.0,
        relative_threshold=0.02,
    ),
    _MetricDefinition("bicycle_waiting_time_s", "s", False, absolute_threshold=0.5),
    _MetricDefinition("bicycle_queue_count", "people", False, absolute_threshold=1.0),
    _MetricDefinition("pedestrian_waiting_time_s", "s", False, absolute_threshold=0.5),
    _MetricDefinition(
        "pedestrian_crossing_count",
        "crossings",
        True,
        aggregate="latest",
        absolute_threshold=1.0,
    ),
    _MetricDefinition("motor_bicycle_conflict_count", "conflicts", False, absolute_threshold=0.5),
    _MetricDefinition("motor_pedestrian_conflict_count", "conflicts", False, absolute_threshold=0.5),
    _MetricDefinition("bicycle_pedestrian_conflict_count", "conflicts", False, absolute_threshold=0.5),
)


@dataclass(frozen=True, slots=True)
class _PairedSample:
    simulation_time_s: float
    baseline_metrics: Mapping[str, object]
    candidate_metrics: Mapping[str, object]
    baseline_intersections: Sequence[Mapping[str, object]]
    candidate_intersections: Sequence[Mapping[str, object]]


@dataclass(slots=True)
class _ApproachAggregate:
    direction: str
    movement: str
    metrics: dict[str, tuple[float, int]]


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _mean(values: Sequence[float]) -> float | None:
    return fmean(values) if values else None


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


class LiveComparisonAccumulator:
    """Compare real observations from a synchronized baseline/candidate pair.

    The accumulator never fills missing values and never aligns different
    simulation times. Such a mismatch invalidates the pair explicitly.
    """

    def __init__(self, *, window_s: float = 60.0, synchronization_tolerance_s: float = 1e-6):
        if window_s <= 0:
            raise ValueError("window_s must be positive")
        self.window_s = float(window_s)
        self.synchronization_tolerance_s = float(synchronization_tolerance_s)
        self._samples: deque[_PairedSample] = deque()
        self._first_simulation_time_s: float | None = None
        self._invalid_reason: str | None = None
        self._network_pairs: dict[str, tuple[float, float, int]] = {}
        self._intersection_totals: dict[
            Literal["baseline", "candidate"],
            dict[str, dict[str, tuple[float, int]]],
        ] = {"baseline": {}, "candidate": {}}
        self._approach_totals: dict[
            Literal["baseline", "candidate"],
            dict[str, dict[str, _ApproachAggregate]],
        ] = {"baseline": {}, "candidate": {}}

    def invalidate(self, reason: str) -> None:
        self._invalid_reason = reason.strip() or "paired experiment invalidated"

    def add(self, baseline: DigitalTwinSourceFrame, candidate: DigitalTwinSourceFrame) -> None:
        baseline_time = float(baseline.simulation_time_s)
        candidate_time = float(candidate.simulation_time_s)
        if abs(baseline_time - candidate_time) > self.synchronization_tolerance_s:
            self.invalidate(
                "simulation time mismatch: "
                f"baseline={baseline_time:.6f}s candidate={candidate_time:.6f}s"
            )
            raise ValueError(self._invalid_reason)
        if self._samples and baseline_time < self._samples[-1].simulation_time_s:
            self.invalidate("paired simulation time moved backwards")
            raise ValueError(self._invalid_reason)
        if self._invalid_reason is not None:
            raise RuntimeError(f"paired comparison is invalid: {self._invalid_reason}")

        if self._first_simulation_time_s is None:
            self._first_simulation_time_s = baseline_time
        sample = _PairedSample(
            simulation_time_s=baseline_time,
            baseline_metrics=dict(baseline.metrics),
            candidate_metrics=dict(candidate.metrics),
            baseline_intersections=tuple(dict(item) for item in baseline.intersection_metrics),
            candidate_intersections=tuple(dict(item) for item in candidate.intersection_metrics),
        )
        self._samples.append(sample)
        self._update_aggregates(sample, 1)
        minimum_time = baseline_time - self.window_s
        while self._samples and self._samples[0].simulation_time_s < minimum_time:
            self._update_aggregates(self._samples.popleft(), -1)

    @staticmethod
    def _update_metric(
        bucket: dict[str, tuple[float, int]],
        key: str,
        value: float,
        direction: Literal[-1, 1],
    ) -> None:
        total, count = bucket.get(key, (0.0, 0))
        count += direction
        if count <= 0:
            bucket.pop(key, None)
            return
        bucket[key] = (total + direction * value, count)

    def _update_aggregates(
        self,
        sample: _PairedSample,
        direction: Literal[-1, 1],
    ) -> None:
        for definition in _NETWORK_METRICS:
            baseline_value = _number(sample.baseline_metrics.get(definition.key))
            candidate_value = _number(sample.candidate_metrics.get(definition.key))
            if baseline_value is None or candidate_value is None:
                continue
            baseline_total, candidate_total, count = self._network_pairs.get(
                definition.key,
                (0.0, 0.0, 0),
            )
            count += direction
            if count <= 0:
                self._network_pairs.pop(definition.key, None)
            else:
                self._network_pairs[definition.key] = (
                    baseline_total + direction * baseline_value,
                    candidate_total + direction * candidate_value,
                    count,
                )

        self._update_intersection_aggregates(
            "baseline",
            sample.baseline_intersections,
            direction,
        )
        self._update_intersection_aggregates(
            "candidate",
            sample.candidate_intersections,
            direction,
        )

    def _update_intersection_aggregates(
        self,
        role: Literal["baseline", "candidate"],
        intersections: Sequence[Mapping[str, object]],
        direction: Literal[-1, 1],
    ) -> None:
        intersection_totals = self._intersection_totals[role]
        approach_totals = self._approach_totals[role]
        for item in intersections:
            intersection_id = item.get("intersection_id")
            if not isinstance(intersection_id, str) or not intersection_id:
                continue
            intersection_bucket = intersection_totals.setdefault(intersection_id, {})
            for key in ("queue_vehicles", "mean_speed_m_s", "spillback_risk"):
                value = _number(item.get(key))
                if value is not None:
                    self._update_metric(intersection_bucket, key, value, direction)
            if not intersection_bucket:
                intersection_totals.pop(intersection_id, None)

            approaches = item.get("approaches")
            if not isinstance(approaches, list | tuple):
                continue
            approach_bucket = approach_totals.setdefault(intersection_id, {})
            for approach in approaches:
                if not isinstance(approach, Mapping):
                    continue
                lane_id = approach.get("lane_id")
                if not isinstance(lane_id, str) or not lane_id:
                    continue
                aggregate = approach_bucket.setdefault(
                    lane_id,
                    _ApproachAggregate(
                        direction=str(approach.get("direction", "")),
                        movement=str(approach.get("movement", "")),
                        metrics={},
                    ),
                )
                for key in (
                    "vehicle_count",
                    "queue_vehicles",
                    "mean_speed_m_s",
                    "occupancy",
                    "downstream_occupancy",
                ):
                    value = _number(approach.get(key))
                    if value is not None:
                        self._update_metric(aggregate.metrics, key, value, direction)
                if not aggregate.metrics:
                    approach_bucket.pop(lane_id, None)
            if not approach_bucket:
                approach_totals.pop(intersection_id, None)

    def summary(self) -> dict[str, Any]:
        if self._invalid_reason is not None:
            return {
                "valid": False,
                "reason": self._invalid_reason,
                "verdict": "invalid",
                "window_s": self.window_s,
                "paired_sample_count": len(self._samples),
                "network": {},
                "intersections": [],
            }
        if not self._samples:
            return {
                "valid": True,
                "reason": "waiting for synchronized SUMO samples",
                "verdict": "warming_up",
                "window_s": self.window_s,
                "warmup_remaining_s": self.window_s,
                "paired_sample_count": 0,
                "network": {},
                "intersections": [],
            }

        latest_time = self._samples[-1].simulation_time_s
        first_time = (
            latest_time
            if self._first_simulation_time_s is None
            else self._first_simulation_time_s
        )
        warmup_remaining = max(0.0, self.window_s - (latest_time - first_time))
        network, beneficial, harmful = self._network_summary()
        intersections, improved_count, worse_count = self._intersection_summary()
        warmed_up = warmup_remaining <= 0
        verdict: Verdict = "warming_up"
        if warmed_up:
            verdict = self._overall_verdict(
                beneficial=beneficial,
                harmful=harmful,
                improved_intersections=improved_count,
                worse_intersections=worse_count,
            )

        return {
            "valid": True,
            "reason": None if warmed_up else "建立对照基线",
            "verdict": verdict,
            "window_s": self.window_s,
            "warmup_remaining_s": round(warmup_remaining, 3),
            "paired_sample_count": len(self._samples),
            "simulation_time_s": latest_time,
            "network": network,
            "intersections": intersections,
            "counts": {
                "improved_intersections": improved_count,
                "stable_intersections": sum(
                    1 for item in intersections if item["verdict"] == "stable"
                ),
                "worse_intersections": worse_count,
            },
        }

    def _network_summary(self) -> tuple[dict[str, Any], int, int]:
        result: dict[str, Any] = {}
        beneficial = 0
        harmful = 0
        for definition in _NETWORK_METRICS:
            aggregate = self._network_pairs.get(definition.key)
            if aggregate is None:
                continue
            if definition.aggregate == "latest":
                latest_pair = next(
                    (
                        (baseline_value, candidate_value)
                        for sample in reversed(self._samples)
                        if (
                            baseline_value := _number(
                                sample.baseline_metrics.get(definition.key)
                            )
                        )
                        is not None
                        and (
                            candidate_value := _number(
                                sample.candidate_metrics.get(definition.key)
                            )
                        )
                        is not None
                    ),
                    None,
                )
                if latest_pair is None:
                    continue
                baseline_value, candidate_value = latest_pair
            else:
                baseline_total, candidate_total, count = aggregate
                baseline_value = baseline_total / count
                candidate_value = candidate_total / count
            delta = candidate_value - baseline_value
            benefit = delta if definition.higher_better else -delta
            threshold = max(
                definition.absolute_threshold,
                abs(baseline_value) * definition.relative_threshold,
            )
            trend = "stable"
            if benefit >= threshold:
                trend = "improved"
                beneficial += 1
            elif benefit <= -threshold:
                trend = "worse"
                harmful += 1
            benefit_percent = None
            if abs(baseline_value) > 1e-9:
                benefit_percent = benefit / abs(baseline_value) * 100.0
            result[definition.key] = {
                "baseline": _round(baseline_value),
                "candidate": _round(candidate_value),
                "delta": _round(delta),
                "benefit": _round(benefit),
                "benefit_percent": _round(benefit_percent),
                "unit": definition.unit,
                "higher_better": definition.higher_better,
                "trend": trend,
            }
        return result, beneficial, harmful

    def _intersection_summary(self) -> tuple[list[dict[str, Any]], int, int]:
        baseline = self._aggregate_intersections("baseline_intersections")
        candidate = self._aggregate_intersections("candidate_intersections")
        baseline_approaches = self._aggregate_approaches("baseline_intersections")
        candidate_approaches = self._aggregate_approaches("candidate_intersections")
        output: list[dict[str, Any]] = []
        improved_count = 0
        worse_count = 0
        for intersection_id in sorted(set(baseline) & set(candidate)):
            baseline_item = baseline[intersection_id]
            candidate_item = candidate[intersection_id]
            baseline_queue = baseline_item.get("queue_vehicles")
            candidate_queue = candidate_item.get("queue_vehicles")
            baseline_spillback = baseline_item.get("spillback_risk")
            candidate_spillback = candidate_item.get("spillback_risk")
            queue_delta = None
            queue_benefit = None
            threshold = 2.0
            if baseline_queue is not None and candidate_queue is not None:
                queue_delta = candidate_queue - baseline_queue
                queue_benefit = -queue_delta
                threshold = max(2.0, abs(baseline_queue) * 0.05)
            new_spillback = (
                baseline_spillback is not None
                and candidate_spillback is not None
                and baseline_spillback < 0.65 <= candidate_spillback
            )
            verdict = "stable"
            if new_spillback or (queue_benefit is not None and queue_benefit <= -threshold):
                verdict = "worse"
                worse_count += 1
            elif queue_benefit is not None and queue_benefit >= threshold:
                verdict = "improved"
                improved_count += 1

            if queue_delta is None:
                label = "≈ 数据不足"
            elif verdict == "improved":
                label = f"↓ 少排{abs(round(queue_delta))}辆"
            elif verdict == "worse":
                label = f"↑ 多排{abs(round(queue_delta))}辆"
            else:
                label = "≈ 基本持平"

            output.append(
                {
                    "intersection_id": intersection_id,
                    "verdict": verdict,
                    "label": label,
                    "baseline": {key: _round(value) for key, value in baseline_item.items()},
                    "candidate": {key: _round(value) for key, value in candidate_item.items()},
                    "delta": {
                        key: _round(candidate_item[key] - baseline_item[key])
                        for key in sorted(set(baseline_item) & set(candidate_item))
                    },
                    "approaches": self._approach_summary(
                        baseline_approaches.get(intersection_id, {}),
                        candidate_approaches.get(intersection_id, {}),
                    ),
                }
            )
        return output, improved_count, worse_count

    def _aggregate_intersections(
        self,
        attribute: Literal["baseline_intersections", "candidate_intersections"],
    ) -> dict[str, dict[str, float]]:
        role: Literal["baseline", "candidate"] = (
            "baseline" if attribute == "baseline_intersections" else "candidate"
        )
        return {
            intersection_id: {
                key: total / count
                for key, (total, count) in metrics.items()
                if count > 0
            }
            for intersection_id, metrics in self._intersection_totals[role].items()
        }

    def _aggregate_approaches(
        self,
        attribute: Literal["baseline_intersections", "candidate_intersections"],
    ) -> dict[str, dict[str, dict[str, Any]]]:
        role: Literal["baseline", "candidate"] = (
            "baseline" if attribute == "baseline_intersections" else "candidate"
        )
        return {
            intersection_id: {
                lane_id: {
                    "direction": aggregate.direction,
                    "movement": aggregate.movement,
                    **{
                        key: total / count
                        for key, (total, count) in aggregate.metrics.items()
                        if count > 0
                    },
                }
                for lane_id, aggregate in approaches.items()
            }
            for intersection_id, approaches in self._approach_totals[role].items()
        }

    @staticmethod
    def _approach_summary(
        baseline: Mapping[str, Mapping[str, Any]],
        candidate: Mapping[str, Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for lane_id in sorted(set(baseline) & set(candidate)):
            baseline_item = baseline[lane_id]
            candidate_item = candidate[lane_id]
            baseline_queue = _number(baseline_item.get("queue_vehicles"))
            candidate_queue = _number(candidate_item.get("queue_vehicles"))
            queue_delta = (
                candidate_queue - baseline_queue
                if baseline_queue is not None and candidate_queue is not None
                else None
            )
            threshold = max(1.0, abs(baseline_queue or 0.0) * 0.2)
            verdict = "stable"
            if queue_delta is not None and queue_delta <= -threshold:
                verdict = "improved"
            elif queue_delta is not None and queue_delta >= threshold:
                verdict = "worse"
            label = "≈ 持平"
            if verdict == "improved":
                label = f"↓ 少排{abs(round(queue_delta or 0))}辆"
            elif verdict == "worse":
                label = f"↑ 多排{abs(round(queue_delta or 0))}辆"
            numeric_keys = {
                key
                for key in set(baseline_item) & set(candidate_item)
                if _number(baseline_item.get(key)) is not None
                and _number(candidate_item.get(key)) is not None
            }
            output.append(
                {
                    "lane_id": lane_id,
                    "direction": candidate_item.get("direction", ""),
                    "movement": candidate_item.get("movement", ""),
                    "verdict": verdict,
                    "label": label,
                    "baseline": {
                        key: _round(_number(value))
                        for key, value in baseline_item.items()
                        if _number(value) is not None
                    },
                    "candidate": {
                        key: _round(_number(value))
                        for key, value in candidate_item.items()
                        if _number(value) is not None
                    },
                    "delta": {
                        key: _round(
                            float(candidate_item[key]) - float(baseline_item[key])
                        )
                        for key in sorted(numeric_keys)
                    },
                }
            )
        return output

    @staticmethod
    def _overall_verdict(
        *,
        beneficial: int,
        harmful: int,
        improved_intersections: int,
        worse_intersections: int,
    ) -> Verdict:
        has_benefit = beneficial > 0 or improved_intersections > 0
        has_harm = harmful > 0 or worse_intersections > 0
        if has_benefit and has_harm:
            return "mixed"
        if has_benefit:
            return "improved"
        if has_harm:
            return "worse"
        return "stable"
