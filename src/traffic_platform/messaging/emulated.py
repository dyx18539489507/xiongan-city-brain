"""Simulation-time message bus with auditable latency, loss and reordering."""

import asyncio
import json
from dataclasses import dataclass

from traffic_platform.communication_emulator.channel import (
    ChannelConfig,
    DeliveryRecord,
    SimulatedChannel,
)
from traffic_platform.messaging.base import MessageHandler
from traffic_platform.messaging.in_memory import topic_matches


@dataclass(frozen=True, slots=True)
class PendingMessage:
    """One bus publication waiting in the simulated communication channel."""

    topic: str
    payload: bytes
    qos: int
    retain: bool


class EmulatedMessageBus:
    """MQTT-compatible bus whose impairments advance only with simulation time."""

    def __init__(self, config: ChannelConfig | None = None, *, seed: int = 0) -> None:
        self._connected = False
        self._subscriptions: list[tuple[str, MessageHandler]] = []
        self._seed = seed
        self._config = config or ChannelConfig()
        self._channel: SimulatedChannel[PendingMessage] = SimulatedChannel(
            self._config,
            seed=seed,
            corruptor=self._corrupt_pending,
        )
        self._current_time_s = 0.0
        self._broker_offline_until_s = -1.0
        self._endpoint_offline_until_s: dict[str, float] = {}
        self.delivery_count = 0

    @property
    def records(self) -> list[DeliveryRecord]:
        """Expose immutable delivery evidence recorded by the channel."""

        return self._channel.records

    @property
    def config(self) -> ChannelConfig:
        """Return the active channel configuration."""

        return self._config

    async def connect(self) -> None:
        """Enable subscriptions and publications."""

        self._connected = True

    async def disconnect(self) -> None:
        """Stop delivery while retaining communication evidence."""

        self._connected = False

    async def subscribe(
        self,
        topic: str,
        handler: MessageHandler,
        *,
        qos: int = 1,
    ) -> None:
        """Register one MQTT-wildcard-compatible subscriber."""

        self._require_connected()
        if qos not in {0, 1, 2}:
            raise ValueError("qos must be 0, 1 or 2")
        self._subscriptions.append((topic, handler))

    async def publish(
        self,
        topic: str,
        payload: bytes,
        *,
        qos: int = 1,
        retain: bool = False,
    ) -> None:
        """Schedule one publication without sleeping wall-clock time."""

        self._require_connected()
        if qos not in {0, 1, 2}:
            raise ValueError("qos must be 0, 1 or 2")
        message_id, simulation_time = self._metadata(payload)
        self._current_time_s = max(self._current_time_s, simulation_time)
        source, destination, message_type = self._route_metadata(topic)
        offline_until = max(
            self._broker_offline_until_s,
            self._endpoint_offline_until_s.get(source, -1.0),
            self._endpoint_offline_until_s.get(destination, -1.0),
        )
        self._channel.send(
            message_id,
            PendingMessage(topic, payload, qos, retain),
            current_time_s=simulation_time,
            size_bytes=len(payload),
            force_offline=simulation_time < offline_until,
            recovery_time_s=(
                max(0.0, offline_until - simulation_time)
                if simulation_time < offline_until
                else None
            ),
            channel=topic,
            source=source,
            destination=destination,
            message_type=message_type,
        )
        await self.advance(simulation_time)

    async def advance(self, simulation_time_s: float) -> int:
        """Deliver all messages now due and return the delivery count."""

        self._require_connected()
        self._current_time_s = max(self._current_time_s, simulation_time_s)
        delivered = self._channel.advance(self._current_time_s)
        for _, pending in delivered:
            handlers = [
                handler
                for pattern, handler in self._subscriptions
                if topic_matches(pattern, pending.topic)
            ]
            if handlers:
                await asyncio.gather(
                    *(handler(pending.topic, pending.payload) for handler in handlers)
                )
            self.delivery_count += 1
        return len(delivered)

    def configure(self, config: ChannelConfig) -> None:
        """Apply a new fault profile while preserving prior evidence."""

        if config == self._config:
            return
        previous_records = list(self._channel.records)
        self._config = config
        self._channel = SimulatedChannel(
            config,
            seed=self._seed + len(previous_records),
            corruptor=self._corrupt_pending,
        )
        self._channel.records.extend(previous_records)

    def set_broker_offline(
        self,
        current_time_s: float,
        duration_s: float,
    ) -> None:
        """Interrupt and automatically recover the emulated MQTT broker."""

        if duration_s <= 0:
            raise ValueError("duration_s must be positive")
        self._broker_offline_until_s = max(
            self._broker_offline_until_s,
            current_time_s + duration_s,
        )

    def set_endpoint_offline(
        self,
        endpoint: str,
        current_time_s: float,
        duration_s: float,
    ) -> None:
        """Take cloud, edge, vehicle or SUMO endpoint offline in simulated time."""

        if endpoint not in {"cloud", "edge", "vehicle", "sumo", "experiment"}:
            raise ValueError(f"unsupported endpoint: {endpoint}")
        if duration_s <= 0:
            raise ValueError("duration_s must be positive")
        self._endpoint_offline_until_s[endpoint] = max(
            self._endpoint_offline_until_s.get(endpoint, -1.0),
            current_time_s + duration_s,
        )

    def recover_broker(self, current_time_s: float) -> None:
        """Recover the broker immediately at a simulation timestamp."""

        self._broker_offline_until_s = current_time_s

    def recover_endpoint(self, endpoint: str, current_time_s: float) -> None:
        """Recover one endpoint immediately at a simulation timestamp."""

        self._endpoint_offline_until_s[endpoint] = current_time_s

    @staticmethod
    def _metadata(payload: bytes) -> tuple[str, float]:
        try:
            document = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return f"opaque-{hash(payload)}", 0.0
        return (
            str(document.get("message_id", f"opaque-{hash(payload)}")),
            float(document.get("simulation_time", 0.0)),
        )

    @staticmethod
    def _corrupt_pending(message: PendingMessage) -> PendingMessage:
        payload = bytearray(message.payload)
        if payload:
            payload[len(payload) // 2] ^= 0x01
        else:
            payload.append(0)
        return PendingMessage(
            message.topic,
            bytes(payload),
            message.qos,
            message.retain,
        )

    @staticmethod
    def _route_metadata(topic: str) -> tuple[str, str, str]:
        parts = topic.split("/")
        message_type = parts[-1] if parts else "unknown"
        if "/cloud/" in topic:
            return "cloud", "edge", message_type
        if "/edge/" in topic:
            return "edge", "cloud", message_type
        if "/vehicle/" in topic:
            if message_type == "telemetry":
                return "sumo", "vehicle", message_type
            if message_type == "command":
                return "vehicle", "sumo", message_type
            if message_type == "guidance":
                return "edge", "vehicle", message_type
            return "vehicle", "edge", message_type
        if "/experiment/" in topic:
            return "experiment", "report", message_type
        return "unknown", "unknown", message_type

    def _require_connected(self) -> None:
        if not self._connected:
            raise RuntimeError("message bus is not connected")
