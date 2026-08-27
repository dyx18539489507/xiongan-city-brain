"""Algorithm SDK configuration, topology, observation and decision types."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from traffic_platform.contracts.models import CloudStrategy, IntersectionState


class SdkModel(BaseModel):
    """Strict algorithm-SDK model."""

    model_config = ConfigDict(strict=True, extra="forbid", validate_assignment=True)


class PhaseMovement(SdkModel):
    """One incoming-to-outgoing movement served by a signal phase."""

    incoming_lane_id: str
    outgoing_lane_id: str
    saturation_flow_veh_h: float = Field(default=1800.0, gt=0)


class PhaseDefinition(SdkModel):
    """Signal phase definition independent of SUMO internal object types."""

    phase_id: str
    movements: list[PhaseMovement]
    min_green_s: float = Field(default=10.0, gt=0)
    max_green_s: float = Field(default=60.0, gt=0)
    yellow_s: float = Field(default=3.0, ge=0)
    all_red_s: float = Field(default=1.0, ge=0)


class NetworkTopology(SdkModel):
    """Algorithm-facing topology and per-intersection phase map."""

    intersection_ids: list[str]
    phases: dict[str, list[PhaseDefinition]]
    downstream_intersections: dict[str, list[str]]
    speed_limits_m_s: dict[str, float] = Field(default_factory=dict)
    conflicting_phase_pairs: dict[str, set[tuple[str, str]]] = Field(default_factory=dict)
    pedestrian_phase_ids: dict[str, set[str]] = Field(default_factory=dict)
    clearance_phase_ids: dict[str, set[str]] = Field(default_factory=dict)
    phase_order: dict[str, list[str]] = Field(default_factory=dict)
    phase_durations_s: dict[str, dict[str, float]] = Field(default_factory=dict)
    clearance_paths: dict[str, dict[str, dict[str, list[str]]]] = Field(default_factory=dict)


class AlgorithmConfig(SdkModel):
    """Validated generic configuration passed to a selected plugin."""

    decision_latency_target_ms: float = Field(default=100.0, gt=0)
    decision_timeout_ms: float = Field(default=250.0, gt=0)
    min_green_s: float = Field(default=10.0, gt=0)
    max_green_s: float = Field(default=60.0, gt=0)
    extension_s: float = Field(default=5.0, gt=0)
    switch_penalty: float = Field(default=2.0, ge=0)
    downstream_saturation_threshold: float = Field(default=0.9, gt=0, le=1)
    cloud_weight: float = Field(default=0.35, ge=0)
    arrival_weight: float = Field(default=0.2, ge=0)
    capacity_weight: float = Field(default=0.25, ge=0)
    prediction_weight: float = Field(default=0.45, ge=0)
    predicted_queue_weight: float = Field(default=0.35, ge=0)
    predicted_spillback_weight: float = Field(default=0.55, ge=0)
    progression_tiebreak_weight: float = Field(default=0.05, ge=0, le=0.25)
    mobility_preservation_weight: float = Field(default=3.0, ge=0, le=3)
    predictive_pressure_retention_ratio: float = Field(default=1.0, ge=0, le=1)
    prediction_horizon_s: int = Field(default=60, gt=0)
    minimum_prediction_confidence: float = Field(default=0.7, ge=0, le=1)
    policy_gain_threshold: float = Field(default=0.1, ge=0, le=1)
    policy_switch_confirmation_steps: int = Field(default=2, ge=1, le=10)
    low_demand_queue_threshold: float = Field(default=3.0, ge=0)
    minimum_actionable_speed_reduction_ratio: float = Field(
        default=0.05,
        ge=0,
        le=1,
    )
    minimum_guidance_acceleration_gain_m_s: float = Field(default=0.5, ge=0)
    minimum_moving_guidance_speed_m_s: float = Field(default=0.0, ge=0)
    maximum_queue_discharge_guidance_speed_m_s: float = Field(default=1.0, ge=0)
    queue_discharge_target_speed_m_s: float = Field(default=4.0, ge=0)
    high_mobility_maximum_queue_discharge_speed_m_s: float = Field(
        default=0.5,
        ge=0,
    )
    high_mobility_queue_discharge_target_speed_m_s: float = Field(default=2.0, ge=0)
    minimum_glosa_distance_m: float = Field(default=15.0, ge=0)
    maximum_glosa_distance_m: float = Field(default=120.0, gt=0)
    minimum_glosa_speed_m_s: float = Field(default=1.0, ge=0)
    maximum_glosa_time_to_green_s: float = Field(default=45.0, gt=0)
    high_mobility_speed_threshold_m_s: float = Field(default=4.65, gt=0)
    high_mobility_minimum_glosa_speed_m_s: float = Field(default=3.0, ge=0)
    glosa_mobility_classification_window_s: float = Field(default=1.0, gt=0)
    glosa_effectiveness_window_s: float = Field(default=30.0, gt=0)
    glosa_effectiveness_cooldown_s: float = Field(default=20.0, gt=0)
    glosa_minimum_speed_loss_ratio: float = Field(default=0.005, ge=0, le=1)
    glosa_minimum_queue_reduction_ratio: float = Field(default=0.05, ge=0, le=1)
    parameters: dict[str, Any] = Field(default_factory=dict)


class ControlObservation(SdkModel):
    """One local state snapshot plus an optional valid cloud target."""

    intersection: IntersectionState
    cloud_strategy: CloudStrategy | None = None
    predicted_arrivals: dict[str, float] = Field(default_factory=dict)


class DecisionStatus(StrEnum):
    """Algorithm output status."""

    OK = "OK"
    HOLD = "HOLD"
    MODEL_NOT_AVAILABLE = "MODEL_NOT_AVAILABLE"
    DEGRADED = "DEGRADED"


class ControlDecision(SdkModel):
    """Algorithm candidate decision before safety validation."""

    status: DecisionStatus
    intersection_id: str
    requested_phase_id: str | None
    action_type: str
    requested_duration_s: float | None = Field(default=None, gt=0)
    scores: dict[str, float] = Field(default_factory=dict)
    candidate_policy_scores: dict[str, float] = Field(default_factory=dict)
    selected_policy: str | None = None
    expected_gain_ratio: float | None = None
    selection_confidence: float | None = Field(default=None, ge=0, le=1)
    reason_codes: list[str] = Field(default_factory=list)
    explanation: str


class HealthStatus(StrEnum):
    """Plugin health state."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    CLOSED = "closed"


class AlgorithmHealth(SdkModel):
    """Current plugin health and decision statistics."""

    status: HealthStatus
    decisions: int = Field(ge=0)
    failures: int = Field(ge=0)
    last_decision_ms: float | None = Field(default=None, ge=0)
    detail: str
