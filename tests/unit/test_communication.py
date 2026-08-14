"""Event-driven delay, loss, duplication and offline behavior."""

from traffic_platform.communication_emulator.channel import (
    ChannelConfig,
    SimulatedChannel,
)


def test_fixed_delay_uses_simulation_queue() -> None:
    channel = SimulatedChannel[str](ChannelConfig(base_latency_ms=100.0), seed=1)
    record = channel.send("m1", "payload", current_time_s=1.0)
    assert record.scheduled_at_s == 1.1
    assert channel.advance(1.09) == []
    assert channel.advance(1.1) == [("m1", "payload")]


def test_loss_and_offline_are_recorded_without_sleep() -> None:
    lost = SimulatedChannel[str](ChannelConfig(packet_loss_rate=1.0), seed=1)
    assert lost.send("m1", "payload", current_time_s=0.0).dropped
    offline = SimulatedChannel[str](ChannelConfig(), seed=1)
    offline.set_offline(5.0, 30.0)
    record = offline.send("m2", "payload", current_time_s=10.0)
    assert record.dropped
    assert record.offline


def test_seed_reproduces_jitter() -> None:
    config = ChannelConfig(base_latency_ms=100.0, jitter_ms=30.0)
    first = SimulatedChannel[str](config, seed=42)
    second = SimulatedChannel[str](config, seed=42)
    assert first.send("a", "x", current_time_s=0.0).actual_latency_ms == second.send(
        "a", "x", current_time_s=0.0
    ).actual_latency_ms


def test_corruption_mutates_payload_and_is_recorded() -> None:
    channel = SimulatedChannel[bytes](
        ChannelConfig(corruption_rate=1.0),
        seed=3,
        corruptor=lambda payload: payload[:-1] + b"X",
    )
    record = channel.send("m3", b"abc", current_time_s=0.0)
    assert record.corrupted is True
    assert channel.advance(0.0) == [("m3", b"abX")]
