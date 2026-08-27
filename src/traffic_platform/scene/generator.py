"""Generate a traceable Web 3D scene document from the frozen SUMO network."""

from __future__ import annotations

import hashlib
import heapq
import json
import math
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from itertools import pairwise
from pathlib import Path
from typing import Any

from traffic_platform.scene.coordinates import CoordinateDefinition, CoordinateService
from traffic_platform.scene.models import (
    AreaRecord,
    Bounds2,
    BuildingRecord,
    ConnectionRecord,
    ControlCorridorRecord,
    ControlCorridorSegmentRecord,
    CoordinateSystem,
    CrossingRecord,
    EdgeRecord,
    EdgeRegionRecord,
    EnvironmentRecord,
    JunctionRecord,
    LaneRecord,
    Point2,
    RoadRecord,
    RoadsideDeviceRecord,
    SceneDocument,
    SceneMetadata,
    SourceFile,
    TrafficLightLinkRecord,
    TrafficLightRecord,
    TrafficPhaseRecord,
)

GENERATOR_VERSION = "1.2.0"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _points(value: str | None) -> list[Point2]:
    if not value:
        return []
    result: list[Point2] = []
    for pair in value.split():
        x_value, y_value = pair.split(",")[:2]
        result.append(Point2(x=float(x_value), y=float(y_value)))
    return result


def _point_bounds(points: list[Point2]) -> Bounds2 | None:
    if not points:
        return None
    xs = [point.x for point in points]
    ys = [point.y for point in points]
    return Bounds2(min_x=min(xs), min_y=min(ys), max_x=max(xs), max_y=max(ys))


def _intersects(points: list[Point2], bounds: Bounds2) -> bool:
    item = _point_bounds(points)
    return bool(
        item is not None
        and item.max_x >= bounds.min_x
        and item.min_x <= bounds.max_x
        and item.max_y >= bounds.min_y
        and item.min_y <= bounds.max_y
    )


def _inside(point: Point2, bounds: Bounds2) -> bool:
    return bounds.min_x <= point.x <= bounds.max_x and bounds.min_y <= point.y <= bounds.max_y


def _length(points: list[Point2]) -> float:
    return sum(math.hypot(right.x - left.x, right.y - left.y) for left, right in pairwise(points))


def _road_source_id(edge_id: str) -> str:
    identifier = edge_id.removeprefix("-")
    return identifier.split("#", 1)[0]


def _lane_kind(allow: list[str], disallow: list[str], function: str) -> str:
    allowed = set(allow)
    denied = set(disallow)
    if function == "crossing":
        return "pedestrian_crossing"
    if function == "walkingarea":
        return "pedestrian_area"
    if allowed and allowed <= {"pedestrian"}:
        return "pedestrian"
    if allowed and allowed <= {"bicycle"}:
        return "bicycle"
    if allowed and allowed <= {"pedestrian", "bicycle"}:
        return "shared_active"
    if {"pedestrian", "bicycle"} <= denied:
        return "motor"
    if "pedestrian" in allowed or "bicycle" in allowed:
        return "mixed"
    return "motor" if function == "internal" else "mixed"


def _number(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", value)
    return float(match.group(0)) if match else None


def _junction_from_area_id(edge_id: str, marker: str) -> str:
    return edge_id.removeprefix(":").rsplit(marker, 1)[0]


def _load_osm(
    path: Path,
    coordinates: CoordinateService,
    scene_bounds: Bounds2,
) -> tuple[
    dict[str, str],
    list[BuildingRecord],
    list[AreaRecord],
    list[AreaRecord],
    list[AreaRecord],
    list[RoadsideDeviceRecord],
]:
    root = ET.parse(path).getroot()
    nodes: dict[str, tuple[float, float, dict[str, str]]] = {}
    road_names: dict[str, str] = {}
    bus_stops: list[AreaRecord] = []
    devices: list[RoadsideDeviceRecord] = []
    for node in root.findall("node"):
        tags = {tag.get("k", ""): tag.get("v", "") for tag in node.findall("tag")}
        lon = float(node.get("lon", "0"))
        lat = float(node.get("lat", "0"))
        nodes[node.get("id", "")] = (lon, lat, tags)
        x_m, y_m = coordinates.lon_lat_to_sumo(lon, lat)
        point = Point2(x=x_m, y=y_m)
        if not _inside(point, scene_bounds):
            continue
        node_id = node.get("id", "")
        if tags.get("highway") == "bus_stop" or tags.get("public_transport") == "platform":
            bus_stops.append(
                AreaRecord(
                    scene_id=f"bus-stop:osm-node:{node_id}",
                    source_id=f"osm:node:{node_id}",
                    area_type="bus_stop",
                    shape=[point],
                    tags=tags,
                    provenance="openstreetmap",
                )
            )
        device_type = None
        if tags.get("man_made") == "surveillance":
            device_type = "camera"
        elif tags.get("highway") == "street_lamp":
            device_type = "street_light"
        if device_type:
            devices.append(
                RoadsideDeviceRecord(
                    device_id=f"osm-node:{node_id}",
                    device_type=device_type,
                    position=point,
                    status="unknown_static_inventory",
                    managed_junctions=[],
                    communication_status="not_applicable",
                    provenance="openstreetmap",
                )
            )

    buildings: list[BuildingRecord] = []
    vegetation: list[AreaRecord] = []
    zones: list[AreaRecord] = []
    for way in root.findall("way"):
        way_id = way.get("id", "")
        tags = {tag.get("k", ""): tag.get("v", "") for tag in way.findall("tag")}
        if tags.get("highway") and tags.get("name"):
            road_names[way_id] = tags["name"]
        refs = [item.get("ref", "") for item in way.findall("nd")]
        footprint: list[Point2] = []
        for ref in refs:
            node_data = nodes.get(ref)
            if node_data is None:
                continue
            x_m, y_m = coordinates.lon_lat_to_sumo(node_data[0], node_data[1])
            footprint.append(Point2(x=x_m, y=y_m))
        if not footprint or not _intersects(footprint, scene_bounds):
            continue
        source_id = f"osm:way:{way_id}"
        if "building" in tags and len(footprint) >= 3:
            explicit_height = _number(tags.get("height"))
            levels = _number(tags.get("building:levels"))
            if explicit_height is not None:
                height = explicit_height
                height_source = "osm_height"
            elif levels is not None:
                height = levels * 3.2
                height_source = "modeled_from_osm_levels_3.2m"
            else:
                height = None
                height_source = "not_available"
            buildings.append(
                BuildingRecord(
                    scene_id=f"building:{source_id}",
                    source_id=source_id,
                    name=tags.get("name"),
                    building_type=tags.get("building", "yes"),
                    footprint=footprint,
                    height_m=height,
                    levels=levels,
                    height_source=height_source,
                    tags=tags,
                    provenance="openstreetmap",
                )
            )
        vegetation_type = (
            tags.get("leisure")
            if tags.get("leisure") in {"park", "garden"}
            else tags.get("natural")
            if tags.get("natural") in {"wood", "grassland", "scrub"}
            else tags.get("landuse")
            if tags.get("landuse") in {"grass", "forest", "meadow"}
            else None
        )
        if vegetation_type:
            vegetation.append(
                AreaRecord(
                    scene_id=f"vegetation:{source_id}",
                    source_id=source_id,
                    area_type=vegetation_type,
                    shape=footprint,
                    tags=tags,
                    provenance="openstreetmap",
                )
            )
        zone_type = (
            tags.get("landuse")
            or tags.get("leisure")
            or tags.get("amenity")
            or tags.get("natural")
            or tags.get("water")
            or tags.get("waterway")
        )
        if zone_type:
            zones.append(
                AreaRecord(
                    scene_id=f"zone:{source_id}",
                    source_id=source_id,
                    area_type=zone_type,
                    shape=footprint,
                    tags=tags,
                    provenance="openstreetmap",
                )
            )
    return road_names, buildings, vegetation, zones, bus_stops, devices


def _shortest_edge_path(
    graph: dict[str, list[tuple[str, str, float]]],
    start: str,
    target: str,
) -> list[str]:
    queue: list[tuple[float, str]] = [(0.0, start)]
    distances = {start: 0.0}
    previous: dict[str, tuple[str, str]] = {}
    while queue:
        distance, node = heapq.heappop(queue)
        if distance != distances.get(node):
            continue
        if node == target:
            break
        for neighbor, edge_id, weight in graph.get(node, []):
            candidate = distance + weight
            if candidate >= distances.get(neighbor, float("inf")):
                continue
            distances[neighbor] = candidate
            previous[neighbor] = (node, edge_id)
            heapq.heappush(queue, (candidate, neighbor))
    if target not in distances:
        return []
    path: list[str] = []
    cursor = target
    while cursor != start:
        prior, edge_id = previous[cursor]
        path.append(edge_id)
        cursor = prior
    path.reverse()
    return path


def _parse_network(
    path: Path,
    scene_bounds: Bounds2,
    controlled_tls: dict[str, dict[str, Any]],
    controlled_junctions: dict[str, dict[str, Any]],
) -> tuple[
    dict[str, str],
    Bounds2,
    Bounds2,
    Point2,
    list[JunctionRecord],
    list[EdgeRecord],
    list[LaneRecord],
    list[ConnectionRecord],
    list[CrossingRecord],
    list[AreaRecord],
    list[AreaRecord],
    list[TrafficLightRecord],
]:
    location: dict[str, str] = {}
    junctions: list[JunctionRecord] = []
    edges: list[EdgeRecord] = []
    lanes: list[LaneRecord] = []
    crossings: list[CrossingRecord] = []
    pedestrian_areas: list[AreaRecord] = []
    bicycle_areas: list[AreaRecord] = []
    tls_programs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    raw_connections: list[dict[str, str]] = []
    selected_edge_ids: set[str] = set()

    for _event, element in ET.iterparse(path, events=("end",)):
        if element.tag == "location":
            location = dict(element.attrib)
            element.clear()
        elif element.tag == "edge":
            edge_id = element.get("id", "")
            function = element.get("function", "ordinary")
            lane_elements = element.findall("lane")
            lane_shapes = [_points(item.get("shape")) for item in lane_elements]
            edge_shape = _points(element.get("shape")) or next(
                (shape for shape in lane_shapes if shape),
                [],
            )
            if not _intersects(edge_shape, scene_bounds):
                element.clear()
                continue
            selected_edge_ids.add(edge_id)
            lane_ids: list[str] = []
            edge_length = 0.0
            for lane_element, shape in zip(lane_elements, lane_shapes, strict=True):
                lane_id = lane_element.get("id", "")
                allow = (lane_element.get("allow") or "").split()
                disallow = (lane_element.get("disallow") or "").split()
                width_value = lane_element.get("width")
                width_m = float(width_value) if width_value is not None else 3.2
                length_m = float(lane_element.get("length", "0"))
                edge_length = max(edge_length, length_m)
                lane = LaneRecord(
                    scene_id=f"lane:{lane_id}",
                    sumo_lane_id=lane_id,
                    sumo_edge_id=edge_id,
                    index=int(lane_element.get("index", "0")),
                    edge_function=function,
                    lane_kind=_lane_kind(allow, disallow, function),
                    shape=shape,
                    width_m=width_m,
                    width_source=("sumo_explicit" if width_value is not None else "sumo_default"),
                    speed_m_s=float(lane_element.get("speed", "0")),
                    length_m=length_m,
                    allow=allow,
                    disallow=disallow,
                )
                lanes.append(lane)
                lane_ids.append(lane_id)
                if lane.lane_kind == "bicycle":
                    bicycle_areas.append(
                        AreaRecord(
                            scene_id=f"bicycle-area:{lane_id}",
                            source_id=lane_id,
                            area_type="dedicated_bicycle_lane",
                            shape=shape,
                            tags={},
                            provenance="sumo_lane_permissions",
                        )
                    )
            road_id = f"road:osm-way:{_road_source_id(edge_id)}" if function == "ordinary" else None
            edges.append(
                EdgeRecord(
                    scene_id=f"edge:{edge_id}",
                    sumo_edge_id=edge_id,
                    road_id=road_id,
                    from_junction_id=element.get("from"),
                    to_junction_id=element.get("to"),
                    function=function,
                    road_type=element.get("type"),
                    priority=int(element.get("priority", "0")),
                    shape=edge_shape,
                    lane_ids=lane_ids,
                    length_m=edge_length or _length(edge_shape),
                )
            )
            if function == "crossing" and lane_elements:
                lane = lanes[-len(lane_elements)]
                crossings.append(
                    CrossingRecord(
                        scene_id=f"crossing:{edge_id}",
                        sumo_edge_id=edge_id,
                        junction_id=_junction_from_area_id(edge_id, "_c"),
                        lane_id=lane.sumo_lane_id,
                        shape=lane.shape,
                        width_m=lane.width_m,
                        crossed_edge_ids=(element.get("crossingEdges") or "").split(),
                    )
                )
            elif function == "walkingarea" and lane_elements:
                lane = lanes[-len(lane_elements)]
                pedestrian_areas.append(
                    AreaRecord(
                        scene_id=f"pedestrian-area:{edge_id}",
                        source_id=edge_id,
                        area_type="walking_area",
                        shape=lane.shape,
                        tags={},
                        provenance="sumo_walkingarea",
                    )
                )
            element.clear()
        elif element.tag == "junction":
            position = Point2(
                x=float(element.get("x", "0")),
                y=float(element.get("y", "0")),
            )
            junction_id = element.get("id", "")
            if _inside(position, scene_bounds) or junction_id in controlled_junctions:
                item = controlled_junctions.get(junction_id, {})
                junctions.append(
                    JunctionRecord(
                        scene_id=f"junction:{junction_id}",
                        sumo_junction_id=junction_id,
                        junction_type=element.get("type", "unknown"),
                        position=position,
                        lon=float(item.get("lon", 0.0)),
                        lat=float(item.get("lat", 0.0)),
                        shape=_points(element.get("shape")),
                        controlled=junction_id in controlled_junctions,
                        display_id=item.get("display_id"),
                        display_name=item.get("display_name"),
                        role=item.get("role"),
                        provenance=(
                            str(item.get("parameter_provenance"))
                            if junction_id in controlled_junctions
                            else "sumo_osm_derived"
                        ),
                    )
                )
            element.clear()
        elif element.tag == "tlLogic":
            tls_id = element.get("id", "")
            if tls_id in controlled_tls:
                tls_programs[tls_id].append(
                    {
                        "program_id": element.get("programID", "0"),
                        "type": element.get("type", "static"),
                        "offset": float(element.get("offset", "0")),
                        "phases": [dict(phase.attrib) for phase in element.findall("phase")],
                    }
                )
            element.clear()
        elif element.tag == "connection":
            raw_connections.append(dict(element.attrib))
            element.clear()

    connections: list[ConnectionRecord] = []
    links_by_tls: dict[str, list[TrafficLightLinkRecord]] = defaultdict(list)
    for index, item in enumerate(raw_connections):
        from_edge = item.get("from", "")
        to_edge = item.get("to", "")
        if from_edge not in selected_edge_ids or to_edge not in selected_edge_ids:
            continue
        from_lane = f"{from_edge}_{item.get('fromLane', '0')}"
        to_lane = f"{to_edge}_{item.get('toLane', '0')}"
        connection_tls_id = item.get("tl")
        link_index = int(item["linkIndex"]) if item.get("linkIndex") is not None else None
        connections.append(
            ConnectionRecord(
                scene_id=f"connection:{from_lane}:{to_lane}:{index}",
                from_edge_id=from_edge,
                to_edge_id=to_edge,
                from_lane_id=from_lane,
                to_lane_id=to_lane,
                via_lane_id=item.get("via"),
                direction=item.get("dir"),
                state=item.get("state"),
                tls_id=connection_tls_id,
                link_index=link_index,
            )
        )
        if connection_tls_id in controlled_tls and link_index is not None:
            links_by_tls[connection_tls_id].append(
                TrafficLightLinkRecord(
                    link_index=link_index,
                    from_lane_id=from_lane,
                    to_lane_id=to_lane,
                    via_lane_id=item.get("via"),
                )
            )

    traffic_lights: list[TrafficLightRecord] = []
    for tls_id in sorted(controlled_tls):
        programs = tls_programs.get(tls_id, [])
        for program in programs:
            phases = [
                TrafficPhaseRecord(
                    index=index,
                    duration_s=float(phase.get("duration", "0")),
                    state=phase.get("state", ""),
                    min_duration_s=(
                        float(phase["minDur"]) if phase.get("minDur") is not None else None
                    ),
                    max_duration_s=(
                        float(phase["maxDur"]) if phase.get("maxDur") is not None else None
                    ),
                )
                for index, phase in enumerate(program["phases"])
            ]
            links = sorted(
                links_by_tls.get(tls_id, []),
                key=lambda item: (item.link_index, item.from_lane_id, item.to_lane_id),
            )
            traffic_lights.append(
                TrafficLightRecord(
                    scene_id=f"tls:{tls_id}:{program['program_id']}",
                    sumo_tls_id=tls_id,
                    controlled_junction_id=str(
                        controlled_tls[tls_id].get("intersection_id", tls_id)
                    ),
                    program_id=str(program["program_id"]),
                    program_type=str(program["type"]),
                    offset_s=float(program["offset"]),
                    phases=phases,
                    links=links,
                    display_id=controlled_tls[tls_id].get("display_id"),
                )
            )

    net_offset_values = [float(item) for item in location["netOffset"].split(",")]
    sumo_values = [float(item) for item in location["convBoundary"].split(",")]
    geo_values = [float(item) for item in location["origBoundary"].split(",")]
    return (
        location,
        Bounds2(
            min_x=sumo_values[0],
            min_y=sumo_values[1],
            max_x=sumo_values[2],
            max_y=sumo_values[3],
        ),
        Bounds2(
            min_x=geo_values[0],
            min_y=geo_values[1],
            max_x=geo_values[2],
            max_y=geo_values[3],
        ),
        Point2(x=net_offset_values[0], y=net_offset_values[1]),
        junctions,
        edges,
        lanes,
        connections,
        crossings,
        pedestrian_areas,
        bicycle_areas,
        traffic_lights,
    )


def generate_scene_document(
    workspace: Path,
    *,
    scenario_id: str = "xiongan_rongdong_20",
    output_path: Path | None = None,
    padding_m: float = 300.0,
) -> dict[str, Any]:
    """Generate and validate one deterministic static scene artifact."""

    if padding_m < 0:
        raise ValueError("padding_m must be non-negative")
    generated = workspace / "scenarios" / "generated" / scenario_id
    network_file = generated / "rongdong.multimodal.net.xml"
    selection_file = generated / "controlled_intersections.json"
    zones_file = generated / "functional_zones.json"
    osm_file = generated / "source.osm.xml"
    if scenario_id == "xiongan_rongdong_20" and not osm_file.is_file():
        osm_file = workspace / "scenarios" / "source" / scenario_id / "rongdong_bbox.osm.xml"
    vtypes_file = generated / "vtypes.add.xml"
    config_file = workspace / "scenarios" / "configs" / f"{scenario_id}.yaml"
    source_files = [
        (network_file, "sumo_network_truth"),
        (selection_file, "controlled_intersection_registry"),
        (zones_file, "functional_zone_inventory"),
        (vtypes_file, "sumo_participant_types"),
        (config_file, "scenario_configuration"),
    ]
    if osm_file.is_file():
        source_files.append((osm_file, "osm_geographic_context"))
    missing = [path for path, _role in source_files if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"scene inputs are missing: {missing}")

    selection = json.loads(selection_file.read_text(encoding="utf-8"))
    selected_items = selection["intersections"]
    controlled_tls = {
        str(item.get("sumo_tls_id", item["intersection_id"])): item for item in selected_items
    }
    controlled_junctions: dict[str, dict[str, Any]] = {}
    for item in selected_items:
        members = item.get(
            "member_sumo_junction_ids", [item.get("sumo_node_id", item["intersection_id"])]
        )
        for junction_id in members:
            controlled_junctions[str(junction_id)] = item
    xs = [float(item["x"]) for item in selected_items]
    ys = [float(item["y"]) for item in selected_items]
    controlled_bounds = Bounds2(
        min_x=min(xs),
        min_y=min(ys),
        max_x=max(xs),
        max_y=max(ys),
    )
    scene_bounds = Bounds2(
        min_x=controlled_bounds.min_x - padding_m,
        min_y=controlled_bounds.min_y - padding_m,
        max_x=controlled_bounds.max_x + padding_m,
        max_y=controlled_bounds.max_y + padding_m,
    )
    origin = Point2(
        x=round((controlled_bounds.min_x + controlled_bounds.max_x) / 2.0, 3),
        y=round((controlled_bounds.min_y + controlled_bounds.max_y) / 2.0, 3),
    )

    (
        location,
        sumo_bounds,
        geo_bounds,
        net_offset,
        junctions,
        edges,
        lanes,
        connections,
        crossings,
        pedestrian_areas,
        bicycle_areas,
        traffic_lights,
    ) = _parse_network(network_file, scene_bounds, controlled_tls, controlled_junctions)
    projection = location.get("projParameter", "-")
    coordinates = (
        CoordinateService(
            CoordinateDefinition(
                projection=projection,
                net_offset_x=net_offset.x,
                net_offset_y=net_offset.y,
                world_origin_sumo_x=origin.x,
                world_origin_sumo_y=origin.y,
            )
        )
        if projection not in {"", "-", "!"}
        else None
    )
    for junction in junctions:
        if coordinates is not None and not junction.lon and not junction.lat:
            junction.lon, junction.lat = coordinates.sumo_to_lon_lat(
                junction.position.x,
                junction.position.y,
            )

    if coordinates is not None and osm_file.is_file():
        road_names, buildings, vegetation, zones, bus_stops, devices = _load_osm(
            osm_file,
            coordinates,
            scene_bounds,
        )
    else:
        road_names, buildings, vegetation, zones, bus_stops, devices = ({}, [], [], [], [], [])
    # The source OSM extract does not inventory RSUs/cameras. Add an explicitly
    # authored, reproducible engineering layout at each controlled junction,
    # anchored to a real incoming SUMO lane rather than arbitrary map offsets.
    lane_by_id = {lane.sumo_lane_id: lane for lane in lanes}
    authored_device_ids: set[str] = set()
    for controller in traffic_lights:
        rsu_id = f"rsu:{controller.controlled_junction_id}"
        if rsu_id in authored_device_ids:
            continue
        incoming_lane = next(
            (
                lane_by_id.get(link.from_lane_id)
                for link in controller.links
                if lane_by_id.get(link.from_lane_id) is not None
                and len(lane_by_id[link.from_lane_id].shape) >= 2
            ),
            None,
        )
        if incoming_lane is None:
            continue
        end = incoming_lane.shape[-1]
        previous = incoming_lane.shape[-2]
        dx = end.x - previous.x
        dy = end.y - previous.y
        length = math.hypot(dx, dy)
        if length < 0.01:
            continue
        normal_x = -dy / length
        normal_y = dx / length
        roadside_offset = incoming_lane.width_m / 2 + 2.2
        managed = [controller.controlled_junction_id]
        devices.extend(
            [
                RoadsideDeviceRecord(
                    device_id=rsu_id,
                    device_type="rsu",
                    position=Point2(
                        x=end.x + normal_x * roadside_offset,
                        y=end.y + normal_y * roadside_offset,
                    ),
                    status="modeled_asset",
                    managed_junctions=managed,
                    communication_status="runtime_unbound",
                    provenance="engineering_model_from_controlled_junction_and_sumo_lane",
                ),
                RoadsideDeviceRecord(
                    device_id=f"camera:{controller.controlled_junction_id}",
                    device_type="camera",
                    position=Point2(
                        x=end.x - normal_x * roadside_offset,
                        y=end.y - normal_y * roadside_offset,
                    ),
                    status="modeled_asset",
                    managed_junctions=managed,
                    communication_status="runtime_unbound",
                    provenance="engineering_model_from_controlled_junction_and_sumo_lane",
                ),
            ]
        )
        authored_device_ids.add(rsu_id)
    road_groups: dict[str, list[EdgeRecord]] = defaultdict(list)
    for edge in edges:
        if edge.road_id is not None:
            road_groups[edge.road_id].append(edge)
    roads = [
        RoadRecord(
            scene_id=road_id,
            source_road_id=road_id.removeprefix("road:osm-way:"),
            name=road_names.get(road_id.removeprefix("road:osm-way:")),
            road_class=next(
                (edge.road_type or "unknown" for edge in group if edge.road_type),
                "unknown",
            ),
            edge_ids=sorted(edge.sumo_edge_id for edge in group),
            provenance=("sumo_osm_derived" if osm_file.is_file() else "sumo_source_derived"),
        )
        for road_id, group in sorted(road_groups.items())
    ]

    graph: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
    for edge in edges:
        if (
            edge.function == "ordinary"
            and edge.from_junction_id is not None
            and edge.to_junction_id is not None
        ):
            graph[edge.from_junction_id].append(
                (edge.to_junction_id, edge.sumo_edge_id, edge.length_m)
            )
    corridor_ids = list(selection["core_corridor"])
    corridor_edges: list[str] = []
    corridor_segments: list[ControlCorridorSegmentRecord] = []
    edge_length_by_id = {edge.sumo_edge_id: edge.length_m for edge in edges}
    for start, target in pairwise(corridor_ids):
        forward_path = _shortest_edge_path(graph, start, target)
        reverse_path = _shortest_edge_path(graph, target, start)
        if not forward_path and not reverse_path:
            raise ValueError(f"no SUMO edge path between core corridor nodes {start} and {target}")
        corridor_edges.extend(forward_path)
        corridor_edges.extend(reverse_path)
        corridor_segments.append(
            ControlCorridorSegmentRecord(
                from_junction_id=start,
                to_junction_id=target,
                forward_edge_ids=forward_path,
                reverse_edge_ids=reverse_path,
                forward_length_m=(
                    round(sum(edge_length_by_id[item] for item in forward_path), 3)
                    if forward_path
                    else None
                ),
                reverse_length_m=(
                    round(sum(edge_length_by_id[item] for item in reverse_path), 3)
                    if reverse_path
                    else None
                ),
            )
        )
    display_by_id = {item["intersection_id"]: item["display_id"] for item in selected_items}
    corridors = [
        ControlCorridorRecord(
            corridor_id="core-k01-k08",
            name="核心控制走廊 K01-K08",
            junction_ids=corridor_ids,
            edge_ids=list(dict.fromkeys(corridor_edges)),
            display_ids=[display_by_id[item] for item in corridor_ids],
            segments=corridor_segments,
            provenance="controlled_intersections_registry_plus_sumo_shortest_path",
        )
    ]

    controlled_positions = {
        item["intersection_id"]: Point2(x=float(item["x"]), y=float(item["y"]))
        for item in selected_items
    }
    edge_regions: list[EdgeRegionRecord] = []
    corridor_edge_set = set(corridors[0].edge_ids)
    for edge in edges:
        if edge.function != "ordinary" or not edge.shape:
            continue
        midpoint = edge.shape[len(edge.shape) // 2]
        nearest_id, distance = min(
            (
                (
                    junction_id,
                    math.hypot(midpoint.x - point.x, midpoint.y - point.y),
                )
                for junction_id, point in controlled_positions.items()
            ),
            key=lambda item: item[1],
        )
        edge_regions.append(
            EdgeRegionRecord(
                edge_id=edge.sumo_edge_id,
                nearest_controlled_junction_id=nearest_id,
                region_role=(
                    "core_corridor" if edge.sumo_edge_id in corridor_edge_set else "context"
                ),
                distance_m=distance,
            )
        )

    arrays: dict[str, list[Any]] = {
        "junctions": junctions,
        "roads": roads,
        "edges": edges,
        "lanes": lanes,
        "connections": connections,
        "crossings": crossings,
        "trafficLights": traffic_lights,
        "busStops": bus_stops,
        "pedestrianAreas": pedestrian_areas,
        "bicycleAreas": bicycle_areas,
        "buildings": buildings,
        "vegetation": vegetation,
        "roadsideDevices": devices,
        "zones": zones,
        "controlCorridors": corridors,
        "edgeRegions": edge_regions,
    }
    zone_match = re.search(r"(?:\+zone=|zone=)(\d+)", projection)
    metadata = SceneMetadata(
        scene_id=scenario_id,
        scenario_id=scenario_id,
        generator="traffic_platform.scene.generator",
        generator_version=GENERATOR_VERSION,
        claim_boundary=(
            "SUMO is the topology and traffic truth. OSM geography is retained when available; "
            "planning-file geometry and authored visual context remain reviewed engineering models."
        ),
        source_files=[
            SourceFile(
                path=path.relative_to(workspace).as_posix(),
                role=role,
                sha256=_sha256(path),
            )
            for path, role in source_files
        ],
        counts={name: len(items) for name, items in arrays.items()},
    )
    document = SceneDocument(
        metadata=metadata,
        coordinate_system=CoordinateSystem(
            source_crs=(
                f"WGS84 / projected zone {zone_match.group(1)}"
                if zone_match
                else "SUMO local Cartesian"
            ),
            projection=projection,
            utm_zone=int(zone_match.group(1)) if zone_match else 0,
            northern_hemisphere="+south" not in projection,
            net_offset=net_offset,
            sumo_bounds=sumo_bounds,
            geo_bounds=geo_bounds,
            scene_bounds=scene_bounds,
            world_origin_sumo=origin,
            world_axes={
                "x": "east",
                "y": "up",
                "z": "south; north is -z",
            },
        ),
        junctions=junctions,
        roads=roads,
        edges=edges,
        lanes=lanes,
        connections=connections,
        crossings=crossings,
        traffic_lights=traffic_lights,
        bus_stops=bus_stops,
        pedestrian_areas=pedestrian_areas,
        bicycle_areas=bicycle_areas,
        buildings=buildings,
        vegetation=vegetation,
        roadside_devices=devices,
        environment=EnvironmentRecord(
            default_weather="clear",
            default_time_of_day="day",
            ground_elevation_m=0.0,
            sky_mode="lightweight_environment",
            provenance="engineering_default_not_observed_weather",
        ),
        zones=zones,
        control_corridors=corridors,
        edge_regions=edge_regions,
        extensions={
            "staticOnly": True,
            "controlledBounds": controlled_bounds.model_dump(by_alias=True),
            "paddingM": padding_m,
            "selectionRule": "SUMO geometry bounding box intersects controlled bounds plus padding",
            "idMappings": {
                "junctionDisplayToSumo": {
                    item["display_id"]: item["intersection_id"] for item in selected_items
                },
                "junctionSumoToDisplay": display_by_id,
                "scenePrefixes": {
                    "junction": "junction:",
                    "road": "road:osm-way:",
                    "edge": "edge:",
                    "lane": "lane:",
                    "trafficLight": "tls:",
                },
            },
            "provenanceLegend": {
                "openstreetmap": "OSM geometry or tags",
                "sumo_osm_derived": "SUMO geometry derived from OSM",
                "modeled": "engineering assumption, never field measured",
            },
        },
    )

    destination = output_path or (workspace / "generated" / "scenes" / f"{scenario_id}.scene.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(document.model_dump_json(by_alias=True), encoding="utf-8")
    scene_sha256 = _sha256(destination)
    schema_path = destination.with_suffix(".schema.json")
    schema_path.write_text(
        json.dumps(SceneDocument.model_json_schema(by_alias=True), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    manifest_path = destination.with_suffix(".manifest.json")
    manifest_path.write_text(
        json.dumps(
            {
                "schemaVersion": document.metadata.schema_version,
                "sceneId": scenario_id,
                "sceneFile": destination.name,
                "sceneSha256": scene_sha256,
                "sceneBytes": destination.stat().st_size,
                "counts": document.metadata.counts,
                "sourceFiles": [
                    source.model_dump(by_alias=True) for source in document.metadata.source_files
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    mapping_path = destination.with_name(
        destination.name.replace(".scene.json", ".traffic_light_mapping.json")
    )
    mapping_path.write_text(
        json.dumps(
            {
                "schemaVersion": "1.0",
                "sceneId": scenario_id,
                "sourceSceneFile": destination.name,
                "sourceSceneSha256": scene_sha256,
                "controllers": [
                    {
                        "sceneId": controller.scene_id,
                        "sumoTlsId": controller.sumo_tls_id,
                        "controlledJunctionId": controller.controlled_junction_id,
                        "memberSumoJunctionIds": controlled_tls[controller.sumo_tls_id].get(
                            "member_sumo_junction_ids", [controller.controlled_junction_id]
                        ),
                        "displayId": controller.display_id,
                        "programId": controller.program_id,
                        "links": [link.model_dump(by_alias=True) for link in controller.links],
                        "phaseStateLengths": [len(phase.state) for phase in controller.phases],
                    }
                    for controller in traffic_lights
                ],
                "counts": {
                    "controllers": len(traffic_lights),
                    "links": sum(len(controller.links) for controller in traffic_lights),
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "status": "generated",
        "scene_id": scenario_id,
        "output": str(destination),
        "schema": str(schema_path),
        "manifest": str(manifest_path),
        "traffic_light_mapping": str(mapping_path),
        "sha256": scene_sha256,
        "counts": metadata.counts,
    }
