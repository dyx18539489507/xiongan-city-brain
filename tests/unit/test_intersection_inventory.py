"""Traceable controlled-intersection inventory tests."""

import json
from pathlib import Path


def test_inventory_has_stable_ids_and_lane_level_evidence() -> None:
    payload = json.loads(
        Path(
            "scenarios/generated/xiongan_rongdong_20/intersection_inventory.json"
        ).read_text(encoding="utf-8")
    )
    assert payload["network_scope"] == "complete_rongdong_osm_network_not_cropped"
    assert payload["intersection_count"] == 20
    assert len({item["display_id"] for item in payload["intersections"]}) == 20
    assert all(item["incoming_approaches"] for item in payload["intersections"])
    assert all(item["outgoing_approaches"] for item in payload["intersections"])
    assert all(item["movements"] for item in payload["intersections"])
    assert all(item["signal_programs"] for item in payload["intersections"])
    assert all(item["topology_neighbors"] for item in payload["intersections"])
