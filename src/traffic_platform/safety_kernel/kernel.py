"""Mandatory safety validation for every signal and speed action."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from traffic_platform.algorithm_sdk.types import ControlDecision
from traffic_platform.observability.metrics import UNSAFE_COMMANDS


class SafetyOutcome(StrEnum):
    """Possible safety-kernel decisions."""

    ACCEPTED = "accepted"
    MODIFIED = "modified"
    REJECTED = "rejected"


class SafetyContext(BaseModel):
    """Runtime facts unavailable to a pure traffic-control algorithm."""

    model_config = ConfigDict(strict=True, extra="forbid")

    experiment_id: str
    strategy_experiment_id: str | None = None
    simulation_time: float = Field(ge=0)
    action_expires_at_sim_time: float = Field(gt=0)
    current_phase_id: str
    current_phase_elapsed_s: float = Field(ge=0)
    min_green_s: float = Field(gt=0)
    max_green_s: float = Field(gt=0)
    valid_phase_ids: set[str]
    conflicting_phase_pairs: set[tuple[str, str]] = Field(default_factory=set)
    yellow_required: bool = True
    all_red_required: bool = True
    pedestrian_clearance_ok: bool = True
    signal_healthy: bool = True
    downstream_spillback: bool = False
    emergency_requested_phase_id: str | None = None
    road_speed_limit_m_s: float | None = Field(default=None, gt=0)
    current_vehicle_speed_m_s: float | None = Field(default=None, ge=0)
    max_comfort_deceleration_m_s2: float = Field(default=3.0, gt=0)
    guidance_horizon_s: float = Field(default=2.0, gt=0)


class SafetyResult(BaseModel):
    """Auditable safety result including original and modified decisions."""

    model_config = ConfigDict(strict=True, extra="forbid")

    outcome: SafetyOutcome
    original: ControlDecision
    validated: ControlDecision | None
    reasons: list[str]
    transition_requires_yellow: bool
    transition_requires_all_red: bool


class SafetyKernel:
    """Apply hard traffic-signal and vehicle-dynamics constraints."""

    def validate(self, decision: ControlDecision, context: SafetyContext) -> SafetyResult:
        """Return accepted, modified or rejected with stable reason codes."""

        reject: list[str] = []
        modify: list[str] = []
        target = decision.requested_phase_id
        switching = target is not None and target != context.current_phase_id

        if context.simulation_time >= context.action_expires_at_sim_time:
            reject.append("ACTION_EXPIRED")
        if (
            context.strategy_experiment_id is not None
            and context.strategy_experiment_id != context.experiment_id
        ):
            reject.append("EXPERIMENT_MISMATCH")
        if not context.signal_healthy:
            reject.append("SIGNAL_ABNORMAL")
        if not context.pedestrian_clearance_ok and switching:
            reject.append("PEDESTRIAN_CLEARANCE_ACTIVE")
        if target is not None and target not in context.valid_phase_ids:
            reject.append("UNKNOWN_PHASE")
        if switching and context.current_phase_elapsed_s < context.min_green_s:
            reject.append("MIN_GREEN_NOT_REACHED")
        if (
            switching
            and target is not None
            and (context.current_phase_id, target) in context.conflicting_phase_pairs
            and not context.yellow_required
        ):
            reject.append("CONFLICT_WITHOUT_YELLOW")
        if context.downstream_spillback and decision.action_type in {
            "extend_green",
            "request_next_phase",
        }:
            reject.append("DOWNSTREAM_SPILLBACK")
        if (
            context.emergency_requested_phase_id is not None
            and target not in {context.emergency_requested_phase_id, context.current_phase_id}
        ):
            reject.append("EMERGENCY_PRIORITY_CONFLICT")

        validated = decision.model_copy(deep=True)
        if (
            decision.action_type == "extend_green"
            and decision.requested_duration_s is not None
            and context.current_phase_elapsed_s + decision.requested_duration_s
            > context.max_green_s
        ):
            remaining = context.max_green_s - context.current_phase_elapsed_s
            if remaining <= 0:
                reject.append("MAX_GREEN_REACHED")
            else:
                validated.requested_duration_s = remaining
                modify.append("EXTENSION_CLAMPED_TO_MAX_GREEN")

        if decision.action_type == "apply_speed_guidance":
            requested = decision.scores.get("recommended_speed_m_s")
            if requested is None:
                reject.append("GUIDANCE_SPEED_MISSING")
            elif context.road_speed_limit_m_s is not None and requested > context.road_speed_limit_m_s:
                validated.scores["recommended_speed_m_s"] = context.road_speed_limit_m_s
                modify.append("GUIDANCE_CLAMPED_TO_SPEED_LIMIT")
            if (
                requested is not None
                and context.current_vehicle_speed_m_s is not None
                and requested
                < context.current_vehicle_speed_m_s
                - context.max_comfort_deceleration_m_s2 * context.guidance_horizon_s
            ):
                validated.scores["recommended_speed_m_s"] = max(
                    0.0,
                    context.current_vehicle_speed_m_s
                    - context.max_comfort_deceleration_m_s2 * context.guidance_horizon_s,
                )
                modify.append("GUIDANCE_CLAMPED_TO_COMFORT_DECELERATION")

        if reject:
            for reason in reject:
                UNSAFE_COMMANDS.labels(outcome="rejected", reason=reason).inc()
            return SafetyResult(
                outcome=SafetyOutcome.REJECTED,
                original=decision,
                validated=None,
                reasons=reject,
                transition_requires_yellow=switching and context.yellow_required,
                transition_requires_all_red=switching and context.all_red_required,
            )
        if modify:
            for reason in modify:
                UNSAFE_COMMANDS.labels(outcome="modified", reason=reason).inc()
            return SafetyResult(
                outcome=SafetyOutcome.MODIFIED,
                original=decision,
                validated=validated,
                reasons=modify,
                transition_requires_yellow=switching and context.yellow_required,
                transition_requires_all_red=switching and context.all_red_required,
            )
        return SafetyResult(
            outcome=SafetyOutcome.ACCEPTED,
            original=decision,
            validated=validated,
            reasons=[],
            transition_requires_yellow=switching and context.yellow_required,
            transition_requires_all_red=switching and context.all_red_required,
        )

