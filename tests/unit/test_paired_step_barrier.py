import asyncio

import pytest

from traffic_platform.comparison_service import (
    PairedExperimentControl,
    PairedStepBarrier,
    PairSynchronizationError,
)


async def test_step_barrier_releases_only_matching_simulation_times() -> None:
    barrier = PairedStepBarrier(timeout_s=1)
    baseline = asyncio.create_task(barrier.wait("baseline", 1.0))
    await asyncio.sleep(0)
    assert not baseline.done()

    await barrier.wait("candidate", 1.0)
    await baseline


async def test_step_barrier_aborts_both_sides_on_time_mismatch() -> None:
    barrier = PairedStepBarrier(timeout_s=1)
    baseline = asyncio.create_task(barrier.wait("baseline", 1.0))
    await asyncio.sleep(0)

    with pytest.raises(PairSynchronizationError, match="simulation time mismatch"):
        await barrier.wait("candidate", 2.0)
    with pytest.raises(PairSynchronizationError, match="simulation time mismatch"):
        await baseline


async def test_step_barrier_rejects_peer_finishing_while_other_waits() -> None:
    barrier = PairedStepBarrier(timeout_s=1)
    baseline = asyncio.create_task(barrier.wait("baseline", 1.0))
    await asyncio.sleep(0)

    await barrier.finish("candidate")

    with pytest.raises(PairSynchronizationError, match="finished"):
        await baseline


def test_pair_rejects_a_physical_event_that_never_reaches_both_sumo_instances() -> None:
    control = PairedExperimentControl()
    manifest = control.inject_fault(
        "incident",
        {"duration_s": 1.0, "target": "downstream_bottleneck"},
        event_id="fault-never-applied",
        target="downstream_bottleneck",
        seed=42,
    )

    for child in (control.baseline, control.candidate):
        child.advance_simulation_time(1.0)
        child.advance_simulation_time(2.0)

    assert manifest["status"] == "failed"
    assert control.fault_failure_reason is not None
    assert "fault-never-applied" in control.fault_failure_reason


def test_pair_rejects_different_incident_targets() -> None:
    control = PairedExperimentControl()
    manifest = control.inject_fault(
        "incident",
        {"duration_s": 30.0, "target": "downstream_bottleneck"},
        event_id="fault-target-mismatch",
        target="downstream_bottleneck",
        seed=42,
    )
    control.baseline.advance_simulation_time(1.0)
    control.candidate.advance_simulation_time(1.0)

    control.baseline.mark_disturbance_applied("fault-target-mismatch", 1.0, "vehicle-a")
    control.candidate.mark_disturbance_applied("fault-target-mismatch", 1.0, "vehicle-b")

    assert manifest["status"] == "failed"
    assert control.fault_failure_reason is not None
    assert "mismatched physical targets" in control.fault_failure_reason


def test_pair_uses_one_visual_frame_schedule_across_a_rate_change() -> None:
    control = PairedExperimentControl()

    assert control.digital_twin_interval_for(1.0, 1.0) == 1.0
    control.set_simulation_rate(8.0)
    # The second runner must reuse the first runner's decision even when the
    # target rate changes between their callbacks for the same SUMO timestamp.
    assert control.digital_twin_interval_for(1.0, 1.0) == 1.0

    assert control.digital_twin_interval_for(2.0, 1.0) == 2.0
    assert control.digital_twin_interval_for(2.0, 1.0) == 2.0
    assert control.digital_twin_interval_for(3.0, 1.0) is None
    assert control.digital_twin_interval_for(3.0, 1.0) is None
    assert control.digital_twin_interval_for(4.0, 1.0) == 2.0
    assert control.digital_twin_interval_for(4.0, 1.0) == 2.0
