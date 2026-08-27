import asyncio

import pytest

from traffic_platform.comparison_service import PairedStepBarrier, PairSynchronizationError


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
