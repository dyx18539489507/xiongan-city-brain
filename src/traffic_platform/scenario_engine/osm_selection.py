"""Select the compact, connected 20-intersection Rongdong control area."""

from __future__ import annotations

import heapq
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

import networkx as nx
from networkx.algorithms.approximation import steiner_tree

RETAINED_ORGANIZER_DEMOS = frozenset(
    {"demo_14", "demo_15", "demo_17", "demo_18", "demo_19", "demo_20"}
)
EXCLUDED_ORGANIZER_DEMOS = frozenset({"demo_13", "demo_16"})
MIN_INTERSECTION_DEGREE = 3
SELECTION_DISTANCE_WEIGHT = 0.001
MAX_DIRECT_ADJACENCY_M = 350.0


def _load_sumolib() -> Any:
    sumo_home = os.environ.get("SUMO_HOME")
    if not sumo_home:
        raise RuntimeError("SUMO_HOME is required to select OSM intersections")
    tools = str(Path(sumo_home) / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import sumolib

    return sumolib


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    radius = 6_371_000.0
    lon1, lat1 = map(math.radians, a)
    lon2, lat2 = map(math.radians, b)
    delta_lon = lon2 - lon1
    delta_lat = lat2 - lat1
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(value))


def _add_minimum_edge(
    graph: nx.Graph[str], left: str, right: str, weight: float
) -> None:
    current = graph.get_edge_data(left, right, {}).get("weight", math.inf)
    if weight < current:
        graph.add_edge(left, right, weight=weight)


def _build_road_graph(net: Any) -> nx.Graph[str]:
    graph: nx.Graph[str] = nx.Graph()
    for edge in net.getEdges():
        if edge.isSpecial():
            continue
        _add_minimum_edge(
            graph,
            edge.getFromNode().getID(),
            edge.getToNode().getID(),
            max(float(edge.getLength()), 0.1),
        )
    return graph


def _build_direct_intersection_graph(
    road_graph: nx.Graph[str], intersection_ids: set[str]
) -> nx.Graph[str]:
    """Contract road geometry between adjacent, degree-three-plus junctions."""

    graph: nx.Graph[str] = nx.Graph()
    graph.add_nodes_from(sorted(intersection_ids))
    for source in sorted(intersection_ids):
        queue: list[tuple[float, str]] = [(0.0, source)]
        distances = {source: 0.0}
        while queue:
            distance, node_id = heapq.heappop(queue)
            if distance > distances[node_id]:
                continue
            if node_id != source and node_id in intersection_ids:
                _add_minimum_edge(graph, source, node_id, distance)
                continue
            for neighbor in sorted(road_graph.neighbors(node_id)):
                candidate = distance + float(road_graph[node_id][neighbor]["weight"])
                if candidate < distances.get(neighbor, math.inf):
                    distances[neighbor] = candidate
                    heapq.heappush(queue, (candidate, neighbor))
    return graph


def _assign_organizer_anchors(
    *,
    official_data: dict[str, Any],
    eligible_coordinates: dict[str, tuple[float, float]],
    all_coordinates: dict[str, tuple[float, float]],
    network_nodes: dict[str, Any],
) -> list[dict[str, Any]]:
    candidates: list[tuple[float, str, str, tuple[float, float]]] = []
    for feature in official_data["features"]:
        demo_id = feature["properties"]["demo_id"]
        if demo_id not in RETAINED_ORGANIZER_DEMOS:
            continue
        estimate = tuple(feature["geometry"]["coordinates"])
        for node_id, coordinate in eligible_coordinates.items():
            candidates.append(
                (_haversine_m(estimate, coordinate), demo_id, node_id, estimate)
            )
    assigned_demos: set[str] = set()
    assigned_nodes: set[str] = set()
    retained: list[dict[str, Any]] = []
    for distance, demo_id, node_id, estimate in sorted(candidates):
        if demo_id in assigned_demos or node_id in assigned_nodes:
            continue
        assigned_demos.add(demo_id)
        assigned_nodes.add(node_id)
        original_type = network_nodes[node_id].getType()
        retained.append(
            {
                "demo_id": demo_id,
                "sumo_junction_id": node_id,
                "registration_estimate_lon_lat": list(estimate),
                "sumo_lon_lat": list(all_coordinates[node_id]),
                "nearest_distance_m": round(distance, 2),
                "provenance": "organizer_png_registration_estimate",
                "original_sumo_junction_type": original_type,
                "requires_signalization": original_type
                not in {"traffic_light", "traffic_light_unregulated"},
            }
        )
    if assigned_demos != RETAINED_ORGANIZER_DEMOS:
        missing = sorted(RETAINED_ORGANIZER_DEMOS - assigned_demos)
        raise RuntimeError(f"could not assign organizer anchors: {missing}")
    return sorted(retained, key=lambda item: item["demo_id"])


def _select_compact_nodes(
    intersection_graph: nx.Graph[str], anchor_ids: set[str], count: int
) -> set[str]:
    component_nodes = nx.node_connected_component(
        intersection_graph, next(iter(anchor_ids))
    )
    if not anchor_ids <= component_nodes:
        raise RuntimeError("retained organizer anchors are not road-connected")
    component = intersection_graph.subgraph(component_nodes).copy()
    for _, _, data in component.edges(data=True):
        data["selection_cost"] = 1.0 + (
            SELECTION_DISTANCE_WEIGHT * float(data["weight"])
        )
    connector = steiner_tree(
        component,
        anchor_ids,
        weight="selection_cost",
        method="kou",
    )
    selected = set(connector.nodes)
    if len(selected) > count:
        raise RuntimeError(
            f"compact anchor connector needs {len(selected)} nodes, exceeding {count}"
        )
    while len(selected) < count:
        candidates: list[tuple[int, float, float, str]] = []
        for node_id in sorted(component.nodes - selected):
            adjacent_weights = [
                float(component[node_id][neighbor]["weight"])
                for neighbor in component.neighbors(node_id)
                if neighbor in selected
            ]
            if not adjacent_weights:
                continue
            candidates.append(
                (
                    -len(adjacent_weights),
                    max(adjacent_weights),
                    sum(adjacent_weights) / len(adjacent_weights),
                    node_id,
                )
            )
        if not candidates:
            raise RuntimeError("no directly adjacent intersection candidate remains")
        selected.add(min(candidates)[3])
    return selected


def _select_core_corridor(
    graph: nx.Graph[str], anchor_ids: set[str], maximum_nodes: int = 8
) -> list[str]:
    candidate_paths: list[tuple[float, list[str]]] = []
    for index, source in enumerate(sorted(anchor_ids)):
        for target in sorted(anchor_ids)[index + 1 :]:
            path = nx.shortest_path(graph, source, target, weight="weight")
            distance = nx.path_weight(graph, path, weight="weight")
            candidate_paths.append((float(distance), path))
    path = max(candidate_paths, key=lambda item: (item[0], item[1]))[1]
    if len(path) < 5:
        all_paths: list[tuple[float, list[str]]] = []
        for index, source in enumerate(sorted(graph.nodes)):
            for target in sorted(graph.nodes)[index + 1 :]:
                candidate = nx.shortest_path(graph, source, target, weight="weight")
                all_paths.append(
                    (
                        float(nx.path_weight(graph, candidate, weight="weight")),
                        candidate,
                    )
                )
        path = max(all_paths, key=lambda item: (item[0], item[1]))[1]
    if len(path) <= maximum_nodes:
        return path
    windows = [
        path[index : index + maximum_nodes]
        for index in range(len(path) - maximum_nodes + 1)
    ]
    return max(
        windows,
        key=lambda window: (
            len(anchor_ids.intersection(window)),
            nx.path_weight(graph, window, weight="weight"),
            window,
        ),
    )


def _assign_stable_display_ids(
    nodes: list[dict[str, Any]],
    core_corridor: list[str],
) -> None:
    """Assign deterministic, human-readable IDs without changing SUMO IDs.

    ``K`` identifies the ordered core corridor (核心走廊), while ``B``
    identifies background controlled junctions.  The SUMO junction ID remains
    the machine integration key and is never rewritten.
    """

    by_id = {str(node["intersection_id"]): node for node in nodes}
    for index, intersection_id in enumerate(core_corridor, start=1):
        node = by_id[intersection_id]
        node["display_id"] = f"K{index:02d}"
        node["display_name"] = f"核心走廊路口 K{index:02d}"
        node["control_group"] = "core_corridor"
    background = sorted(
        (node for node in nodes if "display_id" not in node),
        key=lambda node: (
            -float(node["lat"]),
            float(node["lon"]),
            str(node["intersection_id"]),
        ),
    )
    for index, node in enumerate(background, start=1):
        node["display_id"] = f"B{index:02d}"
        node["display_name"] = f"背景控制路口 B{index:02d}"
        node["control_group"] = "background"
    for node in nodes:
        anchor = node.get("location_anchor")
        node["source_label"] = (
            f"{node['display_id']} / {anchor}" if anchor else node["display_id"]
        )


def select_controlled_intersections(
    net_file: Path,
    official_geojson: Path,
    *,
    count: int = 20,
) -> dict[str, Any]:
    """Select six official anchors plus fourteen compact OSM intersections."""

    if count < len(RETAINED_ORGANIZER_DEMOS):
        raise ValueError("count cannot be smaller than the six retained anchors")
    sumolib = _load_sumolib()
    net = sumolib.net.readNet(str(net_file), withInternal=False)
    road_graph = _build_road_graph(net)
    network_nodes = {
        node.getID(): node for node in net.getNodes() if node.getID() in road_graph
    }
    all_coordinates = {
        node_id: tuple(net.convertXY2LonLat(*node.getCoord()))
        for node_id, node in network_nodes.items()
    }
    eligible_ids = {
        node_id
        for node_id in network_nodes
        if road_graph.degree(node_id) >= MIN_INTERSECTION_DEGREE
    }
    eligible_coordinates = {
        node_id: all_coordinates[node_id] for node_id in eligible_ids
    }
    official_data = json.loads(official_geojson.read_text(encoding="utf-8"))
    retained = _assign_organizer_anchors(
        official_data=official_data,
        eligible_coordinates=eligible_coordinates,
        all_coordinates=all_coordinates,
        network_nodes=network_nodes,
    )
    anchor_ids = {item["sumo_junction_id"] for item in retained}
    intersection_graph = _build_direct_intersection_graph(road_graph, eligible_ids)
    selected = _select_compact_nodes(intersection_graph, anchor_ids, count)
    topology = intersection_graph.subgraph(selected).copy()
    if not nx.is_connected(topology):
        raise RuntimeError("selected direct-adjacency intersection graph is disconnected")
    edge_lengths = [float(data["weight"]) for _, _, data in topology.edges(data=True)]
    if not edge_lengths or max(edge_lengths) > MAX_DIRECT_ADJACENCY_M:
        raise RuntimeError(
            "selected topology is not a compact narrow-road network: "
            f"maximum direct adjacency is {max(edge_lengths, default=0.0):.2f} m"
        )
    core_corridor = _select_core_corridor(topology, anchor_ids)
    nodes = [
        {
            "intersection_id": node_id,
            "x": float(network_nodes[node_id].getCoord()[0]),
            "y": float(network_nodes[node_id].getCoord()[1]),
            "lon": all_coordinates[node_id][0],
            "lat": all_coordinates[node_id][1],
            "role": "core_corridor" if node_id in core_corridor else "controlled",
            "parameter_provenance": (
                "organizer_supplied"
                if node_id in anchor_ids
                else "modeled_from_organizer_data"
            ),
            "location_anchor": next(
                (
                    item["demo_id"]
                    for item in retained
                    if item["sumo_junction_id"] == node_id
                ),
                None,
            ),
            "original_sumo_junction_type": network_nodes[node_id].getType(),
        }
        for node_id in sorted(selected)
    ]
    _assign_stable_display_ids(nodes, core_corridor)
    requires_signalization = sorted(
        node_id
        for node_id in selected
        if network_nodes[node_id].getType()
        not in {"traffic_light", "traffic_light_unregulated"}
    )
    return {
        "schema_version": "1.2",
        "network_provenance": "OpenStreetMap",
        "geography_claim": "real_geography_engineering_model_not_field_calibrated",
        "selection_method": (
            "six_registered_organizer_anchors_plus_compact_directly_adjacent_"
            "osm_intersections"
        ),
        "topology_definition": (
            "directly_adjacent_intersections_with_no_unselected_degree_3_"
            "intersection_between"
        ),
        "controlled_intersection_count": len(nodes),
        "controlled_meta_graph_connected": True,
        "controlled_direct_adjacency_graph_connected": True,
        "retained_official_demo_ids": sorted(RETAINED_ORGANIZER_DEMOS),
        "excluded_official_demo_ids": sorted(EXCLUDED_ORGANIZER_DEMOS),
        "exclusion_reason": (
            "demo_13 and demo_16 remain in organizer assets but are outside the "
            "compact main control area"
        ),
        "retained_organizer_location_matches": retained,
        "requires_signalization": requires_signalization,
        "added_osm_intersection_count": count - len(retained),
        "core_corridor": core_corridor,
        "core_corridor_intersection_count": len(core_corridor),
        "topology_edge_count": topology.number_of_edges(),
        "maximum_direct_adjacency_m": round(max(edge_lengths), 2),
        "mean_direct_adjacency_m": round(sum(edge_lengths) / len(edge_lengths), 2),
        "topology_edges": [
            {
                "source": source_node,
                "target": target_node,
                "road_distance_m": round(float(data["weight"]), 2),
            }
            for source_node, target_node, data in sorted(
                topology.edges(data=True), key=lambda item: (item[0], item[1])
            )
        ],
        "intersections": nodes,
    }


def selection_geojson(selection: dict[str, Any]) -> dict[str, Any]:
    """Convert a selection manifest into a web-map compatible GeoJSON."""

    return {
        "type": "FeatureCollection",
        "name": "xiongan_rongdong_20_controlled_intersections",
        "properties": {
            "geography_claim": selection["geography_claim"],
            "controlled_direct_adjacency_graph_connected": selection[
                "controlled_direct_adjacency_graph_connected"
            ],
            "retained_official_demo_ids": selection["retained_official_demo_ids"],
            "excluded_official_demo_ids": selection["excluded_official_demo_ids"],
        },
        "features": [
            {
                "type": "Feature",
                "properties": {
                    key: value
                    for key, value in node.items()
                    if key not in {"x", "y", "lon", "lat"}
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [node["lon"], node["lat"]],
                },
            }
            for node in selection["intersections"]
        ],
    }
