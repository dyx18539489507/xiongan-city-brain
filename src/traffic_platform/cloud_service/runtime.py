"""Cloud MQTT/message-bus runtime using only public contracts."""

from traffic_platform.cloud_service.coordinator import RegionalCoordinator
from traffic_platform.contracts.idempotency import IdempotencyGuard
from traffic_platform.contracts.models import RegionalState
from traffic_platform.messaging.base import MessageBus


class CloudRuntime:
    """Receive regional states and publish versioned strategies."""

    def __init__(
        self,
        bus: MessageBus,
        coordinator: RegionalCoordinator,
        *,
        environment: str,
    ) -> None:
        self.bus = bus
        self.coordinator = coordinator
        self.environment = environment
        self.guard = IdempotencyGuard()
        self.received_states = 0
        self.published_strategies = 0

    async def start(self) -> None:
        """Subscribe to all edge regional-state topics."""

        await self.bus.subscribe(
            f"traffic/{self.environment}/edge/+/state",
            self._handle_state,
            qos=1,
        )

    async def _handle_state(self, _topic: str, payload: bytes) -> None:
        state = RegionalState.model_validate_json(payload)
        self.guard.accept(state)
        self.received_states += 1
        for strategy in self.coordinator.strategies(state):
            await self.bus.publish(
                (
                    f"traffic/{self.environment}/cloud/strategy/"
                    f"{strategy.target_intersection_id}"
                ),
                strategy.model_dump_json().encode("utf-8"),
                qos=1,
            )
            self.published_strategies += 1

