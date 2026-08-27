"""Actual two-process SUMO/TraCI lockstep comparison smoke evidence."""

import os
from pathlib import Path

import pytest

from traffic_platform.comparison_service import (
    LivePairedExperimentRunner,
    PairedDigitalTwinHub,
    PairedExperimentControl,
)
from traffic_platform.experiment_service.engine import smoke_config
from traffic_platform.messaging.in_memory import InMemoryMessageBus


@pytest.mark.performance
async def test_two_real_sumo_runners_publish_synchronized_atomic_frames(
    tmp_path: Path,
) -> None:
    sumo_home = os.environ.get("SUMO_HOME")
    if not sumo_home:
        pytest.skip("SUMO_HOME is not configured")

    baseline = smoke_config("fixed-time", duration_s=3.0, seed=42, result_root=tmp_path)
    candidate = smoke_config(
        "coordinated-max-pressure",
        duration_s=3.0,
        seed=42,
        result_root=tmp_path,
    )
    hub = PairedDigitalTwinHub(Path.cwd(), window_s=2.0)
    hub.configure(
        pair_id="pair-real-smoke",
        scenario_id="xiongan_rongdong_20",
        baseline_algorithm=baseline.algorithm,
        candidate_algorithm=candidate.algorithm,
        baseline_experiment_id=baseline.experiment_id,
        candidate_experiment_id=candidate.experiment_id,
        fairness_manifest={"seed": 42, "duration_s": 3.0},
        fairness_fingerprint="real-smoke",
    )

    result = await LivePairedExperimentRunner(
        baseline_config=baseline,
        candidate_config=candidate,
        sumo_home=Path(sumo_home),
        baseline_bus=InMemoryMessageBus(),
        candidate_bus=InMemoryMessageBus(),
        control=PairedExperimentControl(),
        hub=hub,
    ).run()

    assert result["status"] == "completed"
    assert result["baseline"]["actual_run"] is True
    assert result["candidate"]["actual_run"] is True
    comparison = result["comparison"]
    assert comparison["valid"] is True
    assert comparison["paired_sample_count"] == 3
    assert comparison["simulation_time_s"] == 3.0
    assert all(
        message["baseline"]["message"]["simulationTimeS"]
        == message["candidate"]["message"]["simulationTimeS"]
        for message in hub.frames
        if message["status"] == "running"
    )
