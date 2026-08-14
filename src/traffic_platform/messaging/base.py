"""Transport-neutral pub/sub protocol shared by services."""

from collections.abc import Awaitable, Callable
from typing import Protocol

MessageHandler = Callable[[str, bytes], Awaitable[None]]


class MessageBus(Protocol):
    """Minimal asynchronous message bus implemented by MQTT and tests."""

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def subscribe(
        self,
        topic: str,
        handler: MessageHandler,
        *,
        qos: int = 1,
    ) -> None: ...

    async def publish(
        self,
        topic: str,
        payload: bytes,
        *,
        qos: int = 1,
        retain: bool = False,
    ) -> None: ...

