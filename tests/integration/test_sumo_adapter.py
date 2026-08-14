"""Real SUMO-to-adapter collection and actuation smoke test."""

import json
import os
from pathlib import Path

import pytest

from traffic_platform.sumo_adapter import TraciSumoAdapter


@pytest.mark.integration
def test_real_sumo_state_and_phase_control() -> None:
    sumo_home = os.environ.get("SUMO_HOME")
    if not sumo_home:
        pytest.skip("SUMO_HOME is not configured")
    scenario = Path(
        "scenarios/generated/xiongan_rongdong_20/xiongan_rongdong_20.sumocfg"
    )
    selection_path = Path(
        "scenarios/generated/xiongan_rongdong_20/controlled_intersections.json"
    )
    if not scenario.is_file() or not selection_path.is_file():
        pytest.skip("generated Rongdong scenario is not available")
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    intersection_id = selection["intersections"][0]["intersection_id"]
    with TraciSumoAdapter(
        sumo_home=Path(sumo_home),
        label="pytest-integration",
    ) as adapter:
        port = adapter.start_simulation(scenario, seed=42)
        states = [adapter.step() for _ in range(10)]
        signal = adapter.get_intersection_state(intersection_id)
        adapter.set_phase_duration(intersection_id, 2.0)
        assert port is not None
        assert states[-1].simulation_time_s == 10.0
        assert states[-1].vehicle_count > 0
        assert signal.controlled_lane_ids

