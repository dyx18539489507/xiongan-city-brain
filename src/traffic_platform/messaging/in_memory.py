"""Deterministic asynchronous transport for integration and E2E tests."""

import asyncio
from dataclasses import dataclass

from traffic_platform.messaging.base import MessageHandler


@dataclass(frozen=True, slots=True)
class PublishedMessage:
    """Recorded in-memory delivery."""

    topic: str
    payload: bytes
    qos: int
    retain: bool


class InMemoryMessageBus:
    """MQTT-topic-compatible bus without an external process."""

    def __init__(self) -> None:
        self._connected = False
        self._subscriptions: list[tuple[str, MessageHandler]] = []
        self.messages: list[PublishedMessage] = []

    async def connect(self) -> None:
        """Enable publish and subscribe operations."""

        self._connected = True

    async def disconnect(self) -> None:
        """Stop delivery while retaining evidence for assertions."""

        self._connected = False

    async def subscribe(
        self,
        topic: str,
        handler: MessageHandler,
        *,
        qos: int = 1,
    ) -> None:
        """Register an MQTT wildcard-compatible asynchronous handler."""

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
        """Record and deliver a message to every matching subscriber."""

        self._require_connected()
        self.messages.append(PublishedMessage(topic, payload, qos, retain))
        handlers = [
            handler
            for pattern, handler in self._subscriptions
            if topic_matches(pattern, topic)
        ]
        if handlers:
            await asyncio.gather(*(handler(topic, payload) for handler in handlers))

    def _require_connected(self) -> None:
        if not self._connected:
            raise RuntimeError("message bus is not connected")


def topic_matches(pattern: str, topic: str) -> bool:
    """Match MQTT `+` and terminal `#` wildcard semantics."""

    pattern_parts = pattern.split("/")
    topic_parts = topic.split("/")
    for index, part in enumerate(pattern_parts):
        if part == "#":
            return index == len(pattern_parts) - 1
        if index >= len(topic_parts):
            return False
        if part != "+" and part != topic_parts[index]:
            return False
    return len(pattern_parts) == len(topic_parts)

