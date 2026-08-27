"""Enforceable algorithm timeout and restart behavior."""

import gc

import pytest
from tests.factories import edge_factory, intersection, topology

from traffic_platform.algorithm_sdk.isolation import IsolatedAlgorithmRunner
from traffic_platform.algorithm_sdk.types import AlgorithmConfig, ControlObservation
from traffic_platform.algorithms import builtin_registry
from traffic_platform.common.errors import ErrorCode, PlatformError


def test_isolated_algorithm_returns_a_real_decision() -> None:
    runner = IsolatedAlgorithmRunner(
        "max-pressure",
        AlgorithmConfig(decision_timeout_ms=500.0),
        topology(),
    )
    try:
        decision = runner.decide(ControlObservation(intersection=intersection(edge_factory())))
        assert decision.intersection_id == "J1"
        assert runner.health().decisions == 1
    finally:
        runner.close()


def test_isolated_algorithm_timeout_terminates_and_restarts_worker() -> None:
    runner = IsolatedAlgorithmRunner(
        "max-pressure",
        AlgorithmConfig(decision_timeout_ms=0.001),
        topology(),
    )
    try:
        with pytest.raises(PlatformError) as raised:
            runner.decide(ControlObservation(intersection=intersection(edge_factory())))
        assert raised.value.code == ErrorCode.ALGORITHM_TIMEOUT
        health = runner.health()
        assert health.failures == 1
        assert health.status == "degraded"
        assert "alive" in health.detail
    finally:
        runner.close()


def test_in_process_deadline_restores_gc_after_success_and_failure() -> None:
    registry = builtin_registry()
    algorithm = registry.create("max-pressure")
    algorithm.initialize(AlgorithmConfig(), topology())
    observation = ControlObservation(intersection=intersection(edge_factory()))

    gc.enable()
    registry.decide_with_timeout(algorithm, observation, timeout_ms=500.0)
    assert gc.isenabled()

    def fail(_observation: ControlObservation) -> None:
        raise RuntimeError("boom")

    algorithm.decide = fail  # type: ignore[method-assign]
    with pytest.raises(PlatformError) as raised:
        registry.decide_with_timeout(algorithm, observation, timeout_ms=500.0)
    assert raised.value.code == ErrorCode.ALGORITHM_FAILURE
    assert gc.isenabled()
