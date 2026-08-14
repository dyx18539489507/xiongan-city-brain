"""Evidence registry and geometry resolver for organizer standalone junctions."""

from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from itertools import pairwise, permutations
from pathlib import Path
from typing import Any

from pyproj import Geod

from traffic_platform.scenario_engine.official_models import MOVEMENTS, OfficialWorkbook

_GEOD = Geod(ellps="WGS84")
_STANDARD_STANDALONE_ARM_M = 250.0
_TARGET_BEARINGS = {"N": 0.0, "E": 90.0, "S": 180.0, "W": 270.0}
_DESTINATION_ARM = {
    "E_L": "S",
    "E_S": "W",
    "E_R": "N",
    "W_L": "N",
    "W_S": "E",
    "W_R": "S",
    "S_L": "W",
    "S_S": "N",
    "S_R": "E",
    "N_L": "E",
    "N_S": "S",
    "N_R": "W",
}
_PHASE_NAME_MOVEMENTS: dict[str, set[str]] = {
    "东西向直行": {"E_S", "E_R", "W_S", "W_R"},
    "东西向左转": {"E_L", "W_L"},
    "南北向直行": {"N_S", "N_R", "S_S", "S_R"},
    "南北向左转": {"N_L", "S_L"},
    "西南向左转": {"W_L", "W_R", "S_L"},
    "东西左转直行": {"E_L", "E_S", "E_R", "W_L", "W_S", "W_R"},
    "南北左转直行": {"N_L", "N_S", "N_R", "S_L", "S_S", "S_R"},
    "西向直左": {"W_L", "W_S", "W_R"},
    "东向直左": {"E_L", "E_S", "E_R"},
    "南北向直左": {"N_L", "N_S", "N_R", "S_L", "S_S", "S_R"},
    "东西向直左": {"E_L", "E_S", "E_R", "W_L", "W_S", "W_R"},
    "南向左右转": {"S_L", "S_R"},
    "东西直左": {"E_L", "E_S", "E_R", "W_L", "W_S", "W_R"},
    "南北左转": {"N_L", "S_L"},
    "南北直行": {"N_S", "N_R", "S_S", "S_R"},
    "西向直左南向直右": {"W_L", "W_S", "W_R", "S_S", "S_R"},
    "东向左右转": {"E_L", "E_R"},
    "东北左转右转": {"E_L", "E_R", "N_L", "N_R"},
    "东南向左转": {"E_L", "S_L", "S_R"},
    "北进口左转": {"N_L", "N_S", "N_R"},
    "西进口左转": {"W_L", "W_S", "W_R"},
    "东进口直行": {"E_S", "E_R"},
    "东、北放行": {"E_L", "E_S", "E_R", "N_L", "N_S", "N_R"},
    "南放行": {"S_L", "S_S", "S_R"},
    "南北直左": {"N_L", "N_S", "N_R", "S_L", "S_S", "S_R"},
    "东进口左右转": {"E_L", "E_R"},
    "南北直行转向": {"N_L", "N_S", "N_R", "S_L", "S_S", "S_R"},
    "东北、西南放行": {"N_L", "N_S", "N_R", "S_L", "S_S", "S_R"},
    "西北、东南放行": {"E_L", "E_S", "E_R", "W_L", "W_S", "W_R"},
    "东北西南左转直行": {"N_S", "N_R", "S_S", "S_R"},
    "东北西南左转": {"N_L", "S_L"},
    "西北东南左转直行": {"E_S", "E_R", "W_S", "W_R"},
    "西北东南左转": {"E_L", "W_L"},
}
_NON_MOTOR_HIGHWAYS = {
    "bridleway",
    "construction",
    "cycleway",
    "footway",
    "path",
    "pedestrian",
    "platform",
    "proposed",
    "raceway",
    "steps",
}


def evidence_registry_paths(workspace: Path) -> list[Path]:
    """Return checked-in derived evidence files used by automatic configs."""

    root = workspace / "scenarios" / "source" / "official_20_independent"
    return [
        root / "derived_evidence" / "lane_evidence_assessment.json",
        root / "derived_evidence" / "locations_final.json",
        root / "derived_evidence" / "osm_analysis.json",
    ]


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _active_movements(workbook: OfficialWorkbook) -> set[str]:
    return {
        movement
        for movement in MOVEMENTS
        if any(
            profile.movement_totals[movement] > 0
            for profile in workbook.demand_profiles.values()
        )
    }


def _profile_active_movements(workbook: OfficialWorkbook, profile_key: str) -> set[str]:
    profile = workbook.demand_profiles[profile_key]
    return {
        movement for movement in MOVEMENTS if profile.movement_totals[movement] > 0
    }


def _phase_mapping(workbook: OfficialWorkbook) -> dict[str, dict[str, list[str]]]:
    active = _active_movements(workbook)
    mappings: dict[str, dict[str, list[str]]] = {}
    for profile_key, profile in workbook.signal_profiles.items():
        profile_mapping: dict[str, list[str]] = {}
        for phase in profile.phases:
            try:
                candidates = _PHASE_NAME_MOVEMENTS[phase.name]
            except KeyError as exc:
                raise ValueError(f"unsupported organizer phase name {phase.name!r}") from exc
            movements = sorted(active & candidates)
            if phase.green_s and not movements:
                raise ValueError(
                    f"{profile_key} phase {phase.phase_id} {phase.name!r} maps to no movement"
                )
            profile_mapping[phase.phase_id] = movements
        covered = {
            movement for movements in profile_mapping.values() for movement in movements
        }
        missing = _profile_active_movements(workbook, profile_key) - covered
        if missing:
            raise ValueError(
                f"{profile_key} phase names do not cover movements {sorted(missing)}"
            )
        mappings[profile_key] = profile_mapping
    return mappings


def build_evidence_config(
    workspace: Path,
    demo_id: int,
    workbook: OfficialWorkbook,
) -> dict[str, Any]:
    """Build an effective config from checked-in evidence for demos without YAML."""

    lane_path, location_path, osm_analysis_path = evidence_registry_paths(workspace)
    lane_payload = _load_json(lane_path)
    location_payload = _load_json(location_path)
    osm_payload = _load_json(osm_analysis_path)
    lane_evidence = lane_payload["intersections"][str(demo_id)]
    location = next(
        item for item in location_payload["intersections"] if int(item["id"]) == demo_id
    )
    osm_item = next(
        item for item in osm_payload["intersections"] if int(item["id"]) == demo_id
    )
    active = _active_movements(workbook)
    used_arms = {
        movement[0] for movement in active
    } | {_DESTINATION_ARM[movement] for movement in active}
    lane_arms = set(lane_evidence["arms"])
    if used_arms != lane_arms:
        raise ValueError(
            f"demo_{demo_id} lane evidence arms {sorted(lane_arms)} do not match "
            f"Excel movements {sorted(used_arms)}"
        )
    arms = {
        arm: {
            "incoming_lanes": int(lane_evidence["arms"][arm]["incoming"]),
            "outgoing_lanes": int(lane_evidence["arms"][arm]["outgoing"]),
            "speed_m_s": 13.89,
            "priority": 2,
            "road_name": "resolved from geometry evidence",
            "lane_basis": lane_evidence["method"],
            "lane_confidence": lane_evidence["confidence"],
        }
        for arm in sorted(used_arms)
    }
    osm_source = (
        "scenarios/source/official_20_independent/osm/"
        f"demo_{demo_id:02d}_raw.osm.xml"
    )
    geometry_mode = "organizer_official_sumo_reference" if demo_id <= 4 else "osm_auto"
    return {
        "schema_version": "1.0",
        "scenario_id": f"official_demo_{demo_id}",
        "demo_id": demo_id,
        "display_name": f"主办方独立路口 demo_{demo_id}",
        "registration": {
            "longitude": float(location["longitude"]),
            "latitude": float(location["latitude"]),
            "confidence": location["confidence"],
            "method": location["method"],
            "evidence_boundary": location["evidence_boundary"],
        },
        "geometry": {
            "mode": geometry_mode,
            "preferred_osm_node_id": str(osm_item["nearest_candidate"]["node_id"]),
            "preferred_osm_distance_m": float(
                osm_item["nearest_candidate"]["distance_to_registered_center_m"]
            ),
            "reference_note": (
                "demos 1-4 use organizer SUMO arm lengths and lane structure; "
                "demos 5-20 preserve checked-in OSM branch geometry while using a "
                "standard 250 m isolated-intersection simulation boundary"
            ),
        },
        "network_center": {},
        "osm_reference": {
            "source_file": osm_source,
            "matched_node_id": str(osm_item["nearest_candidate"]["node_id"]),
            "nearest_distance_m": float(
                osm_item["nearest_candidate"]["distance_to_registered_center_m"]
            ),
            "ways": osm_item["connected_ways"],
            "evidence_boundary": osm_item["evidence_boundary"],
        },
        "arms": arms,
        "signal_phase_movements": _phase_mapping(workbook),
        "simulation": {
            "demand_duration_s": 7200,
            "clearance_duration_s": 1800,
            "step_length_s": 1.0,
            "seed": demo_id,
        },
        "vehicle_assumption": {
            "pcu_to_vehicle": 1.0,
            "vehicle_type": "passenger",
            "theme_color_hex": "#FFFF00",
            "sumo_color_rgb": [1.0, 1.0, 0.0],
            "color_basis": "user_selected_theme_from_reference_image",
            "evidence_boundary": (
                "organizer workbook supplies PCU but no vehicle-type split; "
                "the model applies the declared 1 PCU = 1 passenger assumption"
            ),
        },
        "gui": {
            "delay_ms": 300,
            "vehicle_visualization": "simple_shapes",
            "vehicle_quality": 2,
            "view_scheme": "competition simple shapes",
        },
        "lane_evidence": lane_evidence,
        "config_provenance": {
            "type": "derived_evidence_registry",
            "registry_files": [
                path.relative_to(workspace).as_posix()
                for path in evidence_registry_paths(workspace)
            ],
        },
    }


def _angle_difference(left: float, right: float) -> float:
    return abs((left - right + 180.0) % 360.0 - 180.0)


def _bearing(start: tuple[float, float], end: tuple[float, float]) -> float:
    forward, _back, _distance = _GEOD.inv(*start, *end)
    return float(forward) % 360.0


def _length(points: list[tuple[float, float]]) -> float:
    return sum(float(_GEOD.inv(*start, *end)[2]) for start, end in pairwise(points))


def _truncate_polyline(
    points: list[tuple[float, float]],
    target_length_m: float,
) -> list[tuple[float, float]]:
    """Cut an OSM polyline at a fixed geodesic distance from its first point."""

    result = [points[0]]
    remaining = target_length_m
    for start, end in pairwise(points):
        forward, _back, segment_length = _GEOD.inv(*start, *end)
        if segment_length <= remaining:
            result.append(end)
            remaining -= float(segment_length)
            continue
        longitude, latitude, _reverse = _GEOD.fwd(*start, forward, remaining)
        result.append((longitude, latitude))
        return result
    return result


def _standardize_polyline(
    points: list[tuple[float, float]],
    target_length_m: float,
) -> list[tuple[float, float]]:
    """Resize an evidence polyline to a common isolated-intersection boundary.

    Long branches retain their OSM shape up to the boundary. Short branches retain
    every evidenced point and continue along the final evidenced bearing. The
    continuation is an explicit simulation-boundary assumption, not map evidence.
    """

    measured_length_m = _length(points)
    if measured_length_m >= target_length_m:
        return _truncate_polyline(points, target_length_m)
    forward, _back, _segment_length = _GEOD.inv(*points[-2], *points[-1])
    longitude, latitude, _reverse = _GEOD.fwd(
        *points[-1],
        forward,
        target_length_m - measured_length_m,
    )
    return [*points, (longitude, latitude)]


def _segment_key(left: str, right: str) -> tuple[str, str]:
    return (left, right) if left <= right else (right, left)


def _assign_neighbors(
    center: tuple[float, float],
    neighbors: dict[str, tuple[float, float]],
    arms: list[str],
) -> tuple[dict[str, str], float] | None:
    if len(neighbors) < len(arms):
        return None
    best: tuple[dict[str, str], float] | None = None
    for selected in permutations(neighbors, len(arms)):
        differences = [
            _angle_difference(
                _bearing(center, neighbors[node_id]),
                _TARGET_BEARINGS[arm],
            )
            for arm, node_id in zip(arms, selected, strict=True)
        ]
        if max(differences) > 75:
            continue
        score = sum(differences)
        assignment = dict(zip(arms, selected, strict=True))
        if best is None or score < best[1]:
            best = assignment, score
    return best


def _load_osm_graph(
    path: Path,
) -> tuple[
    dict[str, tuple[float, float]],
    dict[str, set[str]],
    dict[tuple[str, str], list[str]],
]:
    root = ET.parse(path).getroot()
    nodes = {
        node.get("id", ""): (float(node.get("lon", "0")), float(node.get("lat", "0")))
        for node in root.findall("node")
    }
    adjacency: dict[str, set[str]] = {}
    segment_ways: dict[tuple[str, str], list[str]] = {}
    for way in root.findall("way"):
        tags = {tag.get("k"): tag.get("v") for tag in way.findall("tag")}
        highway = str(tags.get("highway") or "")
        if not highway or highway in _NON_MOTOR_HIGHWAYS:
            continue
        references = [node.get("ref", "") for node in way.findall("nd")]
        for left, right in pairwise(references):
            if left not in nodes or right not in nodes:
                continue
            adjacency.setdefault(left, set()).add(right)
            adjacency.setdefault(right, set()).add(left)
            segment_ways.setdefault(_segment_key(left, right), []).append(
                str(way.get("id"))
            )
    return nodes, adjacency, segment_ways


def _choose_center(
    nodes: dict[str, tuple[float, float]],
    adjacency: dict[str, set[str]],
    registered: tuple[float, float],
    arms: list[str],
    preferred_node_id: str,
) -> tuple[str, dict[str, str], float, float]:
    best: tuple[str, dict[str, str], float, float, float] | None = None
    for node_id, neighbors in adjacency.items():
        if len(neighbors) < len(arms) or node_id not in nodes:
            continue
        distance = _GEOD.inv(*registered, *nodes[node_id])[2]
        if distance > 180:
            continue
        assignment_result = _assign_neighbors(
            nodes[node_id],
            {neighbor: nodes[neighbor] for neighbor in neighbors if neighbor in nodes},
            arms,
        )
        if assignment_result is None:
            continue
        assignment, angle_score = assignment_result
        score = distance + angle_score * 1.5 + max(0, len(neighbors) - len(arms)) * 8
        if node_id == preferred_node_id:
            score -= 25
        candidate = node_id, assignment, distance, angle_score, score
        if best is None or candidate[4] < best[4]:
            best = candidate
    if best is None:
        raise ValueError(
            f"no OSM topology candidate within 180m can represent arms {arms}"
        )
    return best[0], best[1], best[2], best[3]


def _trace_branch(
    center_id: str,
    first_neighbor: str,
    adjacency: dict[str, set[str]],
    *,
    maximum_nodes: int = 1000,
) -> tuple[list[str], str]:
    chain = [center_id, first_neighbor]
    previous = center_id
    current = first_neighbor
    while len(chain) < maximum_nodes:
        neighbors = adjacency.get(current, set())
        if len(neighbors) != 2:
            return chain, "next_osm_topological_junction"
        candidates = [neighbor for neighbor in neighbors if neighbor != previous]
        if len(candidates) != 1 or candidates[0] in chain:
            return chain, "osm_loop_or_ambiguous_branch"
        previous, current = current, candidates[0]
        chain.append(current)
    return chain, "osm_trace_node_limit"


def _official_reference_net(source_root: Path, demo_id: int) -> Path:
    candidates = sorted(
        source_root.joinpath("路口仿真案例").rglob(f"demo_{demo_id}.net.xml")
    )
    if len(candidates) != 1:
        raise ValueError(
            f"demo_{demo_id} must have exactly one organizer reference net; "
            f"found {candidates}"
        )
    return candidates[0]


def _resolve_official_reference_geometry(
    source_root: Path,
    config: dict[str, Any],
) -> tuple[tuple[float, float], dict[str, list[tuple[float, float]]], dict[str, Any]]:
    demo_id = int(config["demo_id"])
    net_path = _official_reference_net(source_root, demo_id)
    root = ET.parse(net_path).getroot()
    junctions = {
        junction.get("id", ""): (
            float(junction.get("x", "0")),
            float(junction.get("y", "0")),
            junction.get("type", ""),
        )
        for junction in root.findall("junction")
        if junction.get("type") != "internal"
    }
    traffic_lights = [
        junction_id
        for junction_id, (_x, _y, kind) in junctions.items()
        if kind == "traffic_light"
    ]
    if len(traffic_lights) != 1:
        raise ValueError(f"organizer demo_{demo_id} must have one traffic light")
    center_id = traffic_lights[0]
    center_xy = junctions[center_id][:2]
    branches: dict[str, dict[str, Any]] = {}
    for edge in root.findall("edge"):
        if edge.get("function") or not edge.findall("lane"):
            continue
        edge_from = edge.get("from", "")
        edge_to = edge.get("to", "")
        if center_id not in {edge_from, edge_to}:
            continue
        boundary_id = edge_to if edge_from == center_id else edge_from
        if boundary_id not in junctions:
            continue
        dx = junctions[boundary_id][0] - center_xy[0]
        dy = junctions[boundary_id][1] - center_xy[1]
        bearing = math.degrees(math.atan2(dx, dy)) % 360.0
        lane_lengths = [float(lane.get("length", "0")) for lane in edge.findall("lane")]
        branch = branches.setdefault(
            boundary_id,
            {"bearing": bearing, "lengths": [], "edge_ids": []},
        )
        branch["lengths"].extend(lane_lengths)
        branch["edge_ids"].append(edge.get("id"))
    arms = sorted(config["arms"], key=lambda arm: _TARGET_BEARINGS[arm])
    assignments = _assign_neighbors(
        (0.0, 0.0),
        {
            boundary_id: (
                math.sin(math.radians(branch["bearing"])),
                math.cos(math.radians(branch["bearing"])),
            )
            for boundary_id, branch in branches.items()
        },
        arms,
    )
    if assignments is None:
        raise ValueError(f"organizer demo_{demo_id} reference geometry cannot map arms")
    arm_boundaries, _score = assignments
    center = (
        float(config["registration"]["longitude"]),
        float(config["registration"]["latitude"]),
    )
    arm_points: dict[str, list[tuple[float, float]]] = {}
    evidence: dict[str, Any] = {}
    for arm, boundary_id in arm_boundaries.items():
        branch = branches[boundary_id]
        length_m = sum(branch["lengths"]) / len(branch["lengths"])
        bearing = float(branch["bearing"])
        endpoint_lon, endpoint_lat, _back = _GEOD.fwd(*center, bearing, length_m)
        arm_points[arm] = [center, (endpoint_lon, endpoint_lat)]
        config["arms"][arm].update(
            {
                "bearing_deg": round(bearing, 2),
                "length_m": round(length_m, 2),
                "length_basis": "organizer_official_sumo_lane_length_mean",
                "length_confidence": "high",
                "cutoff_reason": "organizer_official_sumo_boundary",
            }
        )
        evidence[arm] = {
            "geometry_source": "organizer_official_sumo_reference",
            "reference_net": str(net_path),
            "reference_boundary_junction": boundary_id,
            "reference_edge_ids": sorted(branch["edge_ids"]),
            "measured_length_m": round(length_m, 2),
            "initial_bearing_deg": round(bearing, 2),
            "length_confidence": "high",
            "cutoff_reason": "organizer_official_sumo_boundary",
        }
    config["network_center"] = {
        "longitude": center[0],
        "latitude": center[1],
        "source": "organizer_sumo_geometry_placed_at_registered_center",
        "node_id": center_id,
        "evidence_boundary": (
            "organizer SUMO provides local geometry; geographic placement comes "
            "from image registration and is not a surveyed control point"
        ),
    }
    config["geometry"]["reference_net"] = str(net_path)
    return center, arm_points, evidence


def _resolve_osm_geometry(
    workspace: Path,
    config: dict[str, Any],
) -> tuple[tuple[float, float], dict[str, list[tuple[float, float]]], dict[str, Any]]:
    osm_path = workspace / str(config["osm_reference"]["source_file"])
    nodes, adjacency, segment_ways = _load_osm_graph(osm_path)
    registered = (
        float(config["registration"]["longitude"]),
        float(config["registration"]["latitude"]),
    )
    arms = sorted(config["arms"], key=lambda arm: _TARGET_BEARINGS[arm])
    center_id, assignments, distance, angle_score = _choose_center(
        nodes,
        adjacency,
        registered,
        arms,
        str(config["geometry"]["preferred_osm_node_id"]),
    )
    center = nodes[center_id]
    arm_points: dict[str, list[tuple[float, float]]] = {}
    evidence: dict[str, Any] = {}
    for arm, first_neighbor in assignments.items():
        chain, cutoff_reason = _trace_branch(center_id, first_neighbor, adjacency)
        evidence_points = [nodes[node_id] for node_id in chain]
        evidence_length_m = _length(evidence_points)
        bearing = _bearing(evidence_points[0], evidence_points[1])
        points = _standardize_polyline(
            evidence_points,
            _STANDARD_STANDALONE_ARM_M,
        )
        modeled_length_m = _STANDARD_STANDALONE_ARM_M
        modeling_adjustment: dict[str, Any] = {
            "type": "standardized_isolated_intersection_boundary",
            "reason": (
                "OSM distance to the next topology node is retained as evidence, "
                "while every organizer-derived standalone arm uses the same 250 m "
                "simulation boundary for comparable storage and GUI scale"
            ),
            "geometry_policy": (
                "truncate along the evidenced OSM polyline when longer than 250 m; "
                "extend along the final evidenced bearing when shorter than 250 m"
            ),
            "evidence_length_m": round(evidence_length_m, 2),
            "modeled_length_m": _STANDARD_STANDALONE_ARM_M,
        }
        way_ids = sorted(
            {
                way_id
                for left, right in pairwise(chain)
                for way_id in segment_ways.get(_segment_key(left, right), [])
            }
        )
        arm_points[arm] = points
        config["arms"][arm].update(
            {
                "bearing_deg": round(bearing, 2),
                "length_m": round(modeled_length_m, 2),
                "evidence_length_m": round(evidence_length_m, 2),
                "osm_node_chain": chain,
                "cutoff_node_id": chain[-1],
                "cutoff_reason": cutoff_reason,
                "length_basis": "geodesic_sum_along_osm_node_chain",
                "length_confidence": "high" if cutoff_reason.startswith("next_") else "medium",
                "osm_way_ids": way_ids,
                "modeling_adjustment": modeling_adjustment,
            }
        )
        evidence[arm] = {
            "geometry_source": "checked_in_osm_extract",
            "osm_node_chain": chain,
            "osm_way_ids": way_ids,
            "cutoff_node_id": chain[-1],
            "cutoff_reason": cutoff_reason,
            "length_basis": "geodesic_sum_along_osm_node_chain",
            "measured_length_m": round(evidence_length_m, 2),
            "modeled_length_m": round(modeled_length_m, 2),
            "initial_bearing_deg": round(bearing, 2),
            "length_confidence": config["arms"][arm]["length_confidence"],
            "modeling_adjustment": modeling_adjustment,
        }
    config["network_center"] = {
        "longitude": center[0],
        "latitude": center[1],
        "source": "osm_topology_candidate",
        "node_id": center_id,
        "distance_to_registered_center_m": round(distance, 2),
        "assignment_angle_error_sum_deg": round(angle_score, 2),
        "evidence_boundary": "OSM community geometry, not a surveyed control point",
    }
    config["osm_reference"]["matched_node_id"] = center_id
    config["osm_reference"]["nearest_distance_m"] = round(distance, 2)
    return center, arm_points, evidence


def resolve_evidence_geometry(
    workspace: Path,
    source_root: Path,
    config: dict[str, Any],
) -> tuple[tuple[float, float], dict[str, list[tuple[float, float]]], dict[str, Any]]:
    """Resolve either organizer-reference or OSM-derived arm geometry."""

    mode = str(config.get("geometry", {}).get("mode", ""))
    if mode == "organizer_official_sumo_reference":
        return _resolve_official_reference_geometry(source_root, config)
    if mode == "osm_auto":
        return _resolve_osm_geometry(workspace, config)
    raise ValueError(f"unsupported evidence geometry mode {mode!r}")
