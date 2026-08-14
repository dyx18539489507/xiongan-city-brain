"""Build a traceable lane, movement, signal and provenance inventory."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

_TURN_NAMES = {
    "s": "straight",
    "l": "left",
    "L": "partial_left",
    "r": "right",
    "R": "partial_right",
    "t": "uturn",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cardinal(dx: float, dy: float) -> str:
    """Return the eight-point direction from one XY vector."""

    if abs(dx) + abs(dy) < 1e-9:
        return "UNKNOWN"
    angle = (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0
    names = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
    return names[int((angle + 22.5) // 45.0) % 8]


def _lane_payload(lane: ET.Element) -> dict[str, Any]:
    allow = lane.get("allow", "")
    disallow = lane.get("disallow", "")
    return {
        "lane_id": lane.attrib["id"],
        "index": int(lane.get("index", "0")),
        "speed_m_s": round(float(lane.get("speed", "0")), 3),
        "length_m": round(float(lane.get("length", "0")), 3),
        "allow": allow.split() if allow else ["all_default_classes"],
        "disallow": disallow.split() if disallow else [],
    }


def _edge_payload(
    edge: ET.Element,
    *,
    node_id: str,
    junctions: dict[str, tuple[float, float]],
    incoming: bool,
) -> dict[str, Any]:
    other_id = edge.get("from") if incoming else edge.get("to")
    center = junctions.get(node_id, (0.0, 0.0))
    other = junctions.get(str(other_id), center)
    direction = _cardinal(other[0] - center[0], other[1] - center[1])
    name = edge.get("name", "").strip()
    lanes = [_lane_payload(lane) for lane in edge.findall("lane")]
    return {
        "edge_id": edge.attrib["id"],
        "road_name": name or f"未命名OSM道路({edge.attrib['id']})",
        "road_name_provenance": "osm" if name else "osm_name_missing_fallback",
        "direction": direction,
        "lane_count": len(lanes),
        "lanes": lanes,
    }


def build_intersection_inventory(
    *,
    net_file: Path,
    selection_file: Path,
    parameter_file: Path,
) -> dict[str, Any]:
    """Return a deterministic inventory for the twenty controlled junctions."""

    selection = json.loads(selection_file.read_text(encoding="utf-8"))
    parameters = json.loads(parameter_file.read_text(encoding="utf-8"))
    root = ET.parse(net_file).getroot()
    junctions = {
        item.attrib["id"]: (
            float(item.get("x", "0")),
            float(item.get("y", "0")),
        )
        for item in root.findall("junction")
    }
    edges = {
        edge.attrib["id"]: edge
        for edge in root.findall("edge")
        if edge.get("function") != "internal"
    }
    incoming_by_node: dict[str, list[ET.Element]] = {}
    outgoing_by_node: dict[str, list[ET.Element]] = {}
    for edge in edges.values():
        incoming_by_node.setdefault(str(edge.get("to")), []).append(edge)
        outgoing_by_node.setdefault(str(edge.get("from")), []).append(edge)
    connections_by_node: dict[str, list[dict[str, Any]]] = {}
    for connection in root.findall("connection"):
        from_edge = edges.get(str(connection.get("from")))
        to_edge = edges.get(str(connection.get("to")))
        if from_edge is None or to_edge is None:
            continue
        node_id = str(from_edge.get("to"))
        if node_id != str(to_edge.get("from")):
            continue
        turn_code = connection.get("dir", "")
        connections_by_node.setdefault(node_id, []).append(
            {
                "from_edge": from_edge.attrib["id"],
                "from_lane_index": int(connection.get("fromLane", "0")),
                "to_edge": to_edge.attrib["id"],
                "to_lane_index": int(connection.get("toLane", "0")),
                "movement": _TURN_NAMES.get(turn_code, turn_code or "unknown"),
                "traffic_light_id": connection.get("tl"),
                "controlled_link_index": (
                    int(connection.attrib["linkIndex"])
                    if "linkIndex" in connection.attrib
                    else None
                ),
            }
        )
    programs: dict[str, list[dict[str, Any]]] = {}
    for logic in root.findall("tlLogic"):
        programs.setdefault(logic.attrib["id"], []).append(
            {
                "program_id": logic.get("programID", "0"),
                "type": logic.get("type", "static"),
                "offset_s": float(logic.get("offset", "0")),
                "cycle_s": round(
                    sum(float(phase.get("duration", "0")) for phase in logic.findall("phase")),
                    3,
                ),
                "phases": [
                    {
                        "phase_index": index,
                        "duration_s": float(phase.get("duration", "0")),
                        "state": phase.get("state", ""),
                        "contains_yellow": "y" in phase.get("state", "").lower(),
                        "all_red": set(phase.get("state", "").lower()) <= {"r"},
                    }
                    for index, phase in enumerate(logic.findall("phase"))
                ],
            }
        )
    topology_neighbors: dict[str, list[dict[str, Any]]] = {}
    display_by_sumo = {
        str(item["intersection_id"]): str(item["display_id"])
        for item in selection["intersections"]
    }
    for edge in selection["topology_edges"]:
        left = str(edge["source"])
        right = str(edge["target"])
        distance = float(edge["road_distance_m"])
        topology_neighbors.setdefault(left, []).append(
            {"display_id": display_by_sumo[right], "sumo_junction_id": right, "distance_m": distance}
        )
        topology_neighbors.setdefault(right, []).append(
            {"display_id": display_by_sumo[left], "sumo_junction_id": left, "distance_m": distance}
        )
    intersections: list[dict[str, Any]] = []
    for selected in sorted(
        selection["intersections"], key=lambda item: str(item["display_id"])
    ):
        node_id = str(selected["intersection_id"])
        parameter = parameters["intersections"][node_id]
        incoming = sorted(
            (
                _edge_payload(edge, node_id=node_id, junctions=junctions, incoming=True)
                for edge in incoming_by_node.get(node_id, [])
            ),
            key=lambda item: (item["direction"], item["edge_id"]),
        )
        outgoing = sorted(
            (
                _edge_payload(edge, node_id=node_id, junctions=junctions, incoming=False)
                for edge in outgoing_by_node.get(node_id, [])
            ),
            key=lambda item: (item["direction"], item["edge_id"]),
        )
        intersections.append(
            {
                "display_id": selected["display_id"],
                "display_name": selected["display_name"],
                "sumo_junction_id": node_id,
                "official_anchor": selected.get("location_anchor"),
                "role": selected["role"],
                "control_group": selected["control_group"],
                "coordinates": {
                    "x_m": selected["x"],
                    "y_m": selected["y"],
                    "longitude": selected["lon"],
                    "latitude": selected["lat"],
                },
                "topology_neighbors": sorted(
                    topology_neighbors.get(node_id, []),
                    key=lambda item: item["display_id"],
                ),
                "junction_type": selected["original_sumo_junction_type"],
                "incoming_approaches": incoming,
                "outgoing_approaches": outgoing,
                "movements": sorted(
                    connections_by_node.get(node_id, []),
                    key=lambda item: (
                        item["from_edge"],
                        item["from_lane_index"],
                        item["to_edge"],
                    ),
                ),
                "signal_programs": programs.get(node_id, []),
                "parameter_provenance": parameter["parameter_provenance"],
                "parameter_donors": parameter["donors"],
                "demand_and_timing": {
                    "raw_peak_flow_veh_h": parameter["raw_peak_flow_veh_h"],
                    "balanced_peak_flow_veh_h": parameter["balanced_peak_flow_veh_h"],
                    "turn_ratios": parameter["turn_ratios"],
                    "donor_cycle_s": parameter["donor_cycle_s"],
                    "recommended_cycle_s": parameter["recommended_cycle_s"],
                },
            }
        )
    return {
        "schema_version": "1.0",
        "scenario_id": "xiongan_rongdong_20",
        "network_scope": "complete_rongdong_osm_network_not_cropped",
        "controlled_inventory_scope": "twenty_controlled_intersections",
        "evidence_boundary": (
            "OSM topology plus organizer-derived and mathematically transferred "
            "parameters; not field-calibrated or survey-grade."
        ),
        "source_files": [
            {"path": str(net_file), "sha256": _sha256(net_file)},
            {"path": str(selection_file), "sha256": _sha256(selection_file)},
            {"path": str(parameter_file), "sha256": _sha256(parameter_file)},
        ],
        "intersection_count": len(intersections),
        "intersections": intersections,
    }


def write_intersection_inventory(
    payload: dict[str, Any],
    *,
    json_file: Path,
    csv_file: Path,
) -> None:
    """Write machine-readable detail plus a compact human-readable index."""

    json_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with csv_file.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(
            target,
            fieldnames=[
                "display_id",
                "sumo_junction_id",
                "official_anchor",
                "role",
                "neighbor_ids",
                "incoming_approaches",
                "incoming_lanes",
                "movement_count",
                "signal_program_count",
                "parameter_provenance",
            ],
        )
        writer.writeheader()
        for item in payload["intersections"]:
            writer.writerow(
                {
                    "display_id": item["display_id"],
                    "sumo_junction_id": item["sumo_junction_id"],
                    "official_anchor": item["official_anchor"] or "",
                    "role": item["role"],
                    "neighbor_ids": ",".join(
                        neighbor["display_id"] for neighbor in item["topology_neighbors"]
                    ),
                    "incoming_approaches": len(item["incoming_approaches"]),
                    "incoming_lanes": sum(
                        approach["lane_count"] for approach in item["incoming_approaches"]
                    ),
                    "movement_count": len(item["movements"]),
                    "signal_program_count": len(item["signal_programs"]),
                    "parameter_provenance": item["parameter_provenance"],
                }
            )
