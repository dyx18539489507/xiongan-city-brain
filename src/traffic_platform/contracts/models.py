"""Strict, versioned SI-unit data contracts shared by every service."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from traffic_platform.common.errors import ErrorCode, PlatformError
from traffic_platform.common.time import expires_after, utc_now


class SourceType(StrEnum):
    """Origin service categories used in every message envelope."""

    CLOUD = "cloud"
    EDGE = "edge"
    VEHICLE = "vehicle"
    EXPERIMENT = "experiment"
    REPORT = "report"
    SYSTEM = "system"
    RSU = "rsu"


class StrictModel(BaseModel):
    """Base class rejecting implicit type coercion and unknown fields."""

    model_config = ConfigDict(strict=True, extra="forbid", validate_assignment=True)


class TrafficMessage(StrictModel):
    """Common envelope required for all exchanged traffic messages."""

    schema_version: str = Field(default="1.0", pattern=r"^\d+\.\d+$")
    message_id: UUID = Field(default_factory=uuid4)
    trace_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_type: SourceType
    timestamp_utc: datetime = Field(default_factory=utc_now)
    simulation_time: float = Field(ge=0)
    sequence_number: int = Field(ge=0)
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime = Field(default_factory=lambda: expires_after(30))
    correlation_id: str = Field(min_length=1)
    environment: str = Field(default="development", min_length=1)
    scenario_id: str = Field(min_length=1)
    experiment_id: str = Field(min_length=1)

    @field_validator("timestamp_utc", "created_at", "expires_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        """Reject ambiguous local datetimes and normalize timestamps to UTC."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_lifetime(self) -> Self:
        """Ensure an envelope cannot expire before it was created."""

        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be later than created_at")
        return self

    def ensure_not_expired(self, at: datetime | None = None) -> None:
        """Raise a stable platform error when this message is no longer valid."""

        checked_at = (at or utc_now()).astimezone(UTC)
        if self.expires_at <= checked_at:
            raise PlatformError(
                ErrorCode.MESSAGE_EXPIRED,
                f"message {self.message_id} expired at {self.expires_at.isoformat()}",
            )


class PositionXY(StrictModel):
    """Cartesian SUMO position in metres."""

    x: float
    y: float


class EmissionEstimate(StrictModel):
    """Per-step emission estimates emitted by SUMO."""

    co2_mg_s: float = Field(ge=0)
    nox_mg_s: float = Field(ge=0)


class ServiceHeartbeat(TrafficMessage):
    """Liveness and dependency status emitted by one deployable service."""

    service_role: str
    instance_id: str
    status: str
    dependencies: dict[str, str] = Field(default_factory=dict)


class CloudCommand(TrafficMessage):
    """Low-frequency cloud management command for one edge service."""

    edge_id: str
    command: str
    parameters: dict[str, float | str | bool] = Field(default_factory=dict)


class ExperimentEvent(TrafficMessage):
    """Durable experiment lifecycle, fault, safety or disturbance event."""

    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)


class MetricSnapshot(TrafficMessage):
    """Sampled metric snapshot for reporting and live visualization."""

    metrics: dict[str, float | int | str | bool]


class SpeedGuidance(TrafficMessage):
    """Cloud/edge recommended speed for one connected vehicle."""

    vehicle_id: str
    recommended_speed_m_s: float = Field(ge=0)
    speed_limit_m_s: float = Field(gt=0)
    valid_until_simulation_time: float = Field(gt=0)
    reason_codes: list[str] = Field(default_factory=list)


class VehicleGuidanceCommand(TrafficMessage):
    """Vehicle-agent validated speed command consumed by the SUMO owner."""

    vehicle_id: str
    requested_speed_m_s: float = Field(ge=0)
    applied_speed_m_s: float | None = Field(default=None, ge=0)
    executed: bool
    validation_status: str
    validation_reasons: list[str] = Field(default_factory=list)


class VehicleState(TrafficMessage):
    """High-frequency state for one simulated road vehicle."""

    vehicle_id: str
    vehicle_type: str
    connected: bool
    road_id: str
    lane_id: str
    position_xy: PositionXY
    lane_position: float = Field(ge=0)
    speed: float = Field(ge=0)
    acceleration: float
    heading: float = Field(ge=0, lt=360)
    route_id: str
    next_intersection_id: str | None
    distance_to_stop_line: float = Field(ge=0)
    turn_direction: str
    waiting_time: float = Field(ge=0)
    stop_count: int = Field(ge=0)
    emission_estimate: EmissionEstimate
    fuel_consumption_estimate: float = Field(ge=0)


class BicycleState(TrafficMessage):
    """Lane-level state for one bicycle or electric bicycle."""

    bicycle_id: str
    bicycle_type: str
    electric: bool
    road_id: str
    lane_id: str
    position_xy: PositionXY
    lane_position_m: float = Field(ge=0)
    speed_m_s: float = Field(ge=0)
    acceleration_m_s2: float
    waiting_time_s: float = Field(ge=0)
    next_intersection_id: str | None = None
    turn_direction: str
    in_bicycle_lane: bool
    conflict_risk: float = Field(ge=0, le=1)


class PedestrianState(TrafficMessage):
    """State for one simulated pedestrian with a real walking route."""

    pedestrian_id: str
    pedestrian_type: str
    position_xy: PositionXY
    road_id: str
    lane_id: str
    speed_m_s: float = Field(ge=0)
    waiting_time_s: float = Field(ge=0)
    walking_stage_index: int = Field(ge=0)
    crossing_id: str | None = None
    waiting_area_id: str | None = None
    signal_state: str | None = None
    conflict_risk: float = Field(ge=0, le=1)


class SafetyConflictEvent(TrafficMessage):
    """Observed surrogate-safety conflict; never populated by random data."""

    conflict_id: str
    intersection_id: str | None = None
    participant_a_id: str
    participant_a_type: str
    participant_b_id: str
    participant_b_type: str
    conflict_type: str
    position_xy: PositionXY
    ttc_s: float | None = Field(default=None, ge=0)
    pet_s: float | None = Field(default=None, ge=0)
    minimum_distance_m: float = Field(ge=0)
    relative_speed_m_s: float = Field(ge=0)
    severity: str
    observed: bool = True


class LaneState(TrafficMessage):
    """Aggregated one-second lane state."""

    lane_id: str
    intersection_id: str
    direction: str
    movement: str
    vehicle_count: int = Field(ge=0)
    connected_vehicle_count: int = Field(ge=0)
    queue_vehicle_count: int = Field(ge=0)
    queue_length_m: float = Field(ge=0)
    mean_speed: float = Field(ge=0)
    occupancy: float = Field(ge=0, le=1)
    arrival_rate: float = Field(ge=0)
    discharge_rate: float = Field(ge=0)
    downstream_lane_id: str | None
    downstream_occupancy: float = Field(ge=0, le=1)
    downstream_available_capacity: float = Field(ge=0)
    bicycle_count: int = Field(default=0, ge=0)
    electric_bicycle_count: int = Field(default=0, ge=0)
    bicycle_queue_count: int = Field(default=0, ge=0)
    bicycle_queue_length_m: float = Field(default=0.0, ge=0)
    pedestrian_count: int = Field(default=0, ge=0)
    pedestrian_waiting_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def connected_count_not_above_total(self) -> Self:
        """Keep connected and queued counts bounded by the detected total."""

        if self.connected_vehicle_count > self.vehicle_count:
            raise ValueError("connected_vehicle_count cannot exceed vehicle_count")
        if self.queue_vehicle_count > self.vehicle_count:
            raise ValueError("queue_vehicle_count cannot exceed vehicle_count")
        return self


class IntersectionState(TrafficMessage):
    """Signal, lane and congestion state of one managed intersection."""

    intersection_id: str
    edge_id: str
    current_phase_id: str
    phase_state: str
    phase_elapsed: float = Field(ge=0)
    phase_remaining: float = Field(ge=0)
    cycle_elapsed: float = Field(ge=0)
    lane_states: list[LaneState]
    total_queue: int = Field(ge=0)
    mean_speed: float = Field(ge=0)
    throughput: float = Field(ge=0)
    congestion_level: float = Field(ge=0, le=1)
    spillback_risk: float = Field(ge=0, le=1)
    incident_state: str
    emergency_priority_phase_id: str | None = None
    communication_state: str
    local_control_mode: str
    bicycle_queue_count: int = Field(default=0, ge=0)
    pedestrian_waiting_count: int = Field(default=0, ge=0)
    crossing_pedestrian_count: int = Field(default=0, ge=0)
    active_conflict_count: int = Field(default=0, ge=0)


class RegionalState(TrafficMessage):
    """Regional aggregation consumed by the cloud coordinator."""

    intersection_states: list[IntersectionState]
    network_mean_speed: float = Field(ge=0)
    total_queue: int = Field(ge=0)
    congested_intersections: list[str]
    spillback_edges: list[str]
    risk_levels: dict[str, float]
    active_disturbances: list[str]

    @field_validator("risk_levels")
    @classmethod
    def risk_values_are_ratios(cls, value: dict[str, float]) -> dict[str, float]:
        """Validate all named regional risks as zero-to-one ratios."""

        if any(risk < 0 or risk > 1 for risk in value.values()):
            raise ValueError("all risk levels must be between 0 and 1")
        return value


class CloudStrategy(TrafficMessage):
    """Slow-timescale regional target sent from cloud to an edge controller."""

    strategy_id: UUID = Field(default_factory=uuid4)
    strategy_version: int = Field(ge=1)
    generated_at_sim_time: float = Field(ge=0)
    valid_from: float = Field(ge=0)
    valid_until: float = Field(gt=0)
    target_intersection_id: str
    target_cycle_length: float = Field(gt=0)
    target_green_ratios: dict[str, float]
    target_offsets: dict[str, float]
    upstream_release_limit: float = Field(ge=0, le=1)
    downstream_priority: dict[str, float]
    recommended_phase_plan: list[str]
    speed_guidance_parameters: dict[str, float]
    confidence: float = Field(ge=0, le=1)
    cloud_decision_latency_ms: float | None = Field(default=None, ge=0)
    reason_codes: list[str]
    fallback_policy: str

    @model_validator(mode="after")
    def validate_strategy_window_and_ratios(self) -> Self:
        """Validate simulation-time lifetime and per-phase green ratios."""

        if self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be greater than valid_from")
        if any(value < 0 or value > 1 for value in self.target_green_ratios.values()):
            raise ValueError("target green ratios must be between 0 and 1")
        if sum(self.target_green_ratios.values()) > 1.000001:
            raise ValueError("target green ratios cannot sum above 1")
        return self


class ActionType(StrEnum):
    """Supported edge control action verbs."""

    HOLD_PHASE = "hold_phase"
    EXTEND_GREEN = "extend_green"
    TERMINATE_PHASE = "terminate_phase"
    REQUEST_NEXT_PHASE = "request_next_phase"
    CHANGE_CYCLE_TARGET = "change_cycle_target"
    APPLY_SPEED_GUIDANCE = "apply_speed_guidance"
    FALLBACK_FIXED_TIME = "fallback_fixed_time"


class ValidationStatus(StrEnum):
    """Safety-kernel outcome attached to an edge action."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    MODIFIED = "modified"
    REJECTED = "rejected"


class EdgeControlAction(TrafficMessage):
    """Candidate or validated local control action."""

    action_id: UUID = Field(default_factory=uuid4)
    intersection_id: str
    requested_phase_id: str | None
    action_type: ActionType
    requested_duration: float | None = Field(default=None, gt=0)
    source_strategy_id: UUID | None
    validation_status: ValidationStatus = ValidationStatus.PENDING
    rejection_reasons: list[str] = Field(default_factory=list)
    applied_at: float | None = Field(default=None, ge=0)
    expected_effect: dict[str, float | str]
    recommended_speed_m_s: float | None = Field(default=None, ge=0)


class ExecutionStatus(StrEnum):
    """Actual outcome of an edge or vehicle command."""

    EXECUTED = "executed"
    MODIFIED = "modified"
    REJECTED = "rejected"
    FAILED = "failed"


class ExecutionFeedback(TrafficMessage):
    """Execution evidence returned to the strategy originator."""

    action_id: UUID
    strategy_id: UUID | None
    intersection_id: str
    requested_action: dict[str, Any]
    executed_action: dict[str, Any]
    execution_status: ExecutionStatus
    rejection_reason: str | None
    control_mode: str
    command_latency_ms: float = Field(ge=0)
    cloud_round_trip_latency_ms: float | None = Field(default=None, ge=0)
    actual_start_time: float | None = Field(default=None, ge=0)
    actual_end_time: float | None = Field(default=None, ge=0)
    observed_effect: dict[str, float | str]


class CommunicationEvent(TrafficMessage):
    """Observed delivery outcome from the communication emulator or MQTT layer."""

    channel: str
    source: str
    destination: str
    message_type: str
    configured_latency_ms: float = Field(ge=0)
    actual_latency_ms: float = Field(ge=0)
    dropped: bool
    duplicated: bool
    reordered: bool
    corrupted: bool
    timeout: bool
    recovery_time: float | None = Field(default=None, ge=0)


class FaultEvent(TrafficMessage):
    """Injected or naturally detected platform fault."""

    fault_type: str
    target: str
    severity: str
    start_time: float = Field(ge=0)
    duration: float = Field(gt=0)
    injected_by: str
    recovery_policy: str
    recovery_status: str
