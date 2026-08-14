"""Actual Runner-to-digital-twin callback smoke evidence."""

import os
from pathlib import Path

import pytest

from traffic_platform.experiment_service.engine import ExperimentRunner, smoke_config
from traffic_platform.realtime import DigitalTwinSourceFrame


@pytest.mark.performance
async def test_runner_publishes_real_multimodal_entity_frames(tmp_path: Path) -> None:
    sumo_home = os.environ.get("SUMO_HOME")
    if not sumo_home:
        pytest.skip("SUMO_HOME is not configured")
    frames: list[DigitalTwinSourceFrame] = []
    config = smoke_config(
        "fixed-time",
        duration_s=5.0,
        seed=42,
        result_root=tmp_path,
    )
    await ExperimentRunner(
        config,
        sumo_home=Path(sumo_home),
        digital_twin_callback=frames.append,
    ).run()

    assert [frame.simulation_time_s for frame in frames] == [1, 2, 3, 4, 5]
    assert all(frame.scenario_id == "xiongan_rongdong_20" for frame in frames)
    assert all(frame.tick_hz == 1.0 for frame in frames)
    assert all(len(frame.traffic_lights) == 20 for frame in frames)
    assert any(frame.vehicles or frame.pedestrians for frame in frames)

