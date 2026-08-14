"""Real SUMO execution of the compressed S03-S06 disturbance schedule."""

import os
from dataclasses import replace
from pathlib import Path

import pytest

from traffic_platform.experiment_service.engine import ExperimentRunner, smoke_config


@pytest.mark.integration
async def test_scheduled_disturbances_reach_traci_and_safety_pipeline(
    tmp_path: Path,
) -> None:
    sumo_home = os.environ.get("SUMO_HOME")
    if not sumo_home:
        pytest.skip("SUMO_HOME is not configured")
    config = replace(
        smoke_config(
            "coordinated-max-pressure",
            duration_s=16.0,
            seed=89,
            result_root=tmp_path,
        ),
        disturbance_time_scale=0.01,
    )

    result = await ExperimentRunner(
        config,
        sumo_home=Path(sumo_home),
    ).run()

    event_names = {str(item["event"]) for item in result["events"]}
    assert {
        "ROADWORK_LANE_CLOSED",
        "ROADWORK_LANE_REOPENED",
        "EVENT_DISPERSAL_VEHICLE_INJECTED",
        "INCIDENT_STOP_SCHEDULED",
        "EMERGENCY_VEHICLE_INJECTED",
        "EMERGENCY_PRIORITY_DETECTED",
    } <= event_names
    assert event_names & {"INCIDENT_CLEARED", "INCIDENT_STOP_CANCELLED"}
    if "INCIDENT_VEHICLE_STOPPED" in event_names:
        assert "INCIDENT_CLEARED" in event_names
    metrics = result["metrics"]
    assert isinstance(metrics, dict)
    assert metrics["emergency_priority_detection_count"] >= 1
    manifest = result["manifest"]
    assert isinstance(manifest, dict)
    paths = {entry["path"] for entry in manifest["files"]}
    assert "scenarios/configs/xiongan_rongdong_20.yaml" in paths
