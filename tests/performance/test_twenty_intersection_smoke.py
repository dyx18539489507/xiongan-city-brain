"""Actual 20-intersection performance evidence smoke test."""

import os
from pathlib import Path

import pytest

from traffic_platform.experiment_service.engine import ExperimentRunner, smoke_config


@pytest.mark.performance
@pytest.mark.parametrize(
    "algorithm",
    ["actuated-control", "coordinated-max-pressure"],
)
async def test_twenty_intersection_runner_records_engineering_metrics(
    tmp_path: Path,
    algorithm: str,
) -> None:
    sumo_home = os.environ.get("SUMO_HOME")
    if not sumo_home:
        pytest.skip("SUMO_HOME is not configured")
    config = smoke_config(
        algorithm,
        duration_s=5.0,
        seed=11,
        result_root=tmp_path,
    )
    result = await ExperimentRunner(config, sumo_home=Path(sumo_home)).run()
    metrics = result["metrics"]
    assert isinstance(metrics, dict)
    assert metrics["simulation_realtime_factor"] > 0
    assert metrics["memory_mb_peak"] > 0
    assert metrics["cloud_decision_latency_ms"] >= 0
    assert metrics["edge_decision_latency_ms"] >= 0
    assert len(result["samples"]) == 5
