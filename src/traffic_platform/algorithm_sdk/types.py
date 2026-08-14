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
    conflicting_phase_pairs: dict[str, set[tuple[str, str]]] = Field(
        default_factory=dict
    )
    pedestrian_phase_ids: dict[str, set[str]] = Field(default_factory=dict)
    clearance_phase_ids: dict[str, set[str]] = Field(default_factory=dict)


class AlgorithmConfig(SdkModel):
    """Validated generic configuration passed to a selected plugin."""

    decision_timeout_ms: float = Field(default=100.0, gt=0)
    min_green_s: float = Field(default=10.0, gt=0)
    max_green_s: float = Field(default=60.0, gt=0)
    extension_s: float = Field(default=5.0, gt=0)
    switch_penalty: float = Field(default=2.0, ge=0)
    downstream_saturation_threshold: float = Field(default=0.9, gt=0, le=1)
    cloud_weight: float = Field(default=0.35, ge=0)
    arrival_weight: float = Field(default=0.2, ge=0)
    capacity_weight: float = Field(default=0.25, ge=0)
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
