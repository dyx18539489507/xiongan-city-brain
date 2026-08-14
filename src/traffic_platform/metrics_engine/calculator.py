"""Deterministic metrics calculated only from observed simulation samples."""

from collections.abc import Callable
from dataclasses import dataclass, field
from statistics import fmean, median


@dataclass(frozen=True, slots=True)
class MetricSample:
    """One actual sampled network state."""

    simulation_time_s: float
    mean_speed_m_s: float
    total_queue_vehicles: int
    total_queue_m: float
    throughput_vehicles: int
    completed_trips: int
    waiting_time_s: float
    time_loss_s: float
    stop_count: int
    spillback_intersections: int
    congested_intersections: int = 0
    active_vehicle_count: int = 0
    fuel_mg: float = 0.0
    co2_mg: float = 0.0
    nox_mg: float = 0.0
    emergency_braking_count: int = 0
    acceleration_variance: float = 0.0
    bicycle_active_count: int = 0
    bicycle_completed_trips: int = 0
    bicycle_waiting_time_s: float = 0.0
    bicycle_queue_count: int = 0
    pedestrian_active_count: int = 0
    pedestrian_completed_trips: int = 0
    pedestrian_waiting_time_s: float = 0.0
    pedestrian_crossing_count: int = 0
    motor_motor_conflict_count: int = 0
    motor_bicycle_conflict_count: int = 0
    motor_pedestrian_conflict_count: int = 0
    bicycle_pedestrian_conflict_count: int = 0
    minimum_ttc_s: float | None = None
    minimum_pet_s: float | None = None


@dataclass(slots=True)
class MetricsAccumulator:
    """Accumulate samples and compute transparent aggregate metrics."""

    samples: list[MetricSample] = field(default_factory=list)
    unsafe_rejections: int = 0
    algorithm_timeouts: int = 0

    def add(self, sample: MetricSample) -> None:
        """Append one observed sample without fabricating missing fields."""

        if self.samples and sample.simulation_time_s < self.samples[-1].simulation_time_s:
            raise ValueError("metric sample time cannot move backwards")
        self.samples.append(sample)

    def summary(self) -> dict[str, float | int | str]:
        """Return actual aggregates or an explicit unrun status."""

        if not self.samples:
            return {"status": "尚未运行"}
        queues = [sample.total_queue_vehicles for sample in self.samples]
        spillback_samples = [
            sample for sample in self.samples if sample.spillback_intersections > 0
        ]
        step_s = self._typical_step_s()
        spillback_duration = self._duration_where(
            lambda sample: sample.spillback_intersections > 0,
            step_s,
        )
        gridlock_duration = self._duration_where(
            lambda sample: (
                sample.active_vehicle_count > 0
                and sample.total_queue_vehicles > 0
                and sample.mean_speed_m_s < 0.1
            ),
            step_s,
        )
        spillback_onsets = sum(
            1
            for index, sample in enumerate(self.samples)
            if sample.spillback_intersections > 0
            and (index == 0 or self.samples[index - 1].spillback_intersections == 0)
        )
        return {
            "status": "completed",
            "mean_speed": fmean(sample.mean_speed_m_s for sample in self.samples),
            "mean_speed_m_s": fmean(sample.mean_speed_m_s for sample in self.samples),
            "mean_waiting_time": fmean(sample.waiting_time_s for sample in self.samples),
            "mean_time_loss": fmean(sample.time_loss_s for sample in self.samples),
            "mean_queue_vehicles": fmean(queues),
            "mean_queue_meters": fmean(sample.total_queue_m for sample in self.samples),
            "max_queue": max(queues),
            "throughput": self.samples[-1].throughput_vehicles,
            "completed_trips": self.samples[-1].completed_trips,
            "stop_count": self.samples[-1].stop_count,
            "spillback_count": spillback_onsets,
            "spillback_sample_count": len(spillback_samples),
            "spillback_duration": spillback_duration,
            "congested_intersection_count": fmean(
                sample.congested_intersections for sample in self.samples
            ),
            "max_congested_intersection_count": max(
                sample.congested_intersections for sample in self.samples
            ),
            "congestion_propagation_time": self._propagation_time(),
            "network_recovery_time": self._network_recovery_time(),
            "gridlock_duration": gridlock_duration,
            "fuel_consumption_mg": sum(sample.fuel_mg for sample in self.samples),
            "co2_mg": sum(sample.co2_mg for sample in self.samples),
            "nox_mg": sum(sample.nox_mg for sample in self.samples),
            "emergency_braking_count": sum(
                sample.emergency_braking_count for sample in self.samples
            ),
            "acceleration_variance": fmean(sample.acceleration_variance for sample in self.samples),
            "bicycle_completed_trips": self.samples[-1].bicycle_completed_trips,
            "mean_bicycle_waiting_time_s": fmean(
                sample.bicycle_waiting_time_s for sample in self.samples
            ),
            "mean_bicycle_queue_count": fmean(
                sample.bicycle_queue_count for sample in self.samples
            ),
            "pedestrian_completed_trips": self.samples[-1].pedestrian_completed_trips,
            "mean_pedestrian_waiting_time_s": fmean(
                sample.pedestrian_waiting_time_s for sample in self.samples
            ),
            "pedestrian_crossing_count": self.samples[-1].pedestrian_crossing_count,
            "motor_motor_conflict_count": sum(
                sample.motor_motor_conflict_count for sample in self.samples
            ),
            "motor_bicycle_conflict_count": sum(
                sample.motor_bicycle_conflict_count for sample in self.samples
            ),
            "motor_pedestrian_conflict_count": sum(
                sample.motor_pedestrian_conflict_count for sample in self.samples
            ),
            "bicycle_pedestrian_conflict_count": sum(
                sample.bicycle_pedestrian_conflict_count for sample in self.samples
            ),
            "minimum_ttc_s": self._minimum_observed("minimum_ttc_s"),
            "minimum_pet_s": self._minimum_observed("minimum_pet_s"),
            "unsafe_command_rejection_count": self.unsafe_rejections,
            "algorithm_timeout_count": self.algorithm_timeouts,
            "performance_retention_under_delay": ("not_applicable_no_paired_baseline"),
            "performance_retention_under_packet_loss": ("not_applicable_no_paired_baseline"),
        }

    def _minimum_observed(self, field_name: str) -> float | str:
        values = [
            value for sample in self.samples if (value := getattr(sample, field_name)) is not None
        ]
        return min(values) if values else "not_observed"

    def _typical_step_s(self) -> float:
        differences = [
            right.simulation_time_s - left.simulation_time_s
            for left, right in zip(self.samples, self.samples[1:], strict=False)
            if right.simulation_time_s > left.simulation_time_s
        ]
        return median(differences) if differences else 0.0

    def _duration_where(
        self,
        predicate: Callable[[MetricSample], bool],
        default_step_s: float,
    ) -> float:
        duration = 0.0
        for index, sample in enumerate(self.samples):
            if not predicate(sample):
                continue
            if index + 1 < len(self.samples):
                duration += max(
                    0.0,
                    self.samples[index + 1].simulation_time_s - sample.simulation_time_s,
                )
            else:
                duration += default_step_s
        return duration

    def _propagation_time(self) -> float | str:
        first = next(
            (sample for sample in self.samples if sample.congested_intersections > 0),
            None,
        )
        if first is None:
            return "not_triggered"
        propagated = next(
            (
                sample
                for sample in self.samples
                if sample.simulation_time_s > first.simulation_time_s
                and sample.congested_intersections > first.congested_intersections
            ),
            None,
        )
        return (
            propagated.simulation_time_s - first.simulation_time_s
            if propagated is not None
            else "not_observed_within_run"
        )

    def _network_recovery_time(self) -> float | str:
        if not any(
            sample.congested_intersections > 0 or sample.spillback_intersections > 0
            for sample in self.samples
        ):
            return "not_triggered"
        peak_index = max(
            range(len(self.samples)),
            key=lambda index: (
                self.samples[index].congested_intersections,
                self.samples[index].spillback_intersections,
                self.samples[index].total_queue_vehicles,
            ),
        )
        baseline_count = max(1, min(10, len(self.samples) // 10 or 1))
        baseline_speed = fmean(sample.mean_speed_m_s for sample in self.samples[:baseline_count])
        threshold = baseline_speed * 0.8
        consecutive = 0
        for sample in self.samples[peak_index + 1 :]:
            recovered = (
                sample.congested_intersections == 0
                and sample.spillback_intersections == 0
                and sample.mean_speed_m_s >= threshold
            )
            consecutive = consecutive + 1 if recovered else 0
            if consecutive >= 3:
                return sample.simulation_time_s - self.samples[peak_index].simulation_time_s
        return "not_recovered_within_run"
