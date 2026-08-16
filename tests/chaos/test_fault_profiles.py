"""Communication and persistence chaos profiles."""

from pathlib import Path

import pytest

from traffic_platform.communication_emulator.channel import ChannelConfig, SimulatedChannel
from traffic_platform.experiment_service.engine import ExperimentControl
from traffic_platform.storage import BufferedBatchWriter, DataPriority, WriteItem


@pytest.mark.chaos
@pytest.mark.parametrize("latency_ms", [100.0, 500.0])
def test_latency_profiles_use_simulation_time(latency_ms: float) -> None:
    channel: SimulatedChannel[str] = SimulatedChannel(
        ChannelConfig(base_latency_ms=latency_ms),
        seed=4,
    )
    channel.send("message", "payload", current_time_s=10.0)
    assert channel.advance(10.0 + latency_ms / 1000 - 0.001) == []
    assert channel.advance(10.0 + latency_ms / 1000) == [("message", "payload")]


@pytest.mark.chaos
def test_ten_percent_packet_loss_is_seeded_and_auditable() -> None:
    channel: SimulatedChannel[int] = SimulatedChannel(
        ChannelConfig(packet_loss_rate=0.1),
        seed=11,
    )
    for index in range(1000):
        channel.send(str(index), index, current_time_s=float(index))
    dropped = sum(record.dropped for record in channel.records)
    assert 70 <= dropped <= 130


@pytest.mark.chaos
async def test_database_outage_preserves_critical_event(tmp_path: Path) -> None:
    async def unavailable(_: list[WriteItem]) -> None:
        raise ConnectionError("database temporarily unavailable")

    fallback = tmp_path / "critical.jsonl"
    writer = BufferedBatchWriter(
        unavailable,
        batch_size=1,
        max_items=2,
        fallback_path=fallback,
    )
    accepted = await writer.submit(
        WriteItem("event", {"event": "EDGE_AUTONOMOUS"}, DataPriority.EVENT)
    )
    await writer.close()
    assert accepted is True
    assert "EDGE_AUTONOMOUS" in fallback.read_text(encoding="utf-8")


@pytest.mark.chaos
def test_live_faults_expire_independently_on_simulation_clock() -> None:
    control = ExperimentControl()
    control.advance_simulation_time(10.0)
    control.inject_fault(
        "communication_latency",
        {"latency_ms": 500.0, "duration_s": 5.0},
    )
    control.inject_fault(
        "packet_loss",
        {"packet_loss_rate": 0.1, "duration_s": 10.0},
    )

    assert control.channel_config.base_latency_ms == 500.0
    assert control.channel_config.packet_loss_rate == 0.1
    assert control.advance_simulation_time(15.0) == ["communication_latency"]
    assert control.channel_config.base_latency_ms == 0.0
    assert control.channel_config.packet_loss_rate == 0.1
    assert control.advance_simulation_time(20.0) == ["packet_loss"]
    assert control.channel_config == ChannelConfig()


def test_simulation_rate_only_paces_wall_clock() -> None:
    control = ExperimentControl()
    assert control.simulation_rate is None
    control.set_simulation_rate(4.0)
    assert control.simulation_rate == 4.0
    control.set_simulation_rate(None)
    assert control.simulation_rate is None
    with pytest.raises(ValueError, match="simulation rate"):
        control.set_simulation_rate(0.0)
