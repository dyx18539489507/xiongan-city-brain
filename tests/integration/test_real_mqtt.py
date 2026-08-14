"""Optional contract smoke test against a real Eclipse Mosquitto broker."""

import asyncio
import os
from uuid import uuid4

import pytest

from traffic_platform.messaging.mqtt import MqttMessageBus


@pytest.mark.integration
async def test_real_mosquitto_publish_subscribe_round_trip() -> None:
    host = os.environ.get("TRAFFIC_MQTT_TEST_HOST")
    if not host:
        pytest.skip("TRAFFIC_MQTT_TEST_HOST is not configured")
    port = int(os.environ.get("TRAFFIC_MQTT_TEST_PORT", "1883"))
    topic = f"traffic/test/contract/{uuid4().hex}"
    received: asyncio.Future[tuple[str, bytes]] = (
        asyncio.get_running_loop().create_future()
    )

    async def handler(message_topic: str, payload: bytes) -> None:
        if not received.done():
            received.set_result((message_topic, payload))

    bus = MqttMessageBus(host, port, connect_timeout_s=5.0)
    await bus.connect()
    try:
        await bus.subscribe(topic, handler, qos=1)
        await asyncio.sleep(0.1)
        await bus.publish(topic, b'{"schema_version":"1.0.0"}', qos=1)
        message_topic, payload = await asyncio.wait_for(received, timeout=5.0)
        assert message_topic == topic
        assert payload == b'{"schema_version":"1.0.0"}'
    finally:
        await bus.disconnect()
