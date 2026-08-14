"""Message-envelope factory that keeps trace and experiment context consistent."""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, TypeVar
from uuid import uuid4

from traffic_platform.common.time import utc_now
from traffic_platform.contracts.models import SourceType, TrafficMessage

MessageT = TypeVar("MessageT", bound=TrafficMessage)


@dataclass(slots=True)
class MessageFactory:
    """Create versioned messages with monotonic per-source sequence numbers."""

    source_id: str
    source_type: SourceType
    scenario_id: str
    experiment_id: str
    environment: str = "development"
    sequence_number: int = 0

    def build(
        self,
        model: type[MessageT],
        *,
        simulation_time: float,
        ttl_s: float = 30.0,
        trace_id: str | None = None,
        correlation_id: str | None = None,
        **payload: Any,
    ) -> MessageT:
        """Build a validated message and increment the source sequence."""

        if ttl_s <= 0:
            raise ValueError("ttl_s must be positive")
        now = utc_now()
        self.sequence_number += 1
        trace = trace_id or uuid4().hex
        return model(
            trace_id=trace,
            source_id=self.source_id,
            source_type=self.source_type,
            timestamp_utc=now,
            simulation_time=float(simulation_time),
            sequence_number=self.sequence_number,
            created_at=now,
            expires_at=now + timedelta(seconds=ttl_s),
            correlation_id=correlation_id or trace,
            environment=self.environment,
            scenario_id=self.scenario_id,
            experiment_id=self.experiment_id,
            **payload,
        )

