"""Strict, versioned intermediate model shared by SUMO and Web 3D."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(item[:1].upper() + item[1:] for item in tail)


class SceneModel(BaseModel):
    """Reject unknown scene fields and serialize stable camelCase keys."""

    model_config = ConfigDict(
        alias_generator=_camel,
        populate_by_name=True,
        extra="forbid",
    )


class Point2(SceneModel):
    x: float
    y: float


class Bounds2(SceneModel):
    min_x: float
    min_y: float
    max_x: float
    max_y: float


class SourceFile(SceneModel):
    path: str
    role: str
    sha256: str


class SceneMetadata(SceneModel):
    schema_version: str = "1.1"
    scene_id: str
    scenario_id: str
    generator: str
    generator_version: str
    claim_boundary: str
    source_files: list[SourceFile]
    counts: dict[str, int]


class CoordinateSystem(SceneModel):
    units: str = "m"
    source_crs: str
    projection: str
    utm_zone: int
    northern_hemisphere: bool
    net_offset: Point2
    sumo_bounds: Bounds2
    geo_bounds: Bounds2
    scene_bounds: Bounds2
    world_origin_sumo: Point2
    world_axes: dict[str, str]


class JunctionRecord(SceneModel):
    scene_id: str
    sumo_junction_id: str
    junction_type: str
    position: Point2
    lon: float
    lat: float
    shape: list[Point2]
    controlled: bool = False
    display_id: str | None = None
    display_name: str | None = None
    role: str | None = None
    provenance: str


class RoadRecord(SceneModel):
    scene_id: str
    source_road_id: str
    name: str | None = None
    road_class: str
    edge_ids: list[str]
    provenance: str


class EdgeRecord(SceneModel):
    scene_id: str
    sumo_edge_id: str
    road_id: str | None
    from_junction_id: str | None
    to_junction_id: str | None
    function: str
    road_type: str | None
    priority: int
    shape: list[Point2]
    lane_ids: list[str]
    length_m: float


class LaneRecord(SceneModel):
    scene_id: str
    sumo_lane_id: str
    sumo_edge_id: str
    index: int
    edge_function: str
    lane_kind: str
    shape: list[Point2]
    width_m: float
    width_source: str
    speed_m_s: float
    length_m: float
    allow: list[str]
    disallow: list[str]


class ConnectionRecord(SceneModel):
    scene_id: str
    from_edge_id: str
    to_edge_id: str
    from_lane_id: str
    to_lane_id: str
    via_lane_id: str | None = None
    direction: str | None = None
    state: str | None = None
    tls_id: str | None = None
    link_index: int | None = None


class CrossingRecord(SceneModel):
    scene_id: str
    sumo_edge_id: str
    junction_id: str
    lane_id: str
    shape: list[Point2]
    width_m: float
    crossed_edge_ids: list[str]


class TrafficPhaseRecord(SceneModel):
    index: int
    duration_s: float
    state: str
    min_duration_s: float | None = None
    max_duration_s: float | None = None


class TrafficLightLinkRecord(SceneModel):
    link_index: int
    from_lane_id: str
    to_lane_id: str
    via_lane_id: str | None = None


class TrafficLightRecord(SceneModel):
    scene_id: str
    sumo_tls_id: str
    controlled_junction_id: str
    program_id: str
    program_type: str
    offset_s: float
    phases: list[TrafficPhaseRecord]
    links: list[TrafficLightLinkRecord]
    display_id: str | None = None


class AreaRecord(SceneModel):
    scene_id: str
    source_id: str
    area_type: str
    shape: list[Point2]
    tags: dict[str, str] = Field(default_factory=dict)
    provenance: str


class BuildingRecord(SceneModel):
    scene_id: str
    source_id: str
    name: str | None = None
    building_type: str
    footprint: list[Point2]
    height_m: float | None = None
    levels: float | None = None
    height_source: str
    tags: dict[str, str] = Field(default_factory=dict)
    provenance: str


class RoadsideDeviceRecord(SceneModel):
    device_id: str
    device_type: str
    position: Point2
    status: str
    managed_junctions: list[str]
    communication_status: str
    provenance: str


class EnvironmentRecord(SceneModel):
    default_weather: str
    default_time_of_day: str
    ground_elevation_m: float
    sky_mode: str
    provenance: str


class ControlCorridorSegmentRecord(SceneModel):
    from_junction_id: str
    to_junction_id: str
    forward_edge_ids: list[str]
    reverse_edge_ids: list[str]
    forward_length_m: float | None = None
    reverse_length_m: float | None = None


class ControlCorridorRecord(SceneModel):
    corridor_id: str
    name: str
    junction_ids: list[str]
    edge_ids: list[str]
    display_ids: list[str]
    segments: list[ControlCorridorSegmentRecord]
    provenance: str


class EdgeRegionRecord(SceneModel):
    edge_id: str
    nearest_controlled_junction_id: str
    region_role: str
    distance_m: float


class SceneDocument(SceneModel):
    """Complete static scene contract; dynamic entities arrive separately."""

    metadata: SceneMetadata
    coordinate_system: CoordinateSystem
    junctions: list[JunctionRecord]
    roads: list[RoadRecord]
    edges: list[EdgeRecord]
    lanes: list[LaneRecord]
    connections: list[ConnectionRecord]
    crossings: list[CrossingRecord]
    traffic_lights: list[TrafficLightRecord]
    bus_stops: list[AreaRecord]
    pedestrian_areas: list[AreaRecord]
    bicycle_areas: list[AreaRecord]
    buildings: list[BuildingRecord]
    vegetation: list[AreaRecord]
    roadside_devices: list[RoadsideDeviceRecord]
    environment: EnvironmentRecord
    zones: list[AreaRecord]
    control_corridors: list[ControlCorridorRecord]
    edge_regions: list[EdgeRegionRecord]
    extensions: dict[str, Any] = Field(default_factory=dict)
