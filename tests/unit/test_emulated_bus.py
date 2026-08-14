"""Tests for simulation-time transport impairment."""

import json

from traffic_platform.communication_emulator.channel import ChannelConfig
from traffic_platform.messaging.emulated import EmulatedMessageBus


async def test_latency_is_advanced_by_simulation_time_without_sleep() -> None:
    bus = EmulatedMessageBus(ChannelConfig(base_latency_ms=500), seed=2)
    received: list[str] = []

    async def handler(topic: str, payload: bytes) -> None:
        received.append(f"{topic}:{json.loads(payload)['message_id']}")

    await bus.connect()
    await bus.subscribe("traffic/+/state", handler)
    payload = json.dumps({"message_id": "m-1", "simulation_time": 10.0}).encode()
    await bus.publish("traffic/edge/state", payload)
    assert received == []
    await bus.advance(10.49)
    assert received == []
    await bus.advance(10.5)
    assert received == ["traffic/edge/state:m-1"]
    assert bus.records[0].actual_latency_ms == 500


async def test_live_config_can_drop_messages_deterministically() -> None:
    bus = EmulatedMessageBus(seed=1)
    received: list[bytes] = []

    async def handler(_: str, payload: bytes) -> None:
        received.append(payload)

    await bus.connect()
    await bus.subscribe("#", handler)
    bus.configure(ChannelConfig(packet_loss_rate=1.0))
    payload = json.dumps({"message_id": "m-2", "simulation_time": 4.0}).encode()
    await bus.publish("traffic/cloud/state", payload)
    await bus.advance(100)
    assert received == []
    assert bus.records[-1].dropped is True


async def test_corruption_reaches_subscriber_and_is_audited() -> None:
    bus = EmulatedMessageBus(ChannelConfig(corruption_rate=1.0), seed=8)
    received: list[bytes] = []

    async def handler(_: str, payload: bytes) -> None:
        received.append(payload)

    await bus.connect()
    await bus.subscribe("#", handler)
    original = json.dumps(
        {"message_id": "m-3", "simulation_time": 1.0}
    ).encode()
    await bus.publish("traffic/cloud/state", original)
    assert received and received[0] != original
    assert bus.records[-1].corrupted is True


async def test_broker_interruption_and_recovery_are_simulation_timed() -> None:
    bus = EmulatedMessageBus(seed=9)
    received: list[bytes] = []

    async def handler(_: str, payload: bytes) -> None:
        received.append(payload)

    await bus.connect()
    await bus.subscribe("#", handler)
    bus.set_broker_offline(5.0, 10.0)
    offline = json.dumps(
        {"message_id": "broker-offline", "simulation_time": 6.0}
    ).encode()
    recovered = json.dumps(
        {"message_id": "broker-recovered", "simulation_time": 15.0}
    ).encode()
    await bus.publish("traffic/development/edge/e1/state", offline)
    await bus.publish("traffic/development/edge/e1/state", recovered)
    assert received == [recovered]
    assert bus.records[-2].offline is True
    assert bus.records[-2].recovery_time_s == 9.0
    assert bus.records[-1].offline is False


async def test_edge_endpoint_offline_drops_only_routed_edge_messages() -> None:
    bus = EmulatedMessageBus(seed=10)
    received: list[str] = []

    async def handler(topic: str, _: bytes) -> None:
        received.append(topic)

    await bus.connect()
    await bus.subscribe("#", handler)
    bus.set_endpoint_offline("edge", 0.0, 5.0)
    edge_payload = json.dumps(
        {"message_id": "edge-message", "simulation_time": 1.0}
    ).encode()
    report_payload = json.dumps(
        {"message_id": "report-message", "simulation_time": 1.0}
    ).encode()
    await bus.publish("traffic/development/edge/e1/state", edge_payload)
    await bus.publish(
        "traffic/development/experiment/x/event",
        report_payload,
    )
    assert received == ["traffic/development/experiment/x/event"]
