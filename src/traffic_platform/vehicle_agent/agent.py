"""Vehicle-side constrained speed guidance behavior."""

from collections import deque
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class GuidancePerformanceSample:
    """One network observation used to audit whether GLOSA is paying off."""

    simulation_time_s: float
    mean_speed_m_s: float
    queue_vehicles: int


@dataclass(slots=True)
class GlosaEffectivenessGate:
    """Authorize arrival alignment only after measured queue reduction."""

    window_s: float = 30.0
    cooldown_s: float = 20.0
    minimum_speed_loss_ratio: float = 0.01
    minimum_queue_reduction_ratio: float = 0.02
    samples: deque[GuidancePerformanceSample] = field(default_factory=deque)
    cooldown_until_s: float = 0.0
    active: bool = False
    reason: str = "WARMING_UP"
    speed_change_ratio: float | None = None
    queue_reduction_ratio: float | None = None

    def observe(
        self,
        *,
        simulation_time_s: float,
        mean_speed_m_s: float,
        queue_vehicles: int,
    ) -> bool:
        """Update the rolling evidence and return whether GLOSA may intervene."""

        self.samples.append(
            GuidancePerformanceSample(
                simulation_time_s=simulation_time_s,
                mean_speed_m_s=max(0.0, mean_speed_m_s),
                queue_vehicles=max(0, queue_vehicles),
            )
        )
        window_start_s = simulation_time_s - self.window_s
        while self.samples and self.samples[0].simulation_time_s < window_start_s:
            self.samples.popleft()

        if simulation_time_s < self.cooldown_until_s:
            self.active = False
            self.reason = "COOLDOWN_AFTER_NO_QUEUE_PAYOFF"
            return False

        observed_span_s = self.samples[-1].simulation_time_s - self.samples[0].simulation_time_s
        if len(self.samples) < 4 or observed_span_s < self.window_s * 0.8:
            self.active = False
            self.reason = "WARMING_UP"
            self.speed_change_ratio = None
            self.queue_reduction_ratio = None
            return False

        midpoint_s = self.samples[0].simulation_time_s + observed_span_s / 2.0
        earlier = [sample for sample in self.samples if sample.simulation_time_s <= midpoint_s]
        recent = [sample for sample in self.samples if sample.simulation_time_s > midpoint_s]
        if not earlier or not recent:
            self.active = False
            self.reason = "INSUFFICIENT_SPLIT_WINDOW"
            return False

        earlier_speed = sum(sample.mean_speed_m_s for sample in earlier) / len(earlier)
        recent_speed = sum(sample.mean_speed_m_s for sample in recent) / len(recent)
        earlier_queue = sum(sample.queue_vehicles for sample in earlier) / len(earlier)
        recent_queue = sum(sample.queue_vehicles for sample in recent) / len(recent)
        self.speed_change_ratio = (recent_speed - earlier_speed) / max(
            earlier_speed,
            0.1,
        )
        self.queue_reduction_ratio = (earlier_queue - recent_queue) / max(
            earlier_queue,
            1.0,
        )
        no_queue_payoff = (
            self.speed_change_ratio <= -self.minimum_speed_loss_ratio
            and self.queue_reduction_ratio < self.minimum_queue_reduction_ratio
        )
        if no_queue_payoff:
            self.cooldown_until_s = simulation_time_s + self.cooldown_s
            self.active = False
            self.reason = "SPEED_LOSS_WITHOUT_QUEUE_PAYOFF"
            return False

        if self.queue_reduction_ratio >= self.minimum_queue_reduction_ratio:
            self.active = True
            self.reason = "QUEUE_REDUCTION_JUSTIFIES_GUIDANCE"
            return True

        self.active = False
        self.reason = "QUEUE_REDUCTION_NOT_PROVEN"
        return False


@dataclass(slots=True)
class GlosaMobilityRegimeClassifier:
    """Classify and lock the traffic regime from an initial speed window."""

    window_s: float = 1.0
    high_mobility_speed_threshold_m_s: float = 4.65
    samples: list[GuidancePerformanceSample] = field(default_factory=list)
    regime: str = "learning"
    baseline_mean_speed_m_s: float | None = None

    def observe(self, *, simulation_time_s: float, mean_speed_m_s: float) -> str:
        """Return a stable regime after the initial observation window."""

        if self.regime != "learning":
            return self.regime
        self.samples.append(
            GuidancePerformanceSample(
                simulation_time_s=simulation_time_s,
                mean_speed_m_s=max(0.0, mean_speed_m_s),
                queue_vehicles=0,
            )
        )
        observed_span_s = self.samples[-1].simulation_time_s - self.samples[0].simulation_time_s
        if self.window_s > 1.0 and (
            len(self.samples) < 2 or observed_span_s < max(0.0, self.window_s - 1.0)
        ):
            return self.regime
        self.baseline_mean_speed_m_s = sum(sample.mean_speed_m_s for sample in self.samples) / len(
            self.samples
        )
        self.regime = (
            "high_mobility"
            if self.baseline_mean_speed_m_s >= self.high_mobility_speed_threshold_m_s
            else "congested"
        )
        self.samples.clear()
        return self.regime


@dataclass(frozen=True, slots=True)
class VehicleDynamics:
    """Vehicle and road limits used to constrain speed advice."""

    connected: bool
    current_speed_m_s: float
    speed_limit_m_s: float
    max_acceleration_m_s2: float = 2.0
    max_comfort_deceleration_m_s2: float = 3.0
    minimum_safe_speed_m_s: float = 0.0


@dataclass(frozen=True, slots=True)
class GuidanceResult:
    """Requested and executable guidance values with audit reasons."""

    requested_speed_m_s: float
    applied_speed_m_s: float | None
    executed: bool
    reasons: tuple[str, ...]


class VehicleGuidanceAgent:
    """Apply advice only to connected vehicles and respect dynamics."""

    def apply(
        self,
        requested_speed_m_s: float,
        dynamics: VehicleDynamics,
        *,
        horizon_s: float = 2.0,
        leader_safe_speed_m_s: float | None = None,
    ) -> GuidanceResult:
        """Clamp an advisory speed to road, acceleration and car-following limits."""

        if requested_speed_m_s < 0 or horizon_s <= 0:
            raise ValueError("speed must be non-negative and horizon positive")
        if not dynamics.connected:
            return GuidanceResult(
                requested_speed_m_s,
                None,
                False,
                ("NON_CONNECTED_VEHICLE_DEFAULT_SUMO",),
            )
        reasons: list[str] = []
        lower = max(
            dynamics.minimum_safe_speed_m_s,
            dynamics.current_speed_m_s - dynamics.max_comfort_deceleration_m_s2 * horizon_s,
        )
        upper = min(
            dynamics.speed_limit_m_s,
            dynamics.current_speed_m_s + dynamics.max_acceleration_m_s2 * horizon_s,
        )
        if leader_safe_speed_m_s is not None:
            upper = min(upper, leader_safe_speed_m_s)
            if requested_speed_m_s > leader_safe_speed_m_s:
                reasons.append("LEADER_SAFETY_LIMIT")
        applied = min(max(requested_speed_m_s, lower), upper)
        if requested_speed_m_s > dynamics.speed_limit_m_s:
            reasons.append("ROAD_SPEED_LIMIT")
        if requested_speed_m_s > upper:
            reasons.append("ACCELERATION_LIMIT")
        if requested_speed_m_s < lower:
            reasons.append("COMFORT_DECELERATION_LIMIT")
        if not reasons:
            reasons.append("GUIDANCE_ACCEPTED")
        return GuidanceResult(requested_speed_m_s, applied, True, tuple(dict.fromkeys(reasons)))
