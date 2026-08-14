# ruff: noqa: RUF001
"""Build evidence-traceable standalone SUMO projects for organizer intersections."""

import json
import math
import subprocess
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from itertools import pairwise
from pathlib import Path
from typing import Any, cast

import yaml
from pyproj import Geod

from traffic_platform.scenario_engine.manifest import git_revision, sha256_file
from traffic_platform.scenario_engine.official_evidence import (
    build_evidence_config,
    evidence_registry_paths,
    resolve_evidence_geometry,
)
from traffic_platform.scenario_engine.official_models import (
    MOVEMENTS,
    DemandProfile,
    OfficialWorkbook,
    SignalProfile,
)
from traffic_platform.scenario_engine.official_workbook import parse_official_workbook

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
_PROFILE_ORDER = ("am_peak", "offpeak", "pm_peak")
_GEOD = Geod(ellps="WGS84")
_STANDARD_STANDALONE_ARM_M = 250.0


class OfficialBuildError(RuntimeError):
    """Raised when a generated project fails an evidence or SUMO gate."""


def _write_xml(root: ET.Element, path: Path) -> None:
    ET.indent(root, space="    ")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def _sumo_binary(sumo_home: Path, name: str) -> Path:
    suffix = ".exe" if sys.platform == "win32" else ""
    binary = sumo_home / "bin" / f"{name}{suffix}"
    if not binary.is_file():
        raise FileNotFoundError(binary)
    return binary


def _run(command: list[str], *, cwd: Path, timeout_s: int = 300) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_s,
    )
    if completed.returncode != 0:
        raise OfficialBuildError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed


def _load_config(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise OfficialBuildError(f"{path} must contain a YAML mapping")
    required = {
        "schema_version",
        "scenario_id",
        "demo_id",
        "registration",
        "network_center",
        "osm_reference",
        "arms",
        "signal_phase_movements",
        "simulation",
        "vehicle_assumption",
        "gui",
    }
    missing = required - data.keys()
    if missing:
        raise OfficialBuildError(f"{path} is missing keys: {sorted(missing)}")
    if int(data["demo_id"]) <= 0 or not isinstance(data["arms"], dict):
        raise OfficialBuildError(f"invalid demo_id or arms in {path}")
    return data


def _load_osm_nodes(path: Path) -> dict[str, tuple[float, float]]:
    """Load OSM node coordinates as longitude/latitude pairs."""

    if not path.is_file():
        raise FileNotFoundError(path)
    nodes: dict[str, tuple[float, float]] = {}
    for _event, element in ET.iterparse(path, events=("end",)):
        if element.tag == "node":
            nodes[element.attrib["id"]] = (
                float(element.attrib["lon"]),
                float(element.attrib["lat"]),
            )
        element.clear()
    return nodes


def _angle_difference(left: float, right: float) -> float:
    return abs((left - right + 180.0) % 360.0 - 180.0)


def _truncate_polyline(
    points: list[tuple[float, float]],
    target_length_m: float,
) -> list[tuple[float, float]]:
    """Cut a geodesic polyline while preserving its OSM shape up to the boundary."""

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
    """Resize a polyline to a common standalone simulation boundary."""

    measured_length_m = sum(
        float(_GEOD.inv(*start, *end)[2]) for start, end in pairwise(points)
    )
    if measured_length_m >= target_length_m:
        return _truncate_polyline(points, target_length_m)
    forward, _back, _segment_length = _GEOD.inv(*points[-2], *points[-1])
    longitude, latitude, _reverse = _GEOD.fwd(
        *points[-1],
        forward,
        target_length_m - measured_length_m,
    )
    return [*points, (longitude, latitude)]


def _resolve_osm_geometry(
    workspace: Path,
    config: dict[str, Any],
) -> tuple[tuple[float, float], dict[str, list[tuple[float, float]]], dict[str, Any]]:
    """Resolve and verify each modeled arm against an explicit OSM node chain."""

    osm_path = workspace / str(config["osm_reference"]["source_file"])
    osm_nodes = _load_osm_nodes(osm_path)
    center_config = config["network_center"]
    center_node_id = str(center_config["node_id"])
    try:
        center = osm_nodes[center_node_id]
    except KeyError as exc:
        raise OfficialBuildError(f"OSM center node {center_node_id} is absent") from exc
    declared_center = (
        float(center_config["longitude"]),
        float(center_config["latitude"]),
    )
    if max(abs(center[index] - declared_center[index]) for index in (0, 1)) > 1e-7:
        raise OfficialBuildError("declared network center does not match the OSM node")

    arm_points: dict[str, list[tuple[float, float]]] = {}
    evidence: dict[str, Any] = {}
    for arm_id, arm in config["arms"].items():
        chain = [str(node_id) for node_id in arm.get("osm_node_chain", [])]
        if len(chain) < 2 or chain[0] != center_node_id:
            raise OfficialBuildError(
                f"arm {arm_id} must start at {center_node_id} and contain a cutoff node"
            )
        if chain[-1] != str(arm.get("cutoff_node_id")):
            raise OfficialBuildError(f"arm {arm_id} cutoff does not match its OSM chain")
        missing = [node_id for node_id in chain if node_id not in osm_nodes]
        if missing:
            raise OfficialBuildError(f"arm {arm_id} has missing OSM nodes: {missing}")
        points = [osm_nodes[node_id] for node_id in chain]
        measured_length = 0.0
        for start, end in pairwise(points):
            _forward, _back, distance = _GEOD.inv(*start, *end)
            measured_length += distance
        first_bearing, _back, _distance = _GEOD.inv(*points[0], *points[1])
        first_bearing %= 360.0
        if abs(measured_length - float(arm["length_m"])) > 0.1:
            raise OfficialBuildError(
                f"arm {arm_id} measures {measured_length:.2f}m, "
                f"not declared {float(arm['length_m']):.2f}m"
            )
        if _angle_difference(first_bearing, float(arm["bearing_deg"])) > 0.1:
            raise OfficialBuildError(
                f"arm {arm_id} bearing is {first_bearing:.2f} degrees, "
                f"not declared {float(arm['bearing_deg']):.2f}"
            )
        points = _standardize_polyline(points, _STANDARD_STANDALONE_ARM_M)
        modeled_length = _STANDARD_STANDALONE_ARM_M
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
            "evidence_length_m": round(measured_length, 2),
            "modeled_length_m": _STANDARD_STANDALONE_ARM_M,
        }
        arm["evidence_length_m"] = round(measured_length, 2)
        arm["length_m"] = _STANDARD_STANDALONE_ARM_M
        arm["modeling_adjustment"] = modeling_adjustment
        arm_points[str(arm_id)] = points
        evidence[str(arm_id)] = {
            "osm_node_chain": chain,
            "cutoff_node_id": chain[-1],
            "cutoff_reason": arm["cutoff_reason"],
            "length_basis": arm["length_basis"],
            "measured_length_m": round(measured_length, 2),
            "modeled_length_m": round(modeled_length, 2),
            "initial_bearing_deg": round(first_bearing, 2),
            "length_confidence": arm["length_confidence"],
            "modeling_adjustment": modeling_adjustment,
        }
    return center, arm_points, evidence


def _find_organizer_sources(source_root: Path, demo_id: int) -> tuple[Path, Path]:
    demo_root = source_root / "路口数据" / str(demo_id)
    workbooks = sorted(
        path for path in demo_root.rglob("*.xlsx") if not path.name.startswith("~$")
    )
    maps = sorted(demo_root.rglob("*.png"))
    if len(workbooks) != 1 or len(maps) != 1:
        raise OfficialBuildError(
            f"demo_{demo_id} must have exactly one workbook and one PNG; "
            f"found {len(workbooks)} and {len(maps)} under {demo_root}"
        )
    return workbooks[0], maps[0]


def _active_movements(workbook: OfficialWorkbook) -> set[str]:
    return {
        movement
        for movement in MOVEMENTS
        if any(
            profile.movement_totals[movement] > 0
            for profile in workbook.demand_profiles.values()
        )
    }


def _validate_movement_evidence(config: dict[str, Any], workbook: OfficialWorkbook) -> set[str]:
    active = _active_movements(workbook)
    arms = set(config["arms"])
    invalid_sources = {movement for movement in active if movement[0] not in arms}
    invalid_destinations = {
        movement for movement in active if _DESTINATION_ARM[movement] not in arms
    }
    if invalid_sources or invalid_destinations:
        raise OfficialBuildError(
            f"active movements do not fit configured topology; sources={sorted(invalid_sources)}, "
            f"destinations={sorted(invalid_destinations)}"
        )
    mapping_config = config["signal_phase_movements"]
    if set(mapping_config).issubset(set(_PROFILE_ORDER)):
        profile_mappings = {
            key: mapping_config[key] for key in _PROFILE_ORDER
        }
    else:
        profile_mappings = {key: mapping_config for key in _PROFILE_ORDER}
    mapped = {
        str(movement)
        for profile_mapping in profile_mappings.values()
        for movements in profile_mapping.values()
        for movement in movements
    }
    if active - mapped:
        raise OfficialBuildError(f"active movements lack signal mapping: {sorted(active - mapped)}")
    if mapped - active:
        raise OfficialBuildError(f"signal mapping contains inactive movements: {sorted(mapped - active)}")
    for key, profile in workbook.demand_profiles.items():
        profile_active = {
            movement
            for movement in MOVEMENTS
            if profile.movement_totals[movement] > 0
        }
        profile_mapped = {
            str(movement)
            for movements in profile_mappings[key].values()
            for movement in movements
        }
        if profile_active - profile_mapped:
            raise OfficialBuildError(
                f"{key} signal mapping misses active movements: "
                f"{sorted(profile_active - profile_mapped)}"
            )
    return active


def _profile_signal_mapping(
    config: dict[str, Any],
    profile_key: str,
) -> dict[str, list[str]]:
    mapping_config = config["signal_phase_movements"]
    if profile_key in mapping_config and isinstance(mapping_config[profile_key], dict):
        return cast(dict[str, list[str]], mapping_config[profile_key])
    return cast(dict[str, list[str]], mapping_config)


def _movement_lanes(
    movement: str,
    *,
    active: set[str],
    arms: dict[str, dict[str, Any]],
) -> list[int]:
    source, turn = movement.split("_")
    lane_count = int(arms[source]["incoming_lanes"])
    turns = {candidate[-1] for candidate in active if candidate.startswith(f"{source}_")}
    if lane_count == 1:
        return [0]
    if turn == "R":
        return [0]
    if turn == "L":
        return [lane_count - 1]
    reserved = ({0} if "R" in turns else set()) | (
        {lane_count - 1} if "L" in turns else set()
    )
    straight_lanes = [lane for lane in range(lane_count) if lane not in reserved]
    return straight_lanes or list(range(lane_count))


def _write_plain_network(
    output: Path,
    config: dict[str, Any],
    active: set[str],
    center: tuple[float, float],
    arm_points: dict[str, list[tuple[float, float]]],
) -> tuple[Path, Path, Path]:
    longitude, latitude = center
    arms: dict[str, dict[str, Any]] = config["arms"]

    nodes = ET.Element("nodes")
    ET.SubElement(
        nodes,
        "node",
        id="J",
        x=f"{longitude:.8f}",
        y=f"{latitude:.8f}",
        type="traffic_light",
    )
    for arm_id in arms:
        lon, lat = arm_points[arm_id][-1]
        ET.SubElement(
            nodes,
            "node",
            id=f"B_{arm_id}",
            x=f"{lon:.8f}",
            y=f"{lat:.8f}",
            type="priority",
        )
    node_path = output / "network.nod.xml"
    _write_xml(nodes, node_path)

    edges = ET.Element("edges")
    for arm_id, arm in arms.items():
        common: dict[str, str] = {
            "priority": str(int(arm["priority"])),
            "speed": f"{float(arm['speed_m_s']):.2f}",
        }
        ET.SubElement(
            edges,
            "edge",
            {
                "id": f"in_{arm_id}",
                **common,
                "from": f"B_{arm_id}",
                "to": "J",
                "numLanes": str(int(arm["incoming_lanes"])),
                "shape": " ".join(
                    f"{lon:.8f},{lat:.8f}" for lon, lat in reversed(arm_points[arm_id])
                ),
            },
        )
        ET.SubElement(
            edges,
            "edge",
            {
                "id": f"out_{arm_id}",
                **common,
                "from": "J",
                "to": f"B_{arm_id}",
                "numLanes": str(int(arm["outgoing_lanes"])),
                "shape": " ".join(
                    f"{lon:.8f},{lat:.8f}" for lon, lat in arm_points[arm_id]
                ),
            },
        )
    edge_path = output / "network.edg.xml"
    _write_xml(edges, edge_path)

    connections = ET.Element("connections")
    for movement in sorted(active):
        source = movement[0]
        destination = _DESTINATION_ARM[movement]
        destination_lanes = int(arms[destination]["outgoing_lanes"])
        for source_lane in _movement_lanes(movement, active=active, arms=arms):
            if movement.endswith("_L"):
                destination_lane = destination_lanes - 1
            elif movement.endswith("_R"):
                destination_lane = 0
            else:
                destination_lane = min(source_lane, destination_lanes - 1)
            ET.SubElement(
                connections,
                "connection",
                {
                    "from": f"in_{source}",
                    "to": f"out_{destination}",
                    "fromLane": str(source_lane),
                    "toLane": str(destination_lane),
                },
            )
    connection_path = output / "network.con.xml"
    _write_xml(connections, connection_path)
    return node_path, edge_path, connection_path


def _create_base_network(
    output: Path,
    sumo_home: Path,
    paths: tuple[Path, Path, Path],
) -> Path:
    node_path, edge_path, connection_path = paths
    net_path = output / "network.base.net.xml"
    _run(
        [
            str(_sumo_binary(sumo_home, "netconvert")),
            "--node-files",
            str(node_path),
            "--edge-files",
            str(edge_path),
            "--connection-files",
            str(connection_path),
            "--output-file",
            str(net_path),
            "--proj.utm",
            "true",
            "--no-turnarounds",
            "true",
            "--junctions.corner-detail",
            "8",
            "--tls.yellow.time",
            "3",
            "--tls.allred.time",
            "0",
        ],
        cwd=output,
    )
    return net_path


def _record_sumo_effective_lengths(
    net_path: Path,
    arm_geometry: dict[str, Any],
) -> None:
    """Attach netconvert lane lengths without confusing them with OSM lengths."""

    root = ET.parse(net_path).getroot()
    by_edge = {edge.get("id"): edge for edge in root.findall("edge")}
    for arm_id, evidence in arm_geometry.items():
        effective: dict[str, float] = {}
        for direction in ("in", "out"):
            edge = by_edge.get(f"{direction}_{arm_id}")
            lane = edge.find("lane") if edge is not None else None
            if lane is None or lane.get("length") is None:
                raise OfficialBuildError(f"SUMO edge {direction}_{arm_id} has no lane length")
            effective[direction] = round(float(lane.get("length", "0")), 2)
        evidence["sumo_effective_lane_length_m"] = effective


def _link_indices(net_path: Path, active: set[str]) -> tuple[dict[str, list[int]], int]:
    root = ET.parse(net_path).getroot()
    result: dict[str, list[int]] = {movement: [] for movement in active}
    edge_to_movement = {
        (f"in_{movement[0]}", f"out_{_DESTINATION_ARM[movement]}"): movement
        for movement in active
    }
    maximum = -1
    for connection in root.findall("connection"):
        if connection.get("tl") != "J" or connection.get("linkIndex") is None:
            continue
        index = int(connection.get("linkIndex", "-1"))
        maximum = max(maximum, index)
        movement = edge_to_movement.get((connection.get("from", ""), connection.get("to", "")))
        if movement is None:
            continue
        result[movement].append(index)
    missing = [movement for movement, indices in result.items() if not indices]
    if missing or maximum < 0:
        raise OfficialBuildError(f"SUMO network lacks controlled links for {missing}")
    return result, maximum + 1


def _signal_logic(
    profile: SignalProfile,
    *,
    config: dict[str, Any],
    link_indices: dict[str, list[int]],
    state_length: int,
) -> ET.Element:
    logic = ET.Element(
        "tlLogic",
        id="J",
        type="static",
        programID=profile.key,
        offset="0",
    )
    phase_mapping = _profile_signal_mapping(config, profile.key)
    for official_phase in profile.phases:
        movement_ids = set(phase_mapping.get(official_phase.phase_id, []))
        green_state = ["r"] * state_length
        for movement in movement_ids:
            for index in link_indices[str(movement)]:
                green_state[index] = "g"
        if official_phase.green_s:
            ET.SubElement(
                logic,
                "phase",
                duration=str(official_phase.green_s),
                state="".join(green_state),
                name=f"P{official_phase.phase_id} {official_phase.name}",
            )
        if official_phase.yellow_s:
            ET.SubElement(
                logic,
                "phase",
                duration=str(official_phase.yellow_s),
                state="".join("y" if state == "g" else "r" for state in green_state),
                name=f"P{official_phase.phase_id} yellow",
            )
        if official_phase.all_red_s:
            ET.SubElement(
                logic,
                "phase",
                duration=str(official_phase.all_red_s),
                state="r" * state_length,
                name=f"P{official_phase.phase_id} all-red",
            )
    return logic


def _write_profile_network(
    base_net: Path,
    output: Path,
    profile: SignalProfile,
    *,
    config: dict[str, Any],
    link_indices: dict[str, list[int]],
    state_length: int,
) -> tuple[Path, Path]:
    tree = ET.parse(base_net)
    root = tree.getroot()
    for existing in list(root.findall("tlLogic")):
        if existing.get("id") == "J":
            root.remove(existing)
    logic = _signal_logic(
        profile,
        config=config,
        link_indices=link_indices,
        state_length=state_length,
    )
    insert_at = next(
        (index for index, element in enumerate(root) if element.tag == "junction"),
        len(root),
    )
    root.insert(insert_at, logic)
    net_path = output / f"demo_{config['demo_id']}_{profile.key}.net.xml"
    ET.indent(root, space="    ")
    tree.write(net_path, encoding="utf-8", xml_declaration=True)

    additional = ET.Element("additional")
    additional.append(
        _signal_logic(
            profile,
            config=config,
            link_indices=link_indices,
            state_length=state_length,
        )
    )
    signal_path = output / f"demo_{config['demo_id']}_{profile.key}.signal.add.xml"
    _write_xml(additional, signal_path)
    return net_path, signal_path


def _write_routes(
    output: Path,
    config: dict[str, Any],
    profile: DemandProfile,
    active: set[str],
) -> Path:
    routes = ET.Element("routes")
    color_values = config["vehicle_assumption"]["sumo_color_rgb"]
    if (
        not isinstance(color_values, list)
        or len(color_values) != 3
        or any(float(value) < 0 or float(value) > 1 for value in color_values)
    ):
        raise OfficialBuildError("sumo_color_rgb must contain three values between 0 and 1")
    color = ",".join(f"{float(value):g}" for value in color_values)
    ET.SubElement(
        routes,
        "vType",
        id="passenger",
        vClass="passenger",
        accel="2.6",
        decel="4.5",
        sigma="0.5",
        length="5.0",
        minGap="2.5",
        color=color,
    )
    for movement in sorted(active):
        ET.SubElement(
            routes,
            "route",
            id=movement,
            edges=f"in_{movement[0]} out_{_DESTINATION_ARM[movement]}",
        )
    for interval_index, interval in enumerate(profile.intervals, start=1):
        for movement in sorted(active):
            count = interval.counts[movement]
            if count <= 0:
                continue
            ET.SubElement(
                routes,
                "flow",
                id=f"{profile.key}_{interval_index:02d}_{movement}",
                type="passenger",
                route=movement,
                begin=str(interval.begin_s),
                end=str(interval.end_s),
                number=str(count),
                departLane="best",
                departSpeed="max",
            )
    path = output / f"demo_{config['demo_id']}_{profile.key}.rou.xml"
    _write_xml(routes, path)
    return path


def _write_sumocfg(
    output: Path,
    config: dict[str, Any],
    profile_key: str,
    net_path: Path,
    route_path: Path,
    view_settings_path: Path,
) -> Path:
    output_folder = output / "outputs" / profile_key
    output_folder.mkdir(parents=True, exist_ok=True)
    root = ET.Element("configuration")
    input_node = ET.SubElement(root, "input")
    ET.SubElement(input_node, "net-file", value=net_path.name)
    ET.SubElement(input_node, "route-files", value=route_path.name)
    ET.SubElement(input_node, "gui-settings-file", value=view_settings_path.name)
    time_node = ET.SubElement(root, "time")
    ET.SubElement(time_node, "begin", value="0")
    total_time = int(config["simulation"]["demand_duration_s"]) + int(
        config["simulation"]["clearance_duration_s"]
    )
    ET.SubElement(time_node, "end", value=str(total_time))
    ET.SubElement(time_node, "step-length", value=str(config["simulation"]["step_length_s"]))
    processing = ET.SubElement(root, "processing")
    ET.SubElement(processing, "time-to-teleport", value="-1")
    ET.SubElement(processing, "collision.action", value="warn")
    report = ET.SubElement(root, "report")
    ET.SubElement(report, "no-step-log", value="true")
    ET.SubElement(report, "duration-log.statistics", value="true")
    output_node = ET.SubElement(root, "output")
    prefix = f"outputs/{profile_key}"
    ET.SubElement(output_node, "summary-output", value=f"{prefix}/summary.xml")
    ET.SubElement(output_node, "tripinfo-output", value=f"{prefix}/tripinfo.xml")
    ET.SubElement(output_node, "statistic-output", value=f"{prefix}/statistics.xml")
    ET.SubElement(output_node, "vehroute-output", value=f"{prefix}/vehroute.xml")
    random = ET.SubElement(root, "random_number")
    ET.SubElement(random, "seed", value=str(config["simulation"]["seed"]))
    gui = ET.SubElement(root, "gui_only")
    ET.SubElement(gui, "delay", value=str(int(config["gui"]["delay_ms"])))
    path = output / f"demo_{config['demo_id']}_{profile_key}.sumocfg"
    _write_xml(root, path)
    return path


def _write_gui_settings(output: Path, config: dict[str, Any]) -> Path:
    """Persist the requested SUMO-GUI vehicle renderer with the scenario."""

    gui_config = config["gui"]
    vehicle_visualization = str(gui_config.get("vehicle_visualization", ""))
    vehicle_quality = int(gui_config.get("vehicle_quality", -1))
    if vehicle_visualization != "simple_shapes" or vehicle_quality != 2:
        raise OfficialBuildError(
            "official GUI config must use vehicle_visualization=simple_shapes "
            "and vehicle_quality=2"
        )
    root = ET.Element("viewsettings")
    scheme = ET.SubElement(
        root,
        "scheme",
        name=str(gui_config.get("view_scheme", "competition simple shapes")),
    )
    ET.SubElement(
        scheme,
        "vehicles",
        vehicleQuality=str(vehicle_quality),
        vehicle_exaggeration="1",
        vehicle_constantSize="0",
    )
    path = output / "simple-shapes.view.xml"
    _write_xml(root, path)
    return path


def _write_preview(output: Path, config: dict[str, Any], workbook: OfficialWorkbook) -> Path:
    width, height = 1000, 760
    center_x, center_y = 500.0, 390.0
    scale = 0.58
    arms: dict[str, dict[str, Any]] = config["arms"]
    endpoints: dict[str, tuple[float, float]] = {}
    for arm_id, arm in arms.items():
        bearing = math.radians(float(arm["bearing_deg"]))
        length = min(float(arm["length_m"]), 520.0) * scale
        endpoints[arm_id] = (
            center_x + math.sin(bearing) * length,
            center_y - math.cos(bearing) * length,
        )
    road_lines = "\n".join(
        f'<line x1="{center_x}" y1="{center_y}" x2="{x:.1f}" y2="{y:.1f}" '
        f'stroke="#27374d" stroke-width="{12 + 4 * int(arms[arm]["incoming_lanes"])}" '
        f'stroke-linecap="round" />'
        for arm, (x, y) in endpoints.items()
    )
    center_lines = "\n".join(
        f'<line x1="{center_x}" y1="{center_y}" x2="{x:.1f}" y2="{y:.1f}" '
        'stroke="#f4cf57" stroke-width="2" stroke-dasharray="10 8" />'
        for x, y in endpoints.values()
    )
    arm_labels = "\n".join(
        f'<text x="{x:.1f}" y="{y - 18:.1f}" text-anchor="middle" '
        f'fill="#e7edf6" font-size="20">{arm} · {arms[arm]["incoming_lanes"]}进口车道</text>'
        for arm, (x, y) in endpoints.items()
    )
    totals = " / ".join(
        f"{key} {workbook.demand_profiles[key].total_vehicles}辆"
        for key in _PROFILE_ORDER
    )
    cycles = " / ".join(
        f"{key} {workbook.signal_profiles[key].cycle_s}s"
        for key in _PROFILE_ORDER
    )
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<rect width="100%" height="100%" fill="#0c1424" />
<text x="48" y="58" fill="#ffffff" font-size="32" font-family="Segoe UI,Microsoft YaHei,sans-serif">官方独立路口 demo_{config['demo_id']}</text>
<text x="48" y="92" fill="#7ed6c4" font-size="18" font-family="Segoe UI,Microsoft YaHei,sans-serif">Excel 流量与配时 + OSM 位置、方位与道路等级</text>
{road_lines}
{center_lines}
<circle cx="{center_x}" cy="{center_y}" r="24" fill="#f05d5e" stroke="#ffffff" stroke-width="3" />
<text x="{center_x}" y="{center_y + 7}" fill="#ffffff" text-anchor="middle" font-size="20">J</text>
{arm_labels}
<rect x="40" y="622" width="920" height="102" rx="16" fill="#17243a" stroke="#31445f" />
<text x="64" y="661" fill="#ffffff" font-size="18" font-family="Segoe UI,Microsoft YaHei,sans-serif">2小时精确需求：{totals}</text>
<text x="64" y="697" fill="#ffffff" font-size="18" font-family="Segoe UI,Microsoft YaHei,sans-serif">官方周期：{cycles}</text>
</svg>'''
    path = output / "network_preview.svg"
    path.write_text(svg, encoding="utf-8")
    return path


def _validate_profile(
    output: Path,
    sumo_home: Path,
    profile: DemandProfile,
    config_path: Path,
) -> dict[str, Any]:
    profile_output = output / "validation_outputs" / profile.key
    profile_output.mkdir(parents=True, exist_ok=True)
    tripinfo_path = profile_output / "tripinfo.xml"
    summary_path = profile_output / "summary.xml"
    statistics_path = profile_output / "statistics.xml"
    vehroute_path = profile_output / "vehroute.xml"
    _run(
        [
            str(_sumo_binary(sumo_home, "sumo")),
            "-c",
            str(config_path),
            "--xml-validation",
            "always",
            "--tripinfo-output",
            str(tripinfo_path),
            "--summary-output",
            str(summary_path),
            "--statistic-output",
            str(statistics_path),
            "--vehroute-output",
            str(vehroute_path),
        ],
        cwd=output,
        timeout_s=600,
    )
    if not tripinfo_path.is_file() or not summary_path.is_file():
        raise OfficialBuildError(f"SUMO did not create outputs for {profile.key}")
    trip_count = sum(1 for _event, element in ET.iterparse(tripinfo_path, events=("end",)) if element.tag == "tripinfo")
    last_step: ET.Element | None = None
    for _event, element in ET.iterparse(summary_path, events=("end",)):
        if element.tag == "step":
            last_step = element
    if last_step is None:
        raise OfficialBuildError(f"summary has no steps for {profile.key}")
    collisions = 0
    teleports = 0
    if statistics_path.is_file():
        root = ET.parse(statistics_path).getroot()
        safety = root.find("safety")
        if safety is not None:
            collisions = int(float(safety.get("collisions", "0")))
            teleports = int(float(safety.get("teleports", "0")))
    expected = profile.total_vehicles
    running = int(float(last_step.get("running", "0")))
    waiting = int(float(last_step.get("waiting", "0")))
    ended = int(float(last_step.get("ended", "0")))
    loaded = int(float(last_step.get("loaded", "0")))
    return {
        "profile": profile.key,
        "expected_demand": expected,
        "loaded": loaded,
        "tripinfo_count": trip_count,
        "summary_ended": ended,
        "final_running": running,
        "final_waiting": waiting,
        "demand_conservation": loaded == expected,
        "all_vehicles_cleared": trip_count == expected and running == 0 and waiting == 0,
        "collisions": collisions,
        "teleports": teleports,
        "sumo_exit_code": 0,
    }


def _write_project_readme(
    output: Path,
    config: dict[str, Any],
    workbook: OfficialWorkbook,
    validation: dict[str, Any],
) -> Path:
    geometry_mode = str(config.get("geometry", {}).get("mode", "explicit_osm_chain"))
    if geometry_mode == "organizer_official_sumo_reference":
        geometry_note = (
            "道路臂长度、方位和车道结构参考主办方1—4号SUMO示例工程，"
            "地理位置来自PNG配准"
        )
    else:
        geometry_note = (
            "道路中心线沿OSM node chain延伸到下一处拓扑路口；"
            "OSM拓扑与Excel进口方向冲突时会在manifest中明确记录"
        )
    profile_rows = "\n".join(
        f"| {key} | {workbook.demand_profiles[key].clock_window} | "
        f"{workbook.demand_profiles[key].total_vehicles} | "
        f"{workbook.signal_profiles[key].cycle_s} / "
        f"{workbook.signal_profiles[key].source_cycle_s} | "
        f"{validation['profiles'][key].get('all_vehicles_cleared', '未运行')} |"
        for key in _PROFILE_ORDER
    )
    text = f"""# 官方独立路口 demo_{config['demo_id']}

这是一个可运行的独立 SUMO 路口工程，不是凭空生成的规则路口：

- 流量、15 分钟时变分布、转向运动和固定配时取自主办方 Excel；
- 中心位置、道路方位、道路等级及有标签时的车道数参考 OSM；
- 路口形态和车道可见信息由主办方高精地图 PNG 交叉核验；
- 主办方没有提供车辆类型构成，因此本样例仅采用 `1 PCU = 1 passenger`，未伪造车型比例；
- 所有小汽车采用用户指定主题色 `{config['vehicle_assumption']['theme_color_hex']}`；
- SUMO-GUI 演示步进延迟固定为 `{config['gui']['delay_ms']}ms`；
- {geometry_note}；
- Excel源表内部一致性：`{workbook.source_audit['workbook_source_consistent']}`；不一致项见 `manifest.json` 的 `workbook_source_audit`；
- 本工程属于建模结果，不等同于测绘级/车道级高精地图真值。

| 时段 | 原始时钟 | 2小时车辆数 | 执行周期/Excel周期(s) | 9000秒内清空 |
|---|---:|---:|---:|---:|
{profile_rows}

## 运行

```powershell
$env:SUMO_HOME='C:/path/to/sumo'
& $env:SUMO_HOME/bin/sumo-gui.exe -c demo_{config['demo_id']}_am_peak.sumocfg
& $env:SUMO_HOME/bin/sumo.exe -c demo_{config['demo_id']}_pm_peak.sumocfg
```

`validation.json` 是实际 SUMO 运行结果；`manifest.json` 保存源文件与派生文件哈希。
"""
    path = output / "README.md"
    path.write_text(text, encoding="utf-8")
    return path


def _build_one(
    workspace: Path,
    source_root: Path,
    sumo_home: Path,
    demo_id: int,
    *,
    validate: bool,
) -> dict[str, Any]:
    config_path = workspace / "scenarios" / "configs" / "official_intersections" / f"demo_{demo_id}.yaml"
    workbook_path, map_path = _find_organizer_sources(source_root, demo_id)
    workbook = parse_official_workbook(workbook_path)
    if config_path.is_file():
        config = _load_config(config_path)
        config_source_files = [config_path]
    else:
        config = build_evidence_config(workspace, demo_id, workbook)
        config_source_files = evidence_registry_paths(workspace)
    if int(config["demo_id"]) != demo_id:
        raise OfficialBuildError(f"demo id mismatch for effective config {demo_id}")
    active = _validate_movement_evidence(config, workbook)
    output = workspace / "scenarios" / "generated" / "official_20_independent" / f"demo_{demo_id}"
    output.mkdir(parents=True, exist_ok=True)

    if config.get("geometry"):
        center, arm_points, arm_geometry = resolve_evidence_geometry(
            workspace,
            source_root,
            config,
        )
    else:
        center, arm_points, arm_geometry = _resolve_osm_geometry(workspace, config)
    effective_config_path = output / "effective_config.yaml"
    effective_config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    plain_paths = _write_plain_network(
        output,
        config,
        active,
        center,
        arm_points,
    )
    base_net = _create_base_network(output, sumo_home, plain_paths)
    _record_sumo_effective_lengths(base_net, arm_geometry)
    link_indices, state_length = _link_indices(base_net, active)
    view_settings_path = _write_gui_settings(output, config)
    generated_files: list[Path] = [
        effective_config_path,
        *config_source_files,
        *plain_paths,
        base_net,
        view_settings_path,
    ]
    configs: dict[str, Path] = {}
    for key in _PROFILE_ORDER:
        net_path, signal_path = _write_profile_network(
            base_net,
            output,
            workbook.signal_profiles[key],
            config=config,
            link_indices=link_indices,
            state_length=state_length,
        )
        route_path = _write_routes(output, config, workbook.demand_profiles[key], active)
        sumocfg_path = _write_sumocfg(
            output,
            config,
            key,
            net_path,
            route_path,
            view_settings_path,
        )
        configs[key] = sumocfg_path
        generated_files.extend([net_path, signal_path, route_path, sumocfg_path])
    preview_path = _write_preview(output, config, workbook)
    generated_files.append(preview_path)

    validation_profiles: dict[str, Any] = {}
    if validate:
        for key in _PROFILE_ORDER:
            validation_profiles[key] = _validate_profile(
                output,
                sumo_home,
                workbook.demand_profiles[key],
                configs[key],
            )
    else:
        validation_profiles = {
            key: {"profile": key, "status": "not_run"} for key in _PROFILE_ORDER
        }
    validation_result = {
        "schema_version": "1.0",
        "demo_id": demo_id,
        "actual_sumo_run": validate,
        "profiles": validation_profiles,
        "structurally_valid": all(
            result.get("sumo_exit_code") == 0 for result in validation_profiles.values()
        )
        if validate
        else None,
        "all_profiles_cleared": all(
            result.get("all_vehicles_cleared", False) for result in validation_profiles.values()
        )
        if validate
        else None,
        "evidence_note": "structural validity and full demand clearance are separate gates",
    }
    validation_path = output / "validation.json"
    validation_path.write_text(
        json.dumps(validation_result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    generated_files.append(validation_path)
    readme_path = _write_project_readme(output, config, workbook, validation_result)
    generated_files.append(readme_path)

    source_files = [
        {
            "role": "organizer_workbook_read_only",
            "path": str(workbook_path),
            "sha256": sha256_file(workbook_path),
        },
        {
            "role": "organizer_high_precision_map_png_read_only",
            "path": str(map_path),
            "sha256": sha256_file(map_path),
        },
    ]
    geometry_mode = str(config.get("geometry", {}).get("mode", "explicit_osm_chain"))
    if geometry_mode == "organizer_official_sumo_reference":
        reference_net = Path(str(config["geometry"]["reference_net"]))
        source_files.append(
            {
                "role": "organizer_official_sumo_reference_net_read_only",
                "path": str(reference_net),
                "sha256": sha256_file(reference_net),
            }
        )
    osm_path = workspace / str(config["osm_reference"]["source_file"])
    source_files.append(
        {
            "role": "osm_geometry_and_tags_cross_check",
            "path": config["osm_reference"]["source_file"],
            "sha256": sha256_file(osm_path),
        }
    )
    for evidence_path in config_source_files:
        if evidence_path == config_path:
            continue
        source_files.append(
            {
                "role": "derived_evidence_registry",
                "path": evidence_path.relative_to(workspace).as_posix(),
                "sha256": sha256_file(evidence_path),
            }
        )
    manifest = {
        "schema_version": "1.0",
        "scenario_id": config["scenario_id"],
        "demo_id": demo_id,
        "provenance_class": (
            "organizer_excel_png_official_sumo_reference_model"
            if geometry_mode == "organizer_official_sumo_reference"
            else "organizer_excel_png_plus_osm_modeled_sumo"
        ),
        "source_files": source_files,
        "workbook_source_audit": workbook.source_audit,
        "workbook_interpretation": {
            key: {
                "clock_window": workbook.demand_profiles[key].clock_window,
                "demand_total": workbook.demand_profiles[key].total_vehicles,
                "movement_totals": workbook.demand_profiles[key].movement_totals,
                "approach_totals": workbook.demand_profiles[key].approach_totals,
                "executed_component_cycle_s": workbook.signal_profiles[key].cycle_s,
                "source_declared_cycle_s": workbook.signal_profiles[key].source_cycle_s,
                "phases": [asdict(phase) for phase in workbook.signal_profiles[key].phases],
            }
            for key in _PROFILE_ORDER
        },
        "active_movements": sorted(active),
        "arm_geometry": arm_geometry,
        "controlled_link_indices": link_indices,
        "generated_files": [
            {
                "path": path.relative_to(workspace).as_posix(),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
            for path in sorted(set(generated_files))
        ],
        "validation": validation_result,
        "git_revision": git_revision(workspace),
        "evidence_boundaries": [
            config["registration"]["evidence_boundary"],
            config["osm_reference"]["evidence_boundary"],
            config["network_center"]["evidence_boundary"],
            config["vehicle_assumption"]["evidence_boundary"],
            "SUMO network is a traceable model, not field-surveyed lane-level truth",
        ],
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "demo_id": demo_id,
        "output": str(output),
        "profiles": validation_profiles,
        "manifest": str(manifest_path),
        "preview": str(preview_path),
    }


def build_official_intersections(
    workspace: Path,
    source_root: Path,
    sumo_home: Path,
    demo_ids: list[int],
    *,
    validate: bool = True,
    jobs: int = 1,
) -> dict[str, Any]:
    """Build selected organizer intersections as standalone, reproducible SUMO projects."""

    if not source_root.is_dir():
        raise FileNotFoundError(source_root)
    if not demo_ids:
        raise ValueError("at least one demo id is required")
    invalid_ids = sorted({demo_id for demo_id in demo_ids if not 1 <= demo_id <= 20})
    if invalid_ids:
        raise ValueError(f"demo ids must be in 1..20: {invalid_ids}")
    if jobs < 1:
        raise ValueError("jobs must be at least 1")
    unique_ids = list(dict.fromkeys(demo_ids))
    if jobs == 1:
        results = [
            _build_one(workspace, source_root, sumo_home, demo_id, validate=validate)
            for demo_id in unique_ids
        ]
    else:
        indexed: dict[int, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=min(jobs, len(unique_ids))) as executor:
            futures = {
                executor.submit(
                    _build_one,
                    workspace,
                    source_root,
                    sumo_home,
                    demo_id,
                    validate=validate,
                ): demo_id
                for demo_id in unique_ids
            }
            for future in as_completed(futures):
                demo_id = futures[future]
                indexed[demo_id] = future.result()
        results = [indexed[demo_id] for demo_id in unique_ids]
    return {
        "status": "generated_and_validated" if validate else "generated_not_run",
        "demo_ids": unique_ids,
        "jobs": min(jobs, len(unique_ids)),
        "results": results,
    }
