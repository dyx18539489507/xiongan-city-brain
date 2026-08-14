"""Scenario YAML validation and deterministic manifest primitives."""

import json
from pathlib import Path

from traffic_platform.scenario_engine.manifest import sha256_file
from traffic_platform.scenario_engine.models import ScenarioConfig


def test_rongdong_scenario_is_complete_and_not_claimed_measured() -> None:
    config = ScenarioConfig.from_yaml(Path("scenarios/configs/xiongan_rongdong_20.yaml"))
    assert config.scenario_id == "xiongan_rongdong_20"
    assert config.is_real_measured_network is False
    assert len(config.disturbances) >= 3
    assert sum(config.vehicle_type_ratios.values()) == 1.0
    assert config.multimodal.enabled is True
    assert config.multimodal.network_scope == "complete_osm_network"
    assert config.multimodal.pedestrian_signal_mode == "conditional_parallel"
    assert {item.participant for item in config.multimodal.demands} == {
        "bicycle",
        "electric_bicycle",
        "pedestrian",
    }


def test_hash_is_reproducible() -> None:
    path = Path("scenarios/configs/xiongan_rongdong_20.yaml")
    assert sha256_file(path) == sha256_file(path)


def test_connected_selection_is_compact_and_preserves_six_anchors() -> None:
    selection = json.loads(
        Path("scenarios/generated/xiongan_rongdong_20/controlled_intersections.json").read_text(
            encoding="utf-8"
        )
    )
    assert selection["controlled_intersection_count"] == 20
    assert selection["retained_official_demo_ids"] == [
        "demo_14",
        "demo_15",
        "demo_17",
        "demo_18",
        "demo_19",
        "demo_20",
    ]
    assert selection["excluded_official_demo_ids"] == ["demo_13", "demo_16"]
    assert selection["added_osm_intersection_count"] == 14
    assert selection["controlled_direct_adjacency_graph_connected"] is True
    assert sorted(item["display_id"] for item in selection["intersections"]) == [
        *(f"B{index:02d}" for index in range(1, 13)),
        *(f"K{index:02d}" for index in range(1, 9)),
    ]
    assert len({item["display_id"] for item in selection["intersections"]}) == 20
    assert 5 <= len(selection["core_corridor"]) <= 8
    assert selection["maximum_direct_adjacency_m"] <= 350.0
    topology_pairs = {
        frozenset((edge["source"], edge["target"])) for edge in selection["topology_edges"]
    }
    assert all(
        frozenset((left, right)) in topology_pairs
        for left, right in zip(
            selection["core_corridor"],
            selection["core_corridor"][1:],
            strict=False,
        )
    )


def test_generated_od_combines_full_network_and_controlled_corridor_routes() -> None:
    profiles = json.loads(
        Path("scenarios/generated/xiongan_rongdong_20/profiles_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    summaries = [
        profiles["base_route_generation"],
        *(profile["route_generation"] for profile in profiles["profiles"]),
    ]
    assert all(summary["complete_network_vehicle_count"] > 0 for summary in summaries)
    assert all(
        summary["controlled_corridor_vehicle_count"] > 0
        and summary["minimum_controlled_intersections_for_corridor_routes"] >= 5
        for summary in summaries
    )
    assert all(
        summary["network_scope"] == "complete_osm_network_not_bounded_to_controlled_intersections"
        for summary in summaries
    )
