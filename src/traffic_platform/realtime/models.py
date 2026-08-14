"""Versioned compact JSON contracts for the Web 3D entity stream."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from traffic_platform.sumo_adapter import (
    IntersectionSnapshot,
    PedestrianSnapshot,
    VehicleSnapshot,
)


def _camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(item[:1].upper() + item[1:] for item in tail)


class RealtimeModel(BaseModel):
    """Serialize concise camelCase messages and reject accidental fields."""

    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True, extra="forbid")


class SceneReference(RealtimeModel):
    scene_id: str
    schema_version: str
    url: str
    sha256: str
    bytes: int
    counts: dict[str, int]


class VehicleEntity(RealtimeModel):
    id: str
    type: str
    vehicle_class: str
    x: float
    y: float
    angle: float
    speed: float
    acceleration: float
    lane_id: str
    edge_id: str
    route_id: str
    signals: int
    color: str
    brake: bool
    status: Literal["moving", "waiting"]


class PedestrianEntity(RealtimeModel):
    id: str
    type: str
    x: float
    y: float
    angle: float
    speed: float
    lane_id: str
    edge_id: str
    crossing_id: str | None
    waiting_area_id: str | None
    status: Literal["walking", "waiting"]


class TrafficLightEntity(RealtimeModel):
    id: str
    phase_index: int
    state: str
    phase_duration_s: float
    remaining_s: float


class SafetyConflictEntity(RealtimeModel):
    """One trajectory-observed conflict rendered only in analysis mode."""

    id: str
    participant_a_id: str
    participant_b_id: str
    conflict_type: str
    x: float
    y: float
    minimum_distance_m: float
    relative_speed_m_s: float
    ttc_s: float | None = None
    pet_s: float | None = None
    severity: str


class EntityStateSet(RealtimeModel):
    vehicles: list[VehicleEntity] = Field(default_factory=list)
    bicycles: list[VehicleEntity] = Field(default_factory=list)
    pedestrians: list[PedestrianEntity] = Field(default_factory=list)


class EntityRemovalSet(RealtimeModel):
    vehicles: list[str] = Field(default_factory=list)
    bicycles: list[str] = Field(default_factory=list)
    pedestrians: list[str] = Field(default_factory=list)


class RealtimeEvent(RealtimeModel):
    event_id: str
    simulation_time: float
    event: str
    detail: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class DigitalTwinInit(RealtimeModel):
    type: Literal["init"] = "init"
    protocol_version: Literal["1.0"] = "1.0"
    sequence: int
    status: str
    experiment_id: str | None
    scenario_id: str
    simulation_time_s: float
    tick_hz: float
    scene: SceneReference
    vehicle_types: list[str]
    entities: EntityStateSet
    traffic_lights: list[TrafficLightEntity]
    conflicts: list[SafetyConflictEntity] = Field(default_factory=list)
    active_events: list[RealtimeEvent] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    intersection_metrics: list[dict[str, Any]] = Field(default_factory=list)


class DigitalTwinDelta(RealtimeModel):
    type: Literal["delta"] = "delta"
    protocol_version: Literal["1.0"] = "1.0"
    sequence: int
    experiment_id: str
    simulation_time_s: float
    spawn: EntityStateSet
    update: EntityStateSet
    remove: EntityRemovalSet
    traffic_lights: list[TrafficLightEntity]
    conflicts: list[SafetyConflictEntity] = Field(default_factory=list)
    events: list[RealtimeEvent]
    metrics: dict[str, Any] = Field(default_factory=dict)
    intersection_metrics: list[dict[str, Any]] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class DigitalTwinSourceFrame:
    """One actual SUMO tick passed from the runner without visual synthesis."""

    experiment_id: str
    scenario_id: str
    simulation_time_s: float
    tick_hz: float
    vehicles: Sequence[VehicleSnapshot]
    pedestrians: Sequence[PedestrianSnapshot]
    traffic_lights: Sequence[IntersectionSnapshot]
    events: Sequence[Mapping[str, object]]
    conflicts: Sequence[Mapping[str, object]] = field(default_factory=tuple)
    metrics: Mapping[str, object] = field(default_factory=dict)
    intersection_metrics: Sequence[Mapping[str, object]] = field(default_factory=tuple)
