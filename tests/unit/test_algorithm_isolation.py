"""Enforceable algorithm timeout and restart behavior."""

import pytest
from tests.factories import edge_factory, intersection, topology

from traffic_platform.algorithm_sdk.isolation import IsolatedAlgorithmRunner
from traffic_platform.algorithm_sdk.types import AlgorithmConfig, ControlObservation
from traffic_platform.common.errors import ErrorCode, PlatformError


def test_isolated_algorithm_returns_a_real_decision() -> None:
    runner = IsolatedAlgorithmRunner(
        "max-pressure",
        AlgorithmConfig(decision_timeout_ms=500.0),
        topology(),
    )
    try:
        decision = runner.decide(
            ControlObservation(intersection=intersection(edge_factory()))
        )
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
            runner.decide(
                ControlObservation(intersection=intersection(edge_factory()))
            )
        assert raised.value.code == ErrorCode.ALGORITHM_TIMEOUT
        health = runner.health()
        assert health.failures == 1
        assert health.status == "degraded"
        assert "alive" in health.detail
    finally:
        runner.close()
