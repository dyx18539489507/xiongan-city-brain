"""Deterministic, configuration-driven traffic demand generation."""

from __future__ import annotations

import hashlib
import json
import os
import random
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from traffic_platform.scenario_engine.models import ScenarioConfig


@dataclass(frozen=True, slots=True)
class GeneratedDemand:
    """Traceable summary of one generated SUMO route file."""

    route_file: Path
    vehicle_count: int
    vehicle_type_counts: dict[str, int]
    od_counts: dict[str, int]
    connected_vehicle_penetration: float
    route_alternative_count: int
    minimum_controlled_intersections_per_route: int
    mean_controlled_intersections_per_route: float
    maximum_controlled_intersections_per_route: int
    multi_intersection_vehicle_count: int
    complete_network_vehicle_count: int
    controlled_corridor_vehicle_count: int
    minimum_controlled_intersections_for_corridor_routes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class PreparedDemandNetwork:
    """Reusable topology and route pools for a scenario generation batch."""

    route_pools: dict[tuple[str, str, str], tuple[list[list[str]], list[list[str]]]]
    route_controlled_visit_counts: dict[tuple[str, ...], int]
    controlled_intersection_ids: frozenset[str]
    minimum_controlled_intersections: int


def _load_sumolib(sumo_home: Path) -> Any:
    tools = str(sumo_home / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    os.environ.setdefault("SUMO_HOME", str(sumo_home))
    import sumolib

    return sumolib


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _adjust_ratios_for_penetration(
    configured: dict[str, float],
    penetration: float,
) -> dict[str, float]:
    """Make connected vehicle share equal to the selected penetration.

    The remaining configured categories retain their relative proportions. This
    keeps buses, trucks and emergency vehicles represented while allowing the
    required 0/20/50/80/100 percent penetration experiments to be generated
    without changing application code.
    """

    remainder_names = sorted(name for name in configured if name != "connected_vehicle")
    remainder_total = sum(configured[name] for name in remainder_names)
    if penetration >= 1.0:
        return {name: (1.0 if name == "connected_vehicle" else 0.0) for name in sorted(configured)}
    if remainder_total <= 0:
        raise ValueError("non-connected vehicle ratio mass must be positive")
    result = {
        name: configured[name] / remainder_total * (1.0 - penetration) for name in remainder_names
    }
    result["connected_vehicle"] = penetration
    return dict(sorted(result.items()))


def _weighted_choice(
    randomizer: random.Random,
    ratios: dict[str, float],
) -> str:
    draw = randomizer.random()
    cumulative = 0.0
    for name, ratio in sorted(ratios.items()):
        cumulative += ratio
        if draw <= cumulative:
            return name
    return sorted(ratios)[-1]


def _edge_midpoint(edge: Any) -> tuple[float, float]:
    start = edge.getFromNode().getCoord()
    end = edge.getToNode().getCoord()
    return ((float(start[0]) + float(end[0])) / 2, (float(start[1]) + float(end[1])) / 2)


def _quantile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def _zone_edges(
    net: Any,
    controlled_intersection_ids: frozenset[str] = frozenset(),
) -> dict[str, list[Any]]:
    """Derive OD zones from every eligible edge in the complete OSM network.

    ``controlled_intersection_ids`` is retained for API compatibility and for
    route visit accounting. It must never be used to crop or spatially bound
    the OD candidate set.
    """

    _ = controlled_intersection_ids
    edges = sorted(
        (
            edge
            for edge in net.getEdges(withInternal=False)
            if not edge.isSpecial() and edge.allows("passenger")
        ),
        key=lambda edge: edge.getID(),
    )
    if not edges:
        raise ValueError("SUMO network has no passenger-capable road edges")
    midpoints = {edge.getID(): _edge_midpoint(edge) for edge in edges}
    xs = [point[0] for point in midpoints.values()]
    ys = [point[1] for point in midpoints.values()]
    boundary_fraction = 0.20
    west = _quantile(xs, boundary_fraction)
    east = _quantile(xs, 1.0 - boundary_fraction)
    south = _quantile(ys, boundary_fraction)
    north = _quantile(ys, 1.0 - boundary_fraction)
    zones = {
        "west_upstream": [edge for edge in edges if midpoints[edge.getID()][0] <= west],
        "east_bottleneck": [edge for edge in edges if midpoints[edge.getID()][0] >= east],
        "north_activity": [edge for edge in edges if midpoints[edge.getID()][1] >= north],
        "south_exit": [edge for edge in edges if midpoints[edge.getID()][1] <= south],
        "east_upstream": [edge for edge in edges if midpoints[edge.getID()][0] >= east],
        "west_exit": [edge for edge in edges if midpoints[edge.getID()][0] <= west],
        "network": edges,
    }
    empty = [name for name, candidates in zones.items() if not candidates]
    if empty:
        raise ValueError(f"derived traffic zones contain no edges: {empty}")
    return {name: sorted(value, key=lambda edge: edge.getID()) for name, value in zones.items()}


def _route(
    net: Any,
    origins: list[Any],
    destinations: list[Any],
    randomizer: random.Random,
    *,
    use_alternative: bool,
    central_edges: list[Any],
    controlled_intersection_ids: frozenset[str],
    minimum_controlled_intersections: int,
) -> tuple[list[Any], bool]:
    for _ in range(300):
        origin = randomizer.choice(origins)
        destination = randomizer.choice(destinations)
        if origin.getID() == destination.getID():
            continue
        if use_alternative and central_edges:
            via = randomizer.choice(central_edges)
            first = net.getOptimalPath(origin, via, vClass="passenger")
            second = net.getOptimalPath(via, destination, vClass="passenger")
            if first and second and first[0] and second[0]:
                candidate = [*first[0], *second[0][1:]]
                if (
                    len(candidate) >= 3
                    and len({edge.getID() for edge in candidate}) == len(candidate)
                    and _controlled_intersection_count(candidate, controlled_intersection_ids)
                    >= minimum_controlled_intersections
                ):
                    return candidate, True
        direct = net.getOptimalPath(origin, destination, vClass="passenger")
        if (
            direct
            and direct[0]
            and len(direct[0]) >= 2
            and _controlled_intersection_count(direct[0], controlled_intersection_ids)
            >= minimum_controlled_intersections
        ):
            return list(direct[0]), False
    raise RuntimeError("could not find a connected route for configured OD pair")


def _controlled_intersection_count(
    route: list[Any] | tuple[Any, ...],
    controlled_intersection_ids: frozenset[str],
) -> int:
    if not controlled_intersection_ids:
        return 0
    visited: set[str] = set()
    for edge in route:
        visited.add(edge.getFromNode().getID())
        visited.add(edge.getToNode().getID())
    return len(visited.intersection(controlled_intersection_ids))


def _parameter_route_bias(parameter_file: Path | None) -> float:
    """Derive a documented alternative-route share from organizer turn evidence."""

    if parameter_file is None or not parameter_file.is_file():
        return 0.25
    payload = json.loads(parameter_file.read_text(encoding="utf-8"))
    intersections = list(payload.get("intersections", {}).values())
    if not intersections:
        return 0.25
    turning = [
        float(item["turn_ratios"]["left"]) + float(item["turn_ratios"]["right"])
        for item in intersections
    ]
    return min(0.60, max(0.10, sum(turning) / len(turning)))


def prepare_demand_network(
    *,
    net_file: Path,
    scenario: ScenarioConfig,
    sumo_home: Path,
    selection_file: Path | None = None,
) -> PreparedDemandNetwork:
    """Precompute deterministic valid route alternatives for all OD pairs."""

    sumolib = _load_sumolib(sumo_home)
    net = sumolib.net.readNet(str(net_file), withPrograms=False)
    selection = (
        json.loads(selection_file.read_text(encoding="utf-8"))
        if selection_file is not None and selection_file.is_file()
        else {}
    )
    controlled_intersection_ids = frozenset(
        item["intersection_id"] for item in selection.get("intersections", [])
    )
    core_corridor_ids = frozenset(selection.get("core_corridor", []))
    minimum_controlled_intersections = 0
    zones = _zone_edges(net, controlled_intersection_ids)
    all_edges = zones["network"]
    xs = [_edge_midpoint(edge)[0] for edge in all_edges]
    ys = [_edge_midpoint(edge)[1] for edge in all_edges]
    if core_corridor_ids:
        central_edges = [
            edge
            for edge in all_edges
            if edge.getFromNode().getID() in core_corridor_ids
            or edge.getToNode().getID() in core_corridor_ids
        ]
    else:
        central_edges = [
            edge
            for edge in all_edges
            if _quantile(xs, 0.35) <= _edge_midpoint(edge)[0] <= _quantile(xs, 0.65)
            and _quantile(ys, 0.35) <= _edge_midpoint(edge)[1] <= _quantile(ys, 0.65)
        ]
    randomizer = random.Random(scenario.simulation.seed + 7919)
    pools: dict[tuple[str, str, str], tuple[list[list[str]], list[list[str]]]] = {}
    for demand in scenario.demand:
        key = (demand.origin_zone, demand.destination_zone, demand.route_scope)
        route_minimum = (
            5 if demand.route_scope == "controlled_corridor" and controlled_intersection_ids else 0
        )
        if key in pools:
            continue
        origins = zones.get(demand.origin_zone)
        destinations = zones.get(demand.destination_zone)
        if not origins or not destinations:
            raise ValueError(
                f"unsupported or empty OD zones: {demand.origin_zone}->{demand.destination_zone}"
            )
        direct_routes: list[list[str]] = []
        alternative_routes: list[list[str]] = []
        attempts = 0
        while len(direct_routes) < 12 and attempts < 60:
            route, _ = _route(
                net,
                origins,
                destinations,
                randomizer,
                use_alternative=False,
                central_edges=central_edges,
                controlled_intersection_ids=controlled_intersection_ids,
                minimum_controlled_intersections=route_minimum,
            )
            ids = [edge.getID() for edge in route]
            if ids not in direct_routes:
                direct_routes.append(ids)
            attempts += 1
        attempts = 0
        while len(alternative_routes) < 12 and attempts < 120:
            route, used = _route(
                net,
                origins,
                destinations,
                randomizer,
                use_alternative=True,
                central_edges=central_edges,
                controlled_intersection_ids=controlled_intersection_ids,
                minimum_controlled_intersections=route_minimum,
            )
            ids = [edge.getID() for edge in route]
            if used and ids not in direct_routes and ids not in alternative_routes:
                alternative_routes.append(ids)
            attempts += 1
        if not direct_routes:
            raise RuntimeError(f"no valid route pool for {key[0]}->{key[1]} ({key[2]})")
        pools[key] = (direct_routes, alternative_routes)
    route_controlled_visit_counts: dict[tuple[str, ...], int] = {}
    for direct_routes, alternative_routes in pools.values():
        for route_ids in [*direct_routes, *alternative_routes]:
            route_controlled_visit_counts[tuple(route_ids)] = _controlled_intersection_count(
                [net.getEdge(edge_id) for edge_id in route_ids],
                controlled_intersection_ids,
            )
    return PreparedDemandNetwork(
        route_pools=pools,
        route_controlled_visit_counts=route_controlled_visit_counts,
        controlled_intersection_ids=controlled_intersection_ids,
        minimum_controlled_intersections=minimum_controlled_intersections,
    )


def generate_routes(
    *,
    net_file: Path,
    route_file: Path,
    scenario: ScenarioConfig,
    sumo_home: Path,
    flow_multiplier: float | None = None,
    connected_vehicle_penetration: float | None = None,
    seed_offset: int = 0,
    parameter_file: Path | None = None,
    prepared_network: PreparedDemandNetwork | None = None,
) -> GeneratedDemand:
    """Generate explicit valid SUMO routes from one strict scenario configuration."""

    prepared = prepared_network or prepare_demand_network(
        net_file=net_file,
        scenario=scenario,
        sumo_home=sumo_home,
    )
    randomizer = random.Random(scenario.simulation.seed + seed_offset)
    actual_multiplier = scenario.flow_multiplier if flow_multiplier is None else flow_multiplier
    penetration = (
        scenario.connected_vehicle_penetration
        if connected_vehicle_penetration is None
        else connected_vehicle_penetration
    )
    ratios = _adjust_ratios_for_penetration(
        scenario.vehicle_type_ratios,
        penetration,
    )
    alternative_share = _parameter_route_bias(parameter_file)
    root = ET.Element("routes")
    vehicle_count = 0
    alternative_count = 0
    type_counts = {name: 0 for name in ratios}
    od_counts: dict[str, int] = {}
    scheduled: list[tuple[float, str, str, list[str], bool, int, str]] = []
    for od_index, demand in enumerate(scenario.demand):
        route_pools = prepared.route_pools.get(
            (demand.origin_zone, demand.destination_zone, demand.route_scope)
        )
        if route_pools is None:
            raise ValueError(
                f"OD route pool is absent: {demand.origin_zone}->{demand.destination_zone}"
            )
        direct_routes, alternative_routes = route_pools
        duration = demand.end_s - demand.begin_s
        count = round(demand.flow_veh_h * actual_multiplier * duration / 3600.0)
        od_key = f"{demand.origin_zone}->{demand.destination_zone}"
        od_counts[od_key] = count
        if count <= 0:
            continue
        headway = duration / count
        for index in range(count):
            depart = demand.begin_s + (index + 0.5) * headway
            depart += randomizer.uniform(-0.25, 0.25) * headway
            depart = min(demand.end_s - 0.001, max(demand.begin_s, depart))
            use_alternative = demand.route_alternatives and randomizer.random() < alternative_share
            alternative_used = use_alternative and bool(alternative_routes)
            choices = alternative_routes if alternative_used else direct_routes
            route = randomizer.choice(choices)
            vehicle_type = _weighted_choice(randomizer, ratios)
            scheduled.append(
                (
                    depart,
                    f"od{od_index:02d}_{index:05d}",
                    vehicle_type,
                    route,
                    alternative_used,
                    prepared.route_controlled_visit_counts.get(tuple(route), 0),
                    demand.route_scope,
                )
            )
    controlled_visit_counts: list[int] = []
    corridor_visit_counts: list[int] = []
    scope_counts = {"complete_network": 0, "controlled_corridor": 0}
    for (
        depart,
        identifier,
        vehicle_type,
        edges,
        alternative_used,
        controlled_visit_count,
        route_scope,
    ) in sorted(scheduled):
        vehicle = ET.SubElement(
            root,
            "vehicle",
            {
                "id": identifier,
                "type": vehicle_type,
                "depart": f"{depart:.3f}",
                "departLane": "best",
                "departSpeed": "max",
            },
        )
        ET.SubElement(vehicle, "route", {"edges": " ".join(edges)})
        vehicle_count += 1
        alternative_count += int(alternative_used)
        type_counts[vehicle_type] += 1
        controlled_visit_counts.append(controlled_visit_count)
        scope_counts[route_scope] += 1
        if route_scope == "controlled_corridor":
            corridor_visit_counts.append(controlled_visit_count)
    ET.indent(root, space="    ")
    route_file.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(route_file, encoding="utf-8", xml_declaration=True)
    return GeneratedDemand(
        route_file=route_file,
        vehicle_count=vehicle_count,
        vehicle_type_counts=type_counts,
        od_counts=od_counts,
        connected_vehicle_penetration=penetration,
        route_alternative_count=alternative_count,
        minimum_controlled_intersections_per_route=min(controlled_visit_counts, default=0),
        mean_controlled_intersections_per_route=(
            round(sum(controlled_visit_counts) / len(controlled_visit_counts), 3)
            if controlled_visit_counts
            else 0.0
        ),
        maximum_controlled_intersections_per_route=max(controlled_visit_counts, default=0),
        multi_intersection_vehicle_count=sum(count >= 2 for count in controlled_visit_counts),
        complete_network_vehicle_count=scope_counts["complete_network"],
        controlled_corridor_vehicle_count=scope_counts["controlled_corridor"],
        minimum_controlled_intersections_for_corridor_routes=min(corridor_visit_counts, default=0),
        sha256=_sha256(route_file),
    )


def demand_summary(demand: GeneratedDemand) -> dict[str, Any]:
    """Serialize a generated demand summary into a manifest-safe object."""

    return {
        "route_file": demand.route_file.name,
        "vehicle_count": demand.vehicle_count,
        "vehicle_type_counts": demand.vehicle_type_counts,
        "od_counts": demand.od_counts,
        "connected_vehicle_penetration": demand.connected_vehicle_penetration,
        "route_alternative_count": demand.route_alternative_count,
        "minimum_controlled_intersections_per_route": (
            demand.minimum_controlled_intersections_per_route
        ),
        "mean_controlled_intersections_per_route": (demand.mean_controlled_intersections_per_route),
        "maximum_controlled_intersections_per_route": (
            demand.maximum_controlled_intersections_per_route
        ),
        "multi_intersection_vehicle_count": demand.multi_intersection_vehicle_count,
        "complete_network_vehicle_count": demand.complete_network_vehicle_count,
        "controlled_corridor_vehicle_count": demand.controlled_corridor_vehicle_count,
        "minimum_controlled_intersections_for_corridor_routes": (
            demand.minimum_controlled_intersections_for_corridor_routes
        ),
        "network_scope": "complete_osm_network_not_bounded_to_controlled_intersections",
        "sha256": demand.sha256,
    }
