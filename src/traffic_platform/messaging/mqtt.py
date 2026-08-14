"""Real Eclipse Mosquitto-compatible MQTT transport using paho-mqtt."""

import asyncio
import ssl
from collections import defaultdict
from typing import Any
from uuid import uuid4

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from paho.mqtt.properties import Properties
from paho.mqtt.reasoncodes import ReasonCode

from traffic_platform.common.errors import PlatformError
from traffic_platform.messaging.base import MessageHandler
from traffic_platform.observability.logging import get_logger

logger = get_logger(__name__)


class MqttMessageBus:
    """Bridge paho's network thread into an asyncio service lifecycle."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        client_id: str | None = None,
        username: str | None = None,
        password: str | None = None,
        tls_enabled: bool = False,
        ca_cert: str | None = None,
        client_cert: str | None = None,
        client_key: str | None = None,
        tls_insecure: bool = False,
        keepalive_s: int = 30,
        connect_timeout_s: float = 10.0,
    ) -> None:
        self.host = host
        self.port = port
        self.keepalive_s = keepalive_s
        self.connect_timeout_s = connect_timeout_s
        self._client = mqtt.Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id=client_id or f"traffic-{uuid4().hex[:12]}",
            protocol=mqtt.MQTTv5,
        )
        if username:
            self._client.username_pw_set(username, password)
        if bool(client_cert) != bool(client_key):
            raise ValueError(
                "MQTT client certificate and key must be configured together"
            )
        if tls_enabled:
            self._client.tls_set(
                ca_certs=ca_cert,
                certfile=client_cert,
                keyfile=client_key,
                tls_version=ssl.PROTOCOL_TLS_CLIENT,
            )
            self._client.tls_insecure_set(tls_insecure)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._handlers: dict[str, list[MessageHandler]] = defaultdict(list)
        self._subscriptions: dict[str, int] = {}
        self._handler_locks: dict[MessageHandler, asyncio.Lock] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._connected_event: asyncio.Event | None = None
        self._disconnected_event: asyncio.Event | None = None
        self._connected = False

    @property
    def connected(self) -> bool:
        """Return the live paho connection state."""

        return self._connected

    async def connect(self) -> None:
        """Connect with a bounded timeout and start paho's network loop."""

        if self._connected:
            return
        self._loop = asyncio.get_running_loop()
        self._connected_event = asyncio.Event()
        self._disconnected_event = asyncio.Event()
        self._client.connect_async(self.host, self.port, self.keepalive_s)
        self._client.loop_start()
        try:
            await asyncio.wait_for(
                self._connected_event.wait(),
                timeout=self.connect_timeout_s,
            )
        except TimeoutError:
            self._client.loop_stop()
            raise TimeoutError(
                f"MQTT connection to {self.host}:{self.port} timed out"
            ) from None

    async def disconnect(self) -> None:
        """Disconnect cleanly and stop the paho network thread."""

        if not self._connected:
            self._client.loop_stop()
            return
        assert self._disconnected_event is not None
        self._client.disconnect()
        try:
            await asyncio.wait_for(self._disconnected_event.wait(), timeout=5.0)
        finally:
            self._client.loop_stop()
            self._connected = False

    async def subscribe(
        self,
        topic: str,
        handler: MessageHandler,
        *,
        qos: int = 1,
    ) -> None:
        """Subscribe a handler and verify paho accepted the request."""

        await self._wait_until_connected()
        result, _ = self._client.subscribe(topic, qos=qos)
        if result != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"MQTT subscribe failed with code {result}")
        self._handlers[topic].append(handler)
        self._subscriptions[topic] = qos
        self._handler_locks.setdefault(handler, asyncio.Lock())

    async def publish(
        self,
        topic: str,
        payload: bytes,
        *,
        qos: int = 1,
        retain: bool = False,
    ) -> None:
        """Publish bytes and await broker acknowledgement for QoS 1/2."""

        for attempt in range(3):
            await self._wait_until_connected()
            info = self._client.publish(
                topic,
                payload=payload,
                qos=qos,
                retain=retain,
            )
            if info.rc == mqtt.MQTT_ERR_NO_CONN:
                self._mark_disconnected()
                if attempt < 2:
                    continue
            elif info.rc != mqtt.MQTT_ERR_SUCCESS:
                raise RuntimeError(f"MQTT publish failed with code {info.rc}")
            else:
                if qos == 0:
                    return
                try:
                    await asyncio.to_thread(info.wait_for_publish, 5.0)
                except RuntimeError:
                    self._mark_disconnected()
                    if attempt < 2:
                        continue
                    raise
                if info.is_published():
                    return
                self._mark_disconnected()
                if attempt < 2:
                    continue
            raise TimeoutError(
                f"MQTT publish recovery timed out after broker loss: {topic}"
            )

    def _on_connect(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        _flags: mqtt.ConnectFlags,
        reason_code: ReasonCode,
        _properties: Properties | None,
    ) -> None:
        if reason_code.is_failure:
            return
        self._connected = True
        for topic, qos in self._subscriptions.items():
            result, _ = self._client.subscribe(topic, qos=qos)
            if result != mqtt.MQTT_ERR_SUCCESS:
                logger.error(
                    "mqtt_resubscribe_failed",
                    topic=topic,
                    result_code=result,
                )
        if self._loop is not None and self._connected_event is not None:
            self._loop.call_soon_threadsafe(self._connected_event.set)

    def _on_disconnect(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        _flags: mqtt.DisconnectFlags,
        _reason_code: ReasonCode,
        _properties: Properties | None,
    ) -> None:
        self._mark_disconnected()
        if self._loop is not None and self._disconnected_event is not None:
            self._loop.call_soon_threadsafe(self._disconnected_event.set)

    def _on_message(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        message: mqtt.MQTTMessage,
    ) -> None:
        if self._loop is None:
            return
        for pattern, handlers in self._handlers.items():
            if mqtt.topic_matches_sub(pattern, message.topic):
                for handler in handlers:
                    asyncio.run_coroutine_threadsafe(
                        _invoke_handler(
                            handler,
                            self._handler_locks[handler],
                            message.topic,
                            bytes(message.payload),
                        ),
                        self._loop,
                    )

    async def _wait_until_connected(self) -> None:
        """Wait for initial connection or automatic broker recovery."""

        if self._connected:
            return
        if self._connected_event is None:
            raise RuntimeError("MQTT client has not been started")
        try:
            await asyncio.wait_for(
                self._connected_event.wait(),
                timeout=self.connect_timeout_s,
            )
        except TimeoutError:
            raise TimeoutError(
                f"MQTT recovery from {self.host}:{self.port} timed out"
            ) from None

    def _mark_disconnected(self) -> None:
        """Clear connection state from callbacks or synchronous paho errors."""

        self._connected = False
        if self._loop is not None and self._connected_event is not None:
            try:
                running_loop = asyncio.get_running_loop()
            except RuntimeError:
                running_loop = None
            if running_loop is self._loop:
                self._connected_event.clear()
            else:
                self._loop.call_soon_threadsafe(self._connected_event.clear)


async def _invoke_handler(
    handler: MessageHandler,
    lock: asyncio.Lock,
    topic: str,
    payload: bytes,
) -> None:
    """Convert a generic Awaitable-returning callback into a concrete coroutine."""

    async with lock:
        try:
            await handler(topic, payload)
        except PlatformError as exc:
            logger.warning(
                "mqtt_message_rejected",
                topic=topic,
                handler=getattr(handler, "__qualname__", repr(handler)),
                error_code=exc.code.value,
                reason=exc.message,
            )
        except Exception as exc:
            logger.exception(
                "mqtt_handler_failed",
                topic=topic,
                handler=getattr(handler, "__qualname__", repr(handler)),
                error_type=type(exc).__name__,
                error=str(exc),
            )
