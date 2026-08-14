"""Full-OSM pedestrian, bicycle and e-bike scenario derivation.

The frozen motor-network baseline is never edited.  This module derives a
separate network from the same complete OSM extract and records which
facilities came from OSM versus deterministic engineering inference.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from traffic_platform.scenario_engine.models import ScenarioConfig
from traffic_platform.scenario_engine.signal_application import apply_parameter_transfer


@dataclass(frozen=True, slots=True)
class MultimodalDemandSummary:
    """Counts and provenance for one generated active-mode demand file."""

    route_file: Path
    participant_counts: dict[str, int]
    od_counts: dict[str, int]
    sha256: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command: list[str], cwd: Path) -> None:
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"multimodal SUMO command failed ({completed.returncode}): "
            f"{' '.join(command)}\n{completed.stderr}"
        )


def _load_sumolib(sumo_home: Path) -> Any:
    tools = str(sumo_home / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    os.environ.setdefault("SUMO_HOME", str(sumo_home))
    import sumolib

    return sumolib


def build_multimodal_network(
    *,
    osm_file: Path,
    output: Path,
    sumo_home: Path,
    selection_file: Path,
    parameter_file: Path,
    scenario: ScenarioConfig,
) -> dict[str, Any]:
    """Derive a full-extent multimodal network without editing the baseline."""

    if not scenario.multimodal.enabled:
        return {"enabled": False}
    base_file = output / "rongdong.multimodal.base.net.xml"
    signaled_file = output / "rongdong.multimodal.signaled.net.xml"
    final_file = output / "rongdong.multimodal.net.xml"
    netconvert = sumo_home / "bin" / ("netconvert.exe" if sys.platform == "win32" else "netconvert")
    if not netconvert.is_file():
        raise FileNotFoundError(f"netconvert was not found: {netconvert}")
    config = scenario.multimodal
    _run(
        [
            str(netconvert),
            "--osm-files",
            str(osm_file),
            "--output-file",
            str(base_file),
            "--roundabouts.guess",
            "true",
            "--tls.guess-signals",
            "true",
            "--tls.discard-simple",
            "false",
            "--tls.crossing-min.time",
            f"{config.pedestrian_min_green_s:g}",
            "--tls.crossing-clearance.time",
            f"{config.pedestrian_clearance_s:g}",
            "--osm.sidewalks",
            "true",
            "--osm.crossings",
            "true",
            "--sidewalks.guess",
            "true",
            "--sidewalks.guess.max-speed",
            f"{config.sidewalk_max_road_speed_m_s:g}",
            "--sidewalks.guess.min-speed",
            "1.0",
            "--crossings.guess",
            "true",
            "--crossings.guess.speed-threshold",
            f"{config.crossing_speed_threshold_m_s:g}",
            "--walkingareas",
            "true",
            "--bikelanes.guess",
            "true",
            "--bikelanes.guess.max-speed",
            f"{config.bicycle_lane_max_road_speed_m_s:g}",
            "--bikelanes.guess.min-speed",
            "1.0",
            "--default.sidewalk-width",
            f"{config.sidewalk_width_m:g}",
            "--default.bikelane-width",
            f"{config.bicycle_lane_width_m:g}",
            "--osm.turn-lanes",
            "true",
            "--remove-edges.by-vclass",
            "tram,rail_urban,subway,cable_car,rail_electric",
            "--remove-edges.isolated",
            "true",
            "--junctions.join",
            "true",
        ],
        output,
    )
    selection = json.loads(selection_file.read_text(encoding="utf-8"))
    signal_ids = ",".join(selection["requires_signalization"])
    _run(
        [
            str(netconvert),
            "--sumo-net-file",
            str(base_file),
            "--output-file",
            str(signaled_file),
            "--tls.set",
            signal_ids,
            "--tls.default-type",
            "static",
            "--tls.crossing-min.time",
            f"{config.pedestrian_min_green_s:g}",
            "--tls.crossing-clearance.time",
            f"{config.pedestrian_clearance_s:g}",
        ],
        output,
    )
    application = apply_parameter_transfer(
        net_file=signaled_file,
        parameter_file=parameter_file,
        selection_file=selection_file,
        output_file=final_file,
    )
    orphan_signal_repairs = repair_orphan_pedestrian_signals(
        final_file,
        minimum_green_s=config.pedestrian_min_green_s,
    )
    audit = audit_multimodal_network(final_file, selection_file)
    result = {
        "schema_version": "1.0",
        "enabled": True,
        "network_scope": "complete_rongdong_osm_network_not_cropped",
        "baseline_network_modified": False,
        "source_osm": str(osm_file),
        "source_osm_sha256": _sha256(osm_file),
        "network_files": {
            "base": base_file.name,
            "signaled": signaled_file.name,
            "executable": final_file.name,
        },
        "facility_provenance": {
            "osm_import": ["sidewalk", "crossing", "turn_lanes"],
            "engineering_inference": [
                "missing_sidewalks",
                "missing_crossings",
                "bicycle_lanes",
                "walking_areas",
            ],
            "field_calibrated": False,
        },
        "pedestrian_signal_policy": {
            "mode": "conditional_parallel",
            "implementation": (
                "SUMO conflict-aware TLS logic permits pedestrian green with "
                "compatible vehicle movements; conflicting permissive turns use "
                "lowercase-g yield priority"
            ),
            "minimum_green_s": config.pedestrian_min_green_s,
            "clearance_s": config.pedestrian_clearance_s,
        },
        "organizer_parameter_application": application,
        "orphan_pedestrian_signal_repairs": orphan_signal_repairs,
        "audit": audit,
        "evidence_boundary": (
            "OSM supplies geography; missing active-mode facilities and demand are "
            "traceable engineering assumptions, not field observations"
        ),
    }
    (output / "multimodal_network_manifest.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def repair_orphan_pedestrian_signals(
    net_file: Path,
    *,
    minimum_green_s: float,
) -> list[dict[str, Any]]:
    """Give orphan crossing links a safe exclusive phase in the derived net.

    Netconvert can occasionally create a controlled crossing link that is red
    in every generated phase.  Such a link cannot be served and SUMO emits a
    warning.  Reusing an existing all-red phase is conservative and does not
    invent a vehicle conflict relationship.
    """

    tree = ET.parse(net_file)
    root = tree.getroot()
    edge_functions = {
        edge.attrib["id"]: edge.attrib.get("function") for edge in root.findall("edge")
    }
    crossing_indices_by_tl: dict[str, set[int]] = {}
    for connection in root.findall("connection"):
        tl_id = connection.attrib.get("tl")
        link_index = connection.attrib.get("linkIndex")
        if (
            tl_id
            and link_index is not None
            and edge_functions.get(connection.attrib.get("to", "")) == "crossing"
        ):
            crossing_indices_by_tl.setdefault(tl_id, set()).add(int(link_index))
    repairs: list[dict[str, Any]] = []
    for logic in root.findall("tlLogic"):
        tl_id = logic.attrib["id"]
        phases = logic.findall("phase")
        for index in sorted(crossing_indices_by_tl.get(tl_id, set())):
            if any(
                index < len(phase.attrib["state"]) and phase.attrib["state"][index] in {"G", "g"}
                for phase in phases
            ):
                continue
            all_red_phase = next(
                (phase for phase in phases if all(value == "r" for value in phase.attrib["state"])),
                None,
            )
            if all_red_phase is None:
                state_length = max(len(phase.attrib["state"]) for phase in phases)
                all_red_phase = ET.SubElement(
                    logic,
                    "phase",
                    {
                        "duration": f"{minimum_green_s:g}",
                        "state": "r" * state_length,
                    },
                )
                phases.append(all_red_phase)
            state = list(all_red_phase.attrib["state"])
            state[index] = "G"
            all_red_phase.set("state", "".join(state))
            all_red_phase.set(
                "duration",
                f"{max(float(all_red_phase.attrib['duration']), minimum_green_s):g}",
            )
            repairs.append(
                {
                    "traffic_light_id": tl_id,
                    "link_index": index,
                    "policy": "safe_exclusive_fallback_for_orphan_crossing_link",
                }
            )
    if repairs:
        ET.indent(tree, space="    ")
        tree.write(net_file, encoding="utf-8", xml_declaration=True)
    return repairs


def _permissions(lane: ET.Element) -> set[str]:
    allow = lane.attrib.get("allow")
    disallow = set(lane.attrib.get("disallow", "").split())
    if allow:
        return set(allow.split())
    default = {
        "passenger",
        "bus",
        "truck",
        "emergency",
        "bicycle",
        "pedestrian",
    }
    return default - disallow


def audit_multimodal_network(net_file: Path, selection_file: Path) -> dict[str, Any]:
    """Audit active-mode lanes, crossings and conditional-parallel TLS phases."""

    tree = ET.parse(net_file)
    root = tree.getroot()
    selection = json.loads(selection_file.read_text(encoding="utf-8"))
    edge_by_id = {edge.attrib["id"]: edge for edge in root.findall("edge")}
    junction_by_id = {junction.attrib["id"]: junction for junction in root.findall("junction")}
    ordinary_edges = [
        edge for edge in root.findall("edge") if edge.attrib.get("function") != "internal"
    ]
    lanes = [lane for edge in ordinary_edges for lane in edge.findall("lane")]
    tl_by_id = {logic.attrib["id"]: logic for logic in root.findall("tlLogic")}
    connections_by_tl: dict[str, list[ET.Element]] = {}
    for connection in root.findall("connection"):
        tl_id = connection.attrib.get("tl")
        if tl_id:
            connections_by_tl.setdefault(tl_id, []).append(connection)
    intersections: list[dict[str, Any]] = []
    for selected in selection["intersections"]:
        intersection_id = selected["intersection_id"]
        logic = tl_by_id.get(intersection_id)
        connections = connections_by_tl.get(intersection_id, [])
        crossing_indices = sorted(
            {
                int(connection.attrib["linkIndex"])
                for connection in connections
                if edge_by_id.get(connection.attrib["to"]) is not None
                and edge_by_id[connection.attrib["to"]].attrib.get("function") == "crossing"
            }
        )
        phases = logic.findall("phase") if logic is not None else []
        parallel_phases = 0
        pedestrian_green_phases = 0
        yield_link_phases = 0
        pedestrian_green_durations: list[float] = []
        for phase in phases:
            state = phase.attrib["state"]
            pedestrian_green = any(
                index < len(state) and state[index] in {"G", "g"} for index in crossing_indices
            )
            if pedestrian_green:
                pedestrian_green_phases += 1
                pedestrian_green_durations.append(float(phase.attrib["duration"]))
                non_crossing_states = [
                    value for index, value in enumerate(state) if index not in crossing_indices
                ]
                if any(value in {"G", "g"} for value in non_crossing_states):
                    parallel_phases += 1
                if "g" in non_crossing_states:
                    yield_link_phases += 1
        junction = junction_by_id.get(intersection_id)
        incoming_lane_ids = (
            junction.attrib.get("incLanes", "").split() if junction is not None else []
        )
        motor_speeds: list[float] = []
        for lane_id in incoming_lane_ids:
            if lane_id.startswith(":"):
                continue
            edge = edge_by_id.get(lane_id.rsplit("_", 1)[0])
            lane = (
                next(
                    (item for item in edge.findall("lane") if item.attrib["id"] == lane_id),
                    None,
                )
                if edge is not None
                else None
            )
            if lane is not None and _permissions(lane).intersection(
                {"passenger", "bus", "truck", "emergency"}
            ):
                motor_speeds.append(float(lane.attrib["speed"]))
        intersections.append(
            {
                "display_id": selected["display_id"],
                "sumo_intersection_id": intersection_id,
                "crossing_signal_link_count": len(crossing_indices),
                "pedestrian_green_phase_count": pedestrian_green_phases,
                "conditional_parallel_phase_count": parallel_phases,
                "parallel_phase_with_vehicle_yield_count": yield_link_phases,
                "minimum_pedestrian_green_s": min(pedestrian_green_durations, default=0.0),
                "maximum_incoming_motor_speed_m_s": max(motor_speeds, default=0.0),
                "pedestrian_crossing_status": (
                    "conditional_parallel_enabled"
                    if crossing_indices
                    else "not_forced_without_at_grade_crossing_evidence"
                ),
            }
        )
    supported = [
        item
        for item in intersections
        if item["crossing_signal_link_count"] > 0 and item["conditional_parallel_phase_count"] > 0
    ]
    crossing_enabled = [item for item in intersections if item["crossing_signal_link_count"] > 0]
    return {
        "network_sha256": _sha256(net_file),
        "ordinary_edge_count": len(ordinary_edges),
        "lane_count": len(lanes),
        "pedestrian_lane_count": sum("pedestrian" in _permissions(lane) for lane in lanes),
        "bicycle_lane_count": sum("bicycle" in _permissions(lane) for lane in lanes),
        "crossing_edge_count": sum(
            edge.attrib.get("function") == "crossing" for edge in root.findall("edge")
        ),
        "walking_area_edge_count": sum(
            edge.attrib.get("function") == "walkingarea" for edge in root.findall("edge")
        ),
        "selected_intersection_count": len(intersections),
        "selected_with_conditional_parallel_pedestrian_signal": len(supported),
        "all_selected_support_conditional_parallel": len(supported) == len(intersections),
        "all_crossing_enabled_selected_use_conditional_parallel": len(supported)
        == len(crossing_enabled),
        "all_crossing_enabled_selected_meet_minimum_green": all(
            item["minimum_pedestrian_green_s"] >= 10.0 for item in crossing_enabled
        ),
        "crossing_policy_boundary": (
            "at-grade crossings use conditional parallel; crossings are not "
            "fabricated across high-speed or grade-separated approaches without evidence"
        ),
        "intersections": intersections,
    }


def add_active_mode_types(additional_file: Path) -> None:
    """Add traceable modeled motor, bicycle, e-bike and pedestrian types."""

    tree = ET.parse(additional_file)
    root = tree.getroot()
    existing = {item.attrib["id"] for item in root.findall("vType")}
    definitions = {
        "taxi": {
            "vClass": "taxi",
            "accel": "2.5",
            "decel": "4.5",
            "sigma": "0.4",
            "length": "5.0",
            "minGap": "2.2",
            "maxSpeed": "16.67",
            "color": "255,170,0",
        },
        "ride_hailing": {
            "vClass": "passenger",
            "accel": "2.6",
            "decel": "4.5",
            "sigma": "0.35",
            "length": "5.0",
            "minGap": "2.2",
            "maxSpeed": "16.67",
            "color": "0,200,180",
        },
        "delivery_vehicle": {
            "vClass": "delivery",
            "accel": "1.8",
            "decel": "4.0",
            "sigma": "0.45",
            "length": "6.2",
            "minGap": "2.8",
            "maxSpeed": "15.28",
            "color": "150,100,255",
        },
        "bicycle": {
            "vClass": "bicycle",
            "accel": "1.2",
            "decel": "3.0",
            "sigma": "0.5",
            "length": "1.8",
            "minGap": "0.5",
            "maxSpeed": "5.56",
            "guiShape": "bicycle",
            "color": "0,180,255",
        },
        "electric_bicycle": {
            "vClass": "bicycle",
            "accel": "1.8",
            "decel": "4.0",
            "sigma": "0.35",
            "length": "1.9",
            "minGap": "0.6",
            "maxSpeed": "8.33",
            "guiShape": "bicycle",
            "color": "210,80,255",
        },
        "pedestrian_adult": {
            "vClass": "pedestrian",
            "guiShape": "pedestrian",
            "imgFile": "pedestrian_adult.png",
            "maxSpeed": "1.45",
            "speedFactor": "normc(1,0.12,0.65,1.35)",
            "length": "0.5",
            "minGap": "0.2",
            "color": "40,220,120",
        },
        "pedestrian_elderly": {
            "vClass": "pedestrian",
            "guiShape": "pedestrian",
            "imgFile": "pedestrian_elderly.png",
            "maxSpeed": "1.10",
            "speedFactor": "normc(1,0.10,0.65,1.25)",
            "length": "0.5",
            "minGap": "0.25",
            "color": "255,170,40",
        },
    }
    for identifier, attributes in definitions.items():
        if identifier not in existing:
            ET.SubElement(root, "vType", {"id": identifier, **attributes})
    ET.indent(tree, space="    ")
    tree.write(additional_file, encoding="utf-8", xml_declaration=True)


def _edge_midpoint(edge: Any) -> tuple[float, float]:
    start = edge.getFromNode().getCoord()
    end = edge.getToNode().getCoord()
    return (
        (float(start[0]) + float(end[0])) / 2,
        (float(start[1]) + float(end[1])) / 2,
    )


def _quantile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def _mode_zones(net: Any, vclass: str) -> dict[str, list[Any]]:
    edges = sorted(
        (
            edge
            for edge in net.getEdges(withInternal=False)
            if not edge.isSpecial() and edge.allows(vclass)
        ),
        key=lambda edge: edge.getID(),
    )
    if not edges:
        raise ValueError(f"complete network has no {vclass}-capable edges")
    midpoint = {edge.getID(): _edge_midpoint(edge) for edge in edges}
    xs = [point[0] for point in midpoint.values()]
    ys = [point[1] for point in midpoint.values()]
    west = _quantile(xs, 0.20)
    east = _quantile(xs, 0.80)
    south = _quantile(ys, 0.20)
    north = _quantile(ys, 0.80)
    return {
        "west_upstream": [edge for edge in edges if midpoint[edge.getID()][0] <= west],
        "west_exit": [edge for edge in edges if midpoint[edge.getID()][0] <= west],
        "east_upstream": [edge for edge in edges if midpoint[edge.getID()][0] >= east],
        "east_bottleneck": [edge for edge in edges if midpoint[edge.getID()][0] >= east],
        "north_activity": [edge for edge in edges if midpoint[edge.getID()][1] >= north],
        "south_exit": [edge for edge in edges if midpoint[edge.getID()][1] <= south],
        "network_local": edges,
    }


def _route_pool(
    net: Any,
    origins: list[Any],
    destinations: list[Any],
    *,
    vclass: str,
    randomizer: random.Random,
) -> list[list[str]]:
    routes: list[list[str]] = []
    attempts = 0
    while len(routes) < 20 and attempts < 2000:
        attempts += 1
        origin = randomizer.choice(origins)
        destination = randomizer.choice(destinations)
        if origin.getID() == destination.getID():
            continue
        path = net.getOptimalPath(
            origin,
            destination,
            vClass=vclass,
            withInternal=vclass == "pedestrian",
        )
        if not path or not path[0] or len(path[0]) < 2:
            continue
        route_length = sum(float(edge.getLength()) for edge in path[0] if not edge.isSpecial())
        if vclass == "pedestrian" and not 100.0 <= route_length <= 1200.0:
            continue
        identifiers = [edge.getID() for edge in path[0]]
        if len(set(identifiers)) != len(identifiers) or identifiers in routes:
            continue
        routes.append(identifiers)
    if not routes:
        raise RuntimeError(f"no complete-network {vclass} route could be generated")
    return routes


def generate_multimodal_demand(
    *,
    net_file: Path,
    route_file: Path,
    scenario: ScenarioConfig,
    sumo_home: Path,
) -> MultimodalDemandSummary:
    """Generate simultaneous bicycle, e-bike and pedestrian trips."""

    sumolib = _load_sumolib(sumo_home)
    net = sumolib.net.readNet(
        str(net_file),
        withPrograms=False,
        withInternal=True,
        withPedestrianConnections=True,
    )
    randomizer = random.Random(scenario.simulation.seed + 104729)
    zones_by_class = {
        "bicycle": _mode_zones(net, "bicycle"),
        "pedestrian": _mode_zones(net, "pedestrian"),
    }
    pools: dict[tuple[str, str, str], list[list[str]]] = {}
    root = ET.Element("routes")
    scheduled: list[tuple[float, str, str, list[str]]] = []
    participant_counts = {
        "bicycle": 0,
        "electric_bicycle": 0,
        "pedestrian": 0,
    }
    od_counts: dict[str, int] = {}
    for demand_index, demand in enumerate(scenario.multimodal.demands):
        vclass = "pedestrian" if demand.participant == "pedestrian" else "bicycle"
        zones = zones_by_class[vclass]
        origins = zones.get(demand.origin_zone, [])
        destinations = zones.get(demand.destination_zone, [])
        if not origins or not destinations:
            raise ValueError(
                f"empty {vclass} OD zone: {demand.origin_zone}->{demand.destination_zone}"
            )
        pool_key = (vclass, demand.origin_zone, demand.destination_zone)
        if pool_key not in pools:
            pools[pool_key] = _route_pool(
                net,
                origins,
                destinations,
                vclass=vclass,
                randomizer=randomizer,
            )
        duration = demand.end_s - demand.begin_s
        count = round(demand.flow_persons_h * duration / 3600.0)
        od_key = f"{demand.participant}:{demand.origin_zone}->{demand.destination_zone}"
        od_counts[od_key] = od_counts.get(od_key, 0) + count
        if count <= 0:
            continue
        headway = duration / count
        for index in range(count):
            depart = demand.begin_s + (index + 0.5) * headway
            depart += randomizer.uniform(-0.25, 0.25) * headway
            depart = min(demand.end_s - 0.001, max(demand.begin_s, depart))
            candidate_count = 3 if demand.participant == "pedestrian" else 1
            for candidate_index in range(candidate_count):
                candidate_suffix = f"_c{candidate_index}" if candidate_count > 1 else ""
                scheduled.append(
                    (
                        depart,
                        f"active{demand_index:02d}_{index:05d}{candidate_suffix}",
                        demand.participant,
                        randomizer.choice(pools[pool_key]),
                    )
                )
    for depart, identifier, participant, edges in sorted(scheduled):
        if participant == "pedestrian":
            pedestrian_type = (
                "pedestrian_elderly" if randomizer.random() < 0.12 else "pedestrian_adult"
            )
            person = ET.SubElement(
                root,
                "person",
                {
                    "id": identifier,
                    "type": pedestrian_type,
                    "depart": f"{depart:.3f}",
                },
            )
            ET.SubElement(person, "walk", {"from": edges[0], "to": edges[-1]})
        else:
            vehicle = ET.SubElement(
                root,
                "vehicle",
                {
                    "id": identifier,
                    "type": participant,
                    "depart": f"{depart:.3f}",
                    "departLane": "best",
                    "departSpeed": "max",
                },
            )
            ET.SubElement(vehicle, "route", {"edges": " ".join(edges)})
        if participant != "pedestrian" or not identifier.endswith(("_c1", "_c2")):
            participant_counts[participant] += 1
    ET.indent(root, space="    ")
    ET.ElementTree(root).write(route_file, encoding="utf-8", xml_declaration=True)
    return MultimodalDemandSummary(
        route_file=route_file,
        participant_counts=participant_counts,
        od_counts=od_counts,
        sha256=_sha256(route_file),
    )


def route_and_validate_multimodal_demand(
    *,
    raw_summary: MultimodalDemandSummary,
    net_file: Path,
    additional_file: Path,
    output_file: Path,
    sumo_home: Path,
    seed: int,
    scenario: ScenarioConfig,
) -> MultimodalDemandSummary:
    """Use SUMO's router to validate every active-mode route before runtime."""

    duarouter = sumo_home / "bin" / ("duarouter.exe" if sys.platform == "win32" else "duarouter")
    temporary_output = output_file.with_suffix(".duarouter.tmp.xml")
    _run(
        [
            str(duarouter),
            "--net-file",
            str(net_file),
            "--route-files",
            str(raw_summary.route_file),
            "--additional-files",
            str(additional_file),
            "--output-file",
            str(temporary_output),
            "--ignore-errors",
            "true",
            "--repair",
            "true",
            "--seed",
            str(seed),
        ],
        output_file.parent,
    )
    tree = ET.parse(temporary_output)
    root = tree.getroot()
    for vtype in list(root.findall("vType")):
        root.remove(vtype)
    people_by_id = {person.attrib["id"]: person for person in root.findall("person")}
    selected_people: list[ET.Element] = []
    for demand_index, demand in enumerate(scenario.multimodal.demands):
        if demand.participant != "pedestrian":
            continue
        duration = demand.end_s - demand.begin_s
        target_count = round(demand.flow_persons_h * duration / 3600.0)
        for index in range(target_count):
            base_identifier = f"active{demand_index:02d}_{index:05d}"
            candidate = next(
                (
                    people_by_id.get(f"{base_identifier}_c{candidate_index}")
                    for candidate_index in range(3)
                    if people_by_id.get(f"{base_identifier}_c{candidate_index}") is not None
                ),
                None,
            )
            if candidate is None:
                raise RuntimeError(
                    "duarouter found no connected pedestrian route for "
                    f"configured trip slot {base_identifier}"
                )
            candidate.set("id", base_identifier)
            selected_people.append(candidate)
    for person in list(root.findall("person")):
        root.remove(person)
    for person in selected_people:
        root.append(person)
    demand_elements = [element for element in list(root) if element.tag in {"vehicle", "person"}]
    for element in demand_elements:
        root.remove(element)
    for element in sorted(
        demand_elements,
        key=lambda item: (float(item.attrib["depart"]), item.attrib["id"]),
    ):
        root.append(element)
    actual_counts = {
        "bicycle": 0,
        "electric_bicycle": 0,
        "pedestrian": len(selected_people),
    }
    for vehicle in root.findall("vehicle"):
        identifier = vehicle.attrib.get("type", "")
        if identifier in actual_counts:
            actual_counts[identifier] += 1
    if actual_counts != raw_summary.participant_counts:
        raise RuntimeError(
            "duarouter changed multimodal demand counts: "
            f"expected={raw_summary.participant_counts}, actual={actual_counts}"
        )
    ET.indent(tree, space="    ")
    tree.write(output_file, encoding="utf-8", xml_declaration=True)
    temporary_output.unlink(missing_ok=True)
    return MultimodalDemandSummary(
        route_file=output_file,
        participant_counts=actual_counts,
        od_counts=raw_summary.od_counts,
        sha256=_sha256(output_file),
    )


def write_multimodal_demand_manifest(
    summary: MultimodalDemandSummary,
    output_file: Path,
) -> None:
    """Persist active-mode demand counts and evidence boundaries."""

    output_file.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "route_file": summary.route_file.name,
                "route_file_sha256": summary.sha256,
                "participant_counts": summary.participant_counts,
                "od_counts": summary.od_counts,
                "network_scope": "complete_rongdong_osm_network_not_cropped",
                "deterministic_for_equal_config_and_seed": True,
                "field_calibrated": False,
                "demand_provenance": "configuration_driven_engineering_assumption",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
