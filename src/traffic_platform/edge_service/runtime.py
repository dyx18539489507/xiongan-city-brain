"""Edge message runtime for state, strategies and execution feedback."""

import time

from traffic_platform.contracts.idempotency import IdempotencyGuard
from traffic_platform.contracts.models import CloudStrategy, ExecutionFeedback, RegionalState
from traffic_platform.edge_service.controller import EdgeController
from traffic_platform.messaging.base import MessageBus


class EdgeRuntime:
    """Publish aggregated state and consume cloud strategies over public topics."""

    def __init__(
        self,
        bus: MessageBus,
        controller: EdgeController,
        *,
        environment: str,
        edge_id: str,
    ) -> None:
        self.bus = bus
        self.controller = controller
        self.environment = environment
        self.edge_id = edge_id
        self.guard = IdempotencyGuard()
        self.received_strategies = 0
        self.feedback_count = 0
        self.round_trip_latencies_ms: list[float] = []
        self._published_state_wall_times: dict[str, float] = {}

    async def start(self) -> None:
        """Subscribe to per-intersection cloud targets."""

        await self.bus.subscribe(
            f"traffic/{self.environment}/cloud/strategy/+",
            self._handle_strategy,
            qos=1,
        )

    async def publish_state(self, state: RegionalState) -> None:
        """Publish one strict regional aggregation."""

        self._published_state_wall_times[str(state.message_id)] = time.perf_counter()
        await self.bus.publish(
            f"traffic/{self.environment}/edge/{self.edge_id}/state",
            state.model_dump_json().encode("utf-8"),
            qos=1,
        )

    async def publish_feedback(self, feedback: ExecutionFeedback) -> None:
        """Publish safety and execution evidence."""

        await self.bus.publish(
            f"traffic/{self.environment}/edge/{self.edge_id}/feedback",
            feedback.model_dump_json().encode("utf-8"),
            qos=1,
        )
        self.feedback_count += 1

    async def _handle_strategy(self, _topic: str, payload: bytes) -> None:
        strategy = CloudStrategy.model_validate_json(payload)
        validation_time = getattr(self.bus, "validation_time", None)
        self.guard.accept(
            strategy,
            checked_at=validation_time(strategy) if callable(validation_time) else None,
        )
        started = self._published_state_wall_times.get(strategy.correlation_id)
        if started is not None:
            self.round_trip_latencies_ms.append(
                (time.perf_counter() - started) * 1000.0
            )
        if self.controller.accept_cloud_strategy(strategy):
            self.received_strategies += 1
