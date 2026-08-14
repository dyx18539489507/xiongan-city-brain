"""Topology-conditioned transfer of organizer parameters to added OSM junctions."""

import csv
import hashlib
import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import networkx as nx
import numpy as np


@dataclass(frozen=True, slots=True)
class DonorFeatures:
    """Numerical organizer-derived features used by the transfer model."""

    intersection_number: int
    approach_count: int
    phase_count: float
    cycle_s: float
    peak_flow_veh_h: float
    lane_equivalent: float
    turn_ratios: dict[str, float]


@dataclass(frozen=True, slots=True)
class TargetFeatures:
    """OSM/SUMO topology features for one controlled target junction."""

    intersection_id: str
    approach_count: int
    incoming_lane_count: int
    phase_count: int
    mean_speed_m_s: float

    @property
    def capacity_index(self) -> float:
        """Return a relative lane-speed capacity proxy."""

        return self.incoming_lane_count * self.mean_speed_m_s


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_sumolib() -> Any:
    sumo_home = os.environ.get("SUMO_HOME")
    if not sumo_home:
        raise RuntimeError("SUMO_HOME is required for parameter transfer")
    tools = str(Path(sumo_home) / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import sumolib

    return sumolib


def _read_demand(demand_file: Path) -> tuple[float, dict[str, float]]:
    interval_totals: dict[tuple[str, str], float] = {}
    turn_totals = {"left": 0.0, "straight": 0.0, "right": 0.0}
    with demand_file.open("r", encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            if row["traffic_profile"] != "early_peak":
                continue
            flow = float(row["flow"])
            interval_key = (row["interval_start"], row["interval_end"])
            interval_totals[interval_key] = interval_totals.get(interval_key, 0.0) + flow
            turn = row["turn"]
            if turn in turn_totals:
                turn_totals[turn] += flow
    if not interval_totals:
        raise ValueError(f"no early_peak demand in {demand_file}")
    peak_flow = max(interval_totals.values()) * 4.0
    smoothed_total = sum(turn_totals.values()) + 3.0
    ratios = {
        turn: (flow + 1.0) / smoothed_total for turn, flow in turn_totals.items()
    }
    return peak_flow, ratios


def load_donors(processed_root: Path) -> tuple[list[DonorFeatures], list[dict[str, str]]]:
    """Read organizer-derived numeric data without modifying its source files."""

    catalog_path = (
        processed_root.parents[1] / "catalogs" / "intersection_catalog.csv"
    )
    with catalog_path.open("r", encoding="utf-8-sig", newline="") as source:
        catalog = {
            int(row["intersection_id"].split("_")[-1]): row
            for row in csv.DictReader(source)
        }
    donors: list[DonorFeatures] = []
    source_files: list[dict[str, str]] = [
        {"path": str(catalog_path), "sha256": _sha256(catalog_path)}
    ]
    for number in range(1, 21):
        demand_file = (
            processed_root / f"intersection_{number:02d}" / "demand.csv"
        )
        peak_flow, turn_ratios = _read_demand(demand_file)
        row = catalog[number]
        approach_count = int(row["approach_count"])
        phase_count = (
            float(row["phase_count_min"]) + float(row["phase_count_max"])
        ) / 2
        cycle_s = (
            float(row["cycle_seconds_min"]) + float(row["cycle_seconds_max"])
        ) / 2
        lane_equivalent = max(
            float(approach_count),
            math.ceil(peak_flow / (1600.0 * 0.8)),
        )
        donors.append(
            DonorFeatures(
                intersection_number=number,
                approach_count=approach_count,
                phase_count=phase_count,
                cycle_s=cycle_s,
                peak_flow_veh_h=peak_flow,
                lane_equivalent=lane_equivalent,
                turn_ratios=turn_ratios,
            )
        )
        source_files.append({"path": str(demand_file), "sha256": _sha256(demand_file)})
    return donors, source_files


def target_features(
    net_file: Path,
    controlled_intersection_ids: list[str],
) -> list[TargetFeatures]:
    """Extract target topology and capacity proxies from the generated SUMO net."""

    sumolib = _load_sumolib()
    net = sumolib.net.readNet(str(net_file), withPrograms=True)
    result: list[TargetFeatures] = []
    for identifier in controlled_intersection_ids:
        node = net.getNode(identifier)
        incoming = [
            edge for edge in node.getIncoming() if not edge.isSpecial()
        ]
        lanes = [lane for edge in incoming for lane in edge.getLanes()]
        speeds = [float(lane.getSpeed()) for lane in lanes]
        tls_id = node.getTLSID()
        tls = net.getTLS(tls_id) if tls_id else None
        phase_counts = (
            [len(program.getPhases()) for program in tls.getPrograms().values()]
            if tls is not None
            else []
        )
        result.append(
            TargetFeatures(
                intersection_id=identifier,
                approach_count=max(1, len(incoming)),
                incoming_lane_count=max(1, len(lanes)),
                phase_count=max(2, min(8, min(phase_counts, default=2))),
                mean_speed_m_s=sum(speeds) / len(speeds) if speeds else 13.9,
            )
        )
    return result


def _normalize(value: float, values: list[float]) -> float:
    low = min(values)
    high = max(values)
    return 0.5 if high <= low else (value - low) / (high - low)


def _gower_distances(
    target: TargetFeatures,
    donors: list[DonorFeatures],
    all_targets: list[TargetFeatures],
) -> list[tuple[float, DonorFeatures]]:
    donor_flows = [donor.peak_flow_veh_h for donor in donors]
    target_capacities = [item.capacity_index for item in all_targets]
    distances: list[tuple[float, DonorFeatures]] = []
    for donor in donors:
        parts = [
            abs(target.approach_count - donor.approach_count) / 3.0,
            abs(target.incoming_lane_count - donor.lane_equivalent)
            / max(1.0, max(item.incoming_lane_count for item in all_targets)),
            abs(target.phase_count - donor.phase_count) / 6.0,
            abs(
                _normalize(target.capacity_index, target_capacities)
                - _normalize(donor.peak_flow_veh_h, donor_flows)
            ),
        ]
        distances.append((sum(parts) / len(parts), donor))
    return sorted(distances, key=lambda item: (item[0], item[1].intersection_number))


def _weighted_transfer(
    target: TargetFeatures,
    candidates: list[tuple[float, DonorFeatures]],
) -> tuple[float, dict[str, float], float, list[dict[str, float | int]]]:
    nearest = candidates[:3]
    raw_weights = [1.0 / (distance + 0.05) ** 2 for distance, _ in nearest]
    total_weight = sum(raw_weights)
    weights = [weight / total_weight for weight in raw_weights]
    donor_flow = sum(
        weight * donor.peak_flow_veh_h
        for weight, (_, donor) in zip(weights, nearest, strict=True)
    )
    donor_lanes = sum(
        weight * donor.lane_equivalent
        for weight, (_, donor) in zip(weights, nearest, strict=True)
    )
    capacity_scale = math.sqrt(target.incoming_lane_count / max(donor_lanes, 1.0))
    transferred_flow = donor_flow * min(1.6, max(0.6, capacity_scale))
    turns = {
        turn: sum(
            weight * donor.turn_ratios[turn]
            for weight, (_, donor) in zip(weights, nearest, strict=True)
        )
        for turn in ("left", "straight", "right")
    }
    turns_total = sum(turns.values())
    turns = {turn: value / turns_total for turn, value in turns.items()}
    donor_cycle = sum(
        weight * donor.cycle_s
        for weight, (_, donor) in zip(weights, nearest, strict=True)
    )
    evidence = [
        {
            "donor_intersection": donor.intersection_number,
            "gower_distance": round(distance, 6),
            "inverse_square_weight": round(weight, 6),
        }
        for weight, (distance, donor) in zip(weights, nearest, strict=True)
    ]
    return transferred_flow, turns, donor_cycle, evidence


def _webster_cycle(
    flow_veh_h: float,
    incoming_lanes: int,
    phase_count: int,
    donor_cycle_s: float,
) -> float:
    lost_time = phase_count * 4.0
    saturation_capacity = max(1.0, incoming_lanes * 1800.0)
    critical_ratio = min(0.88, flow_veh_h / saturation_capacity)
    formula_cycle = (1.5 * lost_time + 5.0) / max(0.12, 1.0 - critical_ratio)
    blended = 0.6 * formula_cycle + 0.4 * donor_cycle_s
    return round(min(180.0, max(60.0, blended)), 1)


def _spatially_balance(
    raw_flows: dict[str, float],
    coordinates: dict[str, tuple[float, float]],
    *,
    regularization: float = 0.35,
) -> dict[str, float]:
    graph: nx.Graph[str] = nx.Graph()
    graph.add_nodes_from(raw_flows)
    complete: nx.Graph[str] = nx.Graph()
    for left in raw_flows:
        for right in raw_flows:
            if left >= right:
                continue
            left_lon, left_lat = coordinates[left]
            right_lon, right_lat = coordinates[right]
            distance = math.hypot(
                (left_lon - right_lon) * 86_000,
                (left_lat - right_lat) * 111_000,
            )
            complete.add_edge(left, right, weight=max(distance, 1.0))
    graph.add_edges_from(nx.minimum_spanning_edges(complete, data=True))
    identifiers = sorted(raw_flows)
    laplacian = nx.laplacian_matrix(graph, nodelist=identifiers, weight="weight").toarray()
    scale = max(float(np.max(np.diag(laplacian))), 1.0)
    system = np.eye(len(identifiers)) + regularization * laplacian / scale
    raw = np.array([raw_flows[identifier] for identifier in identifiers])
    balanced = np.linalg.solve(system, raw)
    balanced *= raw.sum() / balanced.sum()
    return {
        identifier: round(max(0.0, float(value)), 3)
        for identifier, value in zip(identifiers, balanced, strict=True)
    }


def transfer_parameters(
    processed_root: Path,
    net_file: Path,
    selection_file: Path,
) -> dict[str, Any]:
    """Transfer organizer demand and timing with explicit provenance and uncertainty."""

    selection = json.loads(selection_file.read_text(encoding="utf-8"))
    identifiers = [
        item["intersection_id"] for item in selection["intersections"]
    ]
    targets = target_features(net_file, identifiers)
    donors, source_files = load_donors(processed_root)
    donor_by_number = {donor.intersection_number: donor for donor in donors}
    retained_by_node = {
        item["sumo_junction_id"]: int(item["demo_id"].split("_")[-1])
        for item in selection["retained_organizer_location_matches"]
    }
    # The connected control area retains six organizer locations.  The added
    # OSM junctions must therefore be estimated from the *remaining* organizer
    # workbooks, not from the obsolete demo_1..demo_12 donor pool that belonged
    # to the earlier eight-anchor/twelve-added design.
    retained_numbers = set(retained_by_node.values())
    model_donors = [
        donor
        for donor in donors
        if donor.intersection_number not in retained_numbers
    ]
    transferred: dict[str, dict[str, Any]] = {}
    raw_flows: dict[str, float] = {}
    for target in targets:
        retained_number = retained_by_node.get(target.intersection_id)
        if retained_number is not None:
            donor = donor_by_number[retained_number]
            flow = donor.peak_flow_veh_h
            turns = donor.turn_ratios
            donor_cycle = donor.cycle_s
            evidence: list[dict[str, float | int]] = [
                {
                    "donor_intersection": retained_number,
                    "gower_distance": 0.0,
                    "inverse_square_weight": 1.0,
                }
            ]
            provenance = "organizer_supplied_assigned_to_registered_location"
        else:
            distances = _gower_distances(target, model_donors, targets)
            flow, turns, donor_cycle, evidence = _weighted_transfer(target, distances)
            provenance = "modeled_from_organizer_data"
        raw_flows[target.intersection_id] = flow
        transferred[target.intersection_id] = {
            "parameter_provenance": provenance,
            "target_features": {
                "approach_count": target.approach_count,
                "incoming_lane_count": target.incoming_lane_count,
                "phase_count": target.phase_count,
                "mean_speed_m_s": round(target.mean_speed_m_s, 3),
            },
            "raw_peak_flow_veh_h": round(flow, 3),
            "turn_ratios": {key: round(value, 6) for key, value in turns.items()},
            "donor_cycle_s": round(donor_cycle, 3),
            "donors": evidence,
        }
    coordinates = {
        item["intersection_id"]: (float(item["lon"]), float(item["lat"]))
        for item in selection["intersections"]
    }
    balanced = _spatially_balance(raw_flows, coordinates)
    for target in targets:
        item = transferred[target.intersection_id]
        item["balanced_peak_flow_veh_h"] = balanced[target.intersection_id]
        item["recommended_cycle_s"] = _webster_cycle(
            balanced[target.intersection_id],
            target.incoming_lane_count,
            target.phase_count,
            float(item["donor_cycle_s"]),
        )
        lost_ratio = min(
            0.35,
            target.phase_count * 4.0 / float(item["recommended_cycle_s"]),
        )
        item["effective_green_ratio"] = round(1.0 - lost_ratio, 6)
    return {
        "schema_version": "1.0",
        "method": {
            "distance": "four-feature_gower",
            "neighbors": 3,
            "weighting": "inverse_square_with_epsilon_0.05",
            "capacity_scaling": "sqrt_lane_equivalent_ratio_clamped_0.6_1.6",
            "turn_smoothing": "dirichlet_alpha_1",
            "network_balancing": "minimum_spanning_graph_laplacian_regularization",
            "signal_timing": "webster_cycle_blended_60pct_formula_40pct_donor",
            "modeled_donor_pool": [
                donor.intersection_number for donor in model_donors
            ],
        },
        "evidence_boundary": (
            "Organizer-derived observations are assigned only to retained demo_14, "
            "demo_15, demo_17, demo_18, demo_19, and demo_20 anchors; all other "
            "junction values are modeled estimates, not field measurements."
        ),
        "source_files": source_files,
        "intersections": transferred,
        "total_raw_peak_flow_veh_h": round(sum(raw_flows.values()), 3),
        "total_balanced_peak_flow_veh_h": round(sum(balanced.values()), 3),
    }
