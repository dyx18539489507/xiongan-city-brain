"""Shared strict contract factories for tests."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from traffic_platform.contracts.models import SourceType


@pytest.fixture
def envelope() -> Callable[..., dict[str, Any]]:
    """Return a current, strict common-message envelope factory."""

    def factory(**overrides: Any) -> dict[str, Any]:
        now = datetime.now(UTC)
        values: dict[str, Any] = {
            "trace_id": "trace-test",
            "source_id": "edge-test",
            "source_type": SourceType.EDGE,
            "timestamp_utc": now,
            "simulation_time": 10.0,
            "sequence_number": 1,
            "created_at": now,
            "expires_at": now + timedelta(seconds=60),
            "correlation_id": "corr-test",
            "environment": "test",
            "scenario_id": "scenario-test",
            "experiment_id": "experiment-test",
        }
        values.update(overrides)
        return values

    return factory

