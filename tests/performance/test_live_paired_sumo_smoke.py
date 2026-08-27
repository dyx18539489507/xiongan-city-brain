"""Actual two-process SUMO/TraCI lockstep comparison smoke evidence."""

import asyncio
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
    control = PairedExperimentControl()
    control.set_simulation_rate(8.0)

    result = await LivePairedExperimentRunner(
        baseline_config=baseline,
        candidate_config=candidate,
        sumo_home=Path(sumo_home),
        baseline_bus=InMemoryMessageBus(),
        candidate_bus=InMemoryMessageBus(),
        control=control,
        hub=hub,
    ).run()

    assert result["status"] == "completed"
    assert result["baseline"]["actual_run"] is True
    assert result["candidate"]["actual_run"] is True
    for role in ("baseline", "candidate"):
        performance = result[role]["metrics"]["runner_performance"]
        assert performance["sample_count"] == 3
        assert performance["step_p95_ms"] > 0
        assert performance["achievable_rate_p95"] > 0
        assert set(performance["phase_p95_ms"]) == {
            "sumo_step",
            "disturbance",
            "aggregation",
            "control",
            "telemetry",
            "barrier",
        }
    comparison = result["comparison"]
    assert comparison["valid"] is True
    # At x8 the renderer stream is capped at four wall-clock updates per
    # second, while all three SUMO/control steps above still execute.
    assert comparison["paired_sample_count"] == 2
    assert comparison["simulation_time_s"] == 3.0
    assert all(
        message["baseline"]["message"]["simulationTimeS"]
        == message["candidate"]["message"]["simulationTimeS"]
        for message in hub.frames
        if message["status"] == "running"
    )


@pytest.mark.performance
async def test_real_paired_incident_uses_one_target_without_invalidating_pair(
    tmp_path: Path,
) -> None:
    sumo_home = os.environ.get("SUMO_HOME")
    if not sumo_home:
        pytest.skip("SUMO_HOME is not configured")

    baseline = smoke_config("fixed-time", duration_s=60.0, seed=42, result_root=tmp_path)
    candidate = smoke_config(
        "coordinated-max-pressure",
        duration_s=60.0,
        seed=42,
        result_root=tmp_path,
    )
    hub = PairedDigitalTwinHub(Path.cwd(), window_s=20.0)
    hub.configure(
        pair_id="pair-real-incident",
        scenario_id="xiongan_rongdong_20",
        baseline_algorithm=baseline.algorithm,
        candidate_algorithm=candidate.algorithm,
        baseline_experiment_id=baseline.experiment_id,
        candidate_experiment_id=candidate.experiment_id,
        fairness_manifest={"seed": 42, "duration_s": 60.0},
        fairness_fingerprint="real-incident",
    )
    control = PairedExperimentControl()
    control.set_simulation_rate(8.0)
    run_task = asyncio.create_task(
        LivePairedExperimentRunner(
            baseline_config=baseline,
            candidate_config=candidate,
            sumo_home=Path(sumo_home),
            baseline_bus=InMemoryMessageBus(),
            candidate_bus=InMemoryMessageBus(),
            control=control,
            hub=hub,
        ).run()
    )

    try:
        async with asyncio.timeout(60.0):
            while True:
                if run_task.done():
                    pytest.fail(f"paired run ended before incident injection: {run_task.result()}")
                try:
                    incident_target = hub.select_shared_incident_vehicle(
                        "downstream_bottleneck",
                        42,
                    )
                except ValueError:
                    await asyncio.sleep(0.05)
                    continue
                control.pause()
                break

        manifest = control.inject_fault(
            "incident",
            {
                "duration_s": 30.0,
                "target": "downstream_bottleneck",
                "vehicle_id": incident_target["vehicle_id"],
                "edge_id": incident_target["edge_id"],
            },
            event_id="fault-real-incident",
            target="downstream_bottleneck",
            seed=42,
        )
        control.resume()

        async with asyncio.timeout(15.0):
            while manifest["status"] not in {"applied", "failed"}:
                if run_task.done():
                    await run_task
                    pytest.fail("paired run ended before the incident reached both runners")
                await asyncio.sleep(0.02)

        control.pause()
        assert manifest["status"] == "applied"
        assert manifest["parameters"]["vehicle_id"] == incident_target["vehicle_id"]
        assert manifest["parameters"]["edge_id"] == incident_target["edge_id"]
        runner_status = manifest["runner_status"]
        assert runner_status["baseline"]["simulation_time_s"] == runner_status["candidate"][
            "simulation_time_s"
        ]
        assert runner_status["baseline"]["detail"] == incident_target["vehicle_id"]
        assert runner_status["candidate"]["detail"] == incident_target["vehicle_id"]
        assert control.fault_failure_reason is None
        assert hub.accumulator.summary()["valid"] is True

        control.clear_faults()
        assert manifest["status"] == "cleared"
        assert {item["status"] for item in runner_status.values()} == {"cleared"}
    finally:
        control.resume()
        control.stop()
        await run_task
