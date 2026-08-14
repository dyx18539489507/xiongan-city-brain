"""Actual cloud outage, edge autonomy and smooth recovery demonstration."""

import os
from dataclasses import replace
from pathlib import Path

import pytest

from traffic_platform.edge_service.state_machine import DegradationConfig
from traffic_platform.experiment_service.engine import ExperimentRunner, smoke_config


@pytest.mark.chaos
@pytest.mark.asyncio
async def test_cloud_outage_enters_autonomy_and_recovers(tmp_path: Path) -> None:
    sumo_home = os.environ.get("SUMO_HOME")
    if not sumo_home:
        pytest.skip("SUMO_HOME is not configured")
    base = smoke_config(
        "coordinated-max-pressure",
        duration_s=20.0,
        result_root=tmp_path,
    )
    config = replace(
        base,
        cloud_outage_start_s=6.0,
        cloud_outage_duration_s=10.0,
        degradation_config=DegradationConfig(
            hold_timeout_s=6.0,
            autonomous_timeout_s=8.0,
            recovery_stable_s=2.0,
        ),
    )
    result = await ExperimentRunner(
        config,
        sumo_home=Path(sumo_home),
    ).run()
    modes = {sample["fallback_mode"] for sample in result["samples"]}
    event_names = {event["event"] for event in result["events"]}
    assert "HOLD_LAST_VALID" in modes
    assert "EDGE_AUTONOMOUS" in modes
    assert "RECOVERY_SYNC" in modes
    assert "CLOUD_COORDINATED" in modes
    assert {"CLOUD_OFFLINE_INJECTED", "CLOUD_RECOVERED"} <= event_names

