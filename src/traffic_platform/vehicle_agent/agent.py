"""Vehicle-side constrained speed guidance behavior."""

from dataclasses import dataclass


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
            dynamics.current_speed_m_s
            - dynamics.max_comfort_deceleration_m_s2 * horizon_s,
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

