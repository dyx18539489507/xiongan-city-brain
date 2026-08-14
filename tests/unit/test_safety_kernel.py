"""Mandatory signal and speed safety constraints."""

from traffic_platform.algorithm_sdk.types import ControlDecision, DecisionStatus
from traffic_platform.safety_kernel import (
    SafetyContext,
    SafetyKernel,
    SafetyOutcome,
)


def decision(
    *,
    action: str = "request_next_phase",
    phase: str | None = "P2",
    duration: float | None = 10.0,
    scores: dict[str, float] | None = None,
) -> ControlDecision:
    """Build one candidate decision."""

    return ControlDecision(
        status=DecisionStatus.OK,
        intersection_id="J1",
        requested_phase_id=phase,
        action_type=action,
        requested_duration_s=duration,
        scores=scores or {},
        reason_codes=["TEST"],
        explanation="test",
    )


def context(**overrides: object) -> SafetyContext:
    """Build one healthy signal safety context."""

    values: dict[str, object] = {
        "experiment_id": "experiment-test",
        "strategy_experiment_id": "experiment-test",
        "simulation_time": 10.0,
        "action_expires_at_sim_time": 20.0,
        "current_phase_id": "P1",
        "current_phase_elapsed_s": 15.0,
        "min_green_s": 10.0,
        "max_green_s": 60.0,
        "valid_phase_ids": {"P1", "P2"},
    }
    values.update(overrides)
    return SafetyContext.model_validate(values)


def test_rejects_switch_before_minimum_green() -> None:
    result = SafetyKernel().validate(
        decision(),
        context(current_phase_elapsed_s=5.0),
    )
    assert result.outcome == SafetyOutcome.REJECTED
    assert "MIN_GREEN_NOT_REACHED" in result.reasons


def test_clamps_extension_at_maximum_green() -> None:
    result = SafetyKernel().validate(
        decision(action="extend_green", phase="P1", duration=10.0),
        context(current_phase_elapsed_s=55.0),
    )
    assert result.outcome == SafetyOutcome.MODIFIED
    assert result.validated is not None
    assert result.validated.requested_duration_s == 5.0


def test_clamps_speed_limit_and_comfort_deceleration() -> None:
    result = SafetyKernel().validate(
        decision(
            action="apply_speed_guidance",
            phase=None,
            duration=None,
            scores={"recommended_speed_m_s": 1.0},
        ),
        context(
            road_speed_limit_m_s=13.0,
            current_vehicle_speed_m_s=15.0,
            guidance_horizon_s=2.0,
            max_comfort_deceleration_m_s2=3.0,
        ),
    )
    assert result.outcome == SafetyOutcome.MODIFIED
    assert result.validated is not None
    assert result.validated.scores["recommended_speed_m_s"] == 9.0

