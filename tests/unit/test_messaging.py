"""Transport-neutral topic delivery and MQTT wildcard semantics."""

import asyncio
from typing import Any, cast

import paho.mqtt.client as mqtt
import pytest
from paho.mqtt.properties import Properties
from paho.mqtt.reasoncodes import ReasonCode

from traffic_platform.messaging.in_memory import InMemoryMessageBus, topic_matches
from traffic_platform.messaging.mqtt import MqttMessageBus


def test_topic_matching() -> None:
    assert topic_matches("traffic/+/edge/#", "traffic/test/edge/edge-1/state")
    assert not topic_matches("traffic/prod/edge/+", "traffic/test/edge/e1")


@pytest.mark.asyncio
async def test_in_memory_bus_delivers_serialized_payload() -> None:
    bus = InMemoryMessageBus()
    await bus.connect()
    received: list[bytes] = []

    async def handler(_topic: str, payload: bytes) -> None:
        received.append(payload)

    await bus.subscribe("traffic/+/edge/+/state", handler)
    await bus.publish("traffic/test/edge/e1/state", b'{"real":true}')
    assert received == [b'{"real":true}']
    assert bus.messages[0].qos == 1
    await bus.disconnect()


@pytest.mark.asyncio
async def test_mqtt_reconnect_restores_subscriptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = MqttMessageBus("broker", 1883)
    bus._loop = asyncio.get_running_loop()
    bus._connected_event = asyncio.Event()
    bus._subscriptions["traffic/development/edge/+/state"] = 1
    subscriptions: list[tuple[str, int]] = []

    def subscribe(topic: str, qos: int) -> tuple[int, int]:
        subscriptions.append((topic, qos))
        return mqtt.MQTT_ERR_SUCCESS, 1

    monkeypatch.setattr(bus._client, "subscribe", subscribe)
    reason = cast(ReasonCode, type("SuccessReason", (), {"is_failure": False})())
    bus._on_connect(
        bus._client,
        None,
        cast(Any, object()),
        reason,
        cast(Properties | None, None),
    )
    await asyncio.sleep(0)

    assert bus._connected_event.is_set()
    assert subscriptions == [("traffic/development/edge/+/state", 1)]


@pytest.mark.asyncio
async def test_mqtt_publish_retries_no_connection_during_broker_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = MqttMessageBus("broker", 1883, connect_timeout_s=1.0)
    bus._loop = asyncio.get_running_loop()
    bus._connected_event = asyncio.Event()
    bus._connected_event.set()
    bus._connected = True
    publish_codes = iter([mqtt.MQTT_ERR_NO_CONN, mqtt.MQTT_ERR_SUCCESS])
    attempts = 0

    class PublishInfo:
        def __init__(self, rc: int) -> None:
            self.rc = rc

    def publish(*_args: object, **_kwargs: object) -> PublishInfo:
        nonlocal attempts
        attempts += 1
        return PublishInfo(next(publish_codes))

    async def reconnect() -> None:
        await asyncio.sleep(0.01)
        bus._connected = True
        assert bus._connected_event is not None
        bus._connected_event.set()

    monkeypatch.setattr(bus._client, "publish", publish)
    reconnect_task = asyncio.create_task(reconnect())
    await bus.publish("traffic/test", b"payload", qos=0)
    await reconnect_task

    assert attempts == 2
