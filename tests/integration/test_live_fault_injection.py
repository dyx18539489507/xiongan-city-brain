"""Actual SUMO roadwork and communication impairment integration."""

import os
from pathlib import Path

import pytest

from traffic_platform.experiment_service.engine import (
    ExperimentControl,
    ExperimentRunner,
    smoke_config,
)


@pytest.mark.integration
async def test_roadwork_closes_lane_and_latency_reaches_bus(tmp_path: Path) -> None:
    sumo_home = os.environ.get("SUMO_HOME")
    if not sumo_home:
        pytest.skip("SUMO_HOME is not configured")
    control = ExperimentControl()
    control.inject_fault("roadwork", {})
    control.inject_fault("communication_latency", {"latency_ms": 500.0})
    config = smoke_config(
        "coordinated-max-pressure",
        duration_s=5.0,
        seed=11,
        result_root=tmp_path,
    )
    result = await ExperimentRunner(
        config,
        sumo_home=Path(sumo_home),
        control=control,
    ).run()
    assert any(
        event["event"] == "ROADWORK_LANE_CLOSED" for event in result["events"]
    )
    communication_events = result["communication_events"]
    assert isinstance(communication_events, list)
    assert any(
        event["actual_latency_ms"] == 500.0 for event in communication_events
    )
