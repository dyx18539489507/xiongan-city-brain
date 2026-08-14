"""Cloud timeout, autonomy, fixed-time fallback and smooth recovery."""

import pytest
from tests.factories import cloud_strategy, edge_factory

from traffic_platform.common.errors import PlatformError
from traffic_platform.edge_service.state_machine import (
    DegradationConfig,
    EdgeDegradationMachine,
    EdgeMode,
)


def test_timeout_and_recovery_sequence() -> None:
    machine = EdgeDegradationMachine(
        DegradationConfig(
            hold_timeout_s=10.0,
            autonomous_timeout_s=20.0,
            recovery_stable_s=5.0,
        )
    )
    factory = edge_factory()
    assert machine.accept_strategy(
        cloud_strategy(factory, version=1),
        simulation_time=0.0,
        experiment_id="experiment-test",
    )
    assert machine.mode == EdgeMode.RECOVERY_SYNC
    assert machine.tick(5.0) == EdgeMode.CLOUD_COORDINATED
    assert machine.tick(11.0) == EdgeMode.HOLD_LAST_VALID
    assert machine.tick(21.0) == EdgeMode.EDGE_AUTONOMOUS
    assert machine.accept_strategy(
        cloud_strategy(factory, version=2),
        simulation_time=22.0,
        experiment_id="experiment-test",
    )
    assert machine.mode == EdgeMode.RECOVERY_SYNC
    assert machine.tick(27.0) == EdgeMode.CLOUD_COORDINATED


def test_duplicate_strategy_and_algorithm_failure_fallback() -> None:
    machine = EdgeDegradationMachine()
    factory = edge_factory()
    strategy = cloud_strategy(factory)
    assert machine.accept_strategy(
        strategy,
        simulation_time=10.0,
        experiment_id="experiment-test",
    )
    assert not machine.accept_strategy(
        strategy,
        simulation_time=11.0,
        experiment_id="experiment-test",
    )
    assert machine.tick(12.0, local_healthy=False) == EdgeMode.FIXED_TIME_SAFE


def test_simulation_time_rollback_is_detected() -> None:
    machine = EdgeDegradationMachine()
    machine.tick(10.0)
    with pytest.raises(PlatformError):
        machine.tick(9.0)
    assert machine.mode == EdgeMode.FIXED_TIME_SAFE


def test_edge_restart_restores_versions_through_recovery_sync() -> None:
    original = EdgeDegradationMachine()
    factory = edge_factory()
    assert original.accept_strategy(
        cloud_strategy(factory, version=4),
        simulation_time=10.0,
        experiment_id="experiment-test",
    )
    original.tick(15.0)
    snapshot = original.snapshot(experiment_id="experiment-test")

    restored = EdgeDegradationMachine()
    assert (
        restored.restore(
            snapshot,
            experiment_id="experiment-test",
            simulation_time=16.0,
            cloud_available=True,
        )
        == EdgeMode.RECOVERY_SYNC
    )
    assert restored.last_strategy_versions["J1"] == 4
    assert restored.transitions[-1].reason == "EDGE_RESTART_RESTORED"


def test_edge_restart_rejects_snapshot_from_future_simulation_time() -> None:
    machine = EdgeDegradationMachine()
    machine.tick(20.0)
    snapshot = machine.snapshot(experiment_id="experiment-test")
    restored = EdgeDegradationMachine()
    with pytest.raises(PlatformError):
        restored.restore(
            snapshot,
            experiment_id="experiment-test",
            simulation_time=10.0,
            cloud_available=False,
        )
    assert restored.mode == EdgeMode.FIXED_TIME_SAFE
