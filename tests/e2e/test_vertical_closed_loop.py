"""Actual SUMO -> edge -> cloud -> safety -> SUMO -> vehicle -> report loop."""

import os
from pathlib import Path

import pytest

from traffic_platform.experiment_service.engine import ExperimentRunner, smoke_config
from traffic_platform.messaging.in_memory import InMemoryMessageBus


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_complete_twenty_intersection_vertical_loop(tmp_path: Path) -> None:
    sumo_home = os.environ.get("SUMO_HOME")
    if not sumo_home:
        pytest.skip("SUMO_HOME is not configured")
    bus = InMemoryMessageBus()
    config = smoke_config(
        "coordinated-max-pressure",
        duration_s=15.0,
        seed=42,
        result_root=tmp_path,
    )
    result = await ExperimentRunner(
        config,
        sumo_home=Path(sumo_home),
        bus=bus,
    ).run()
    topics = [message.topic for message in bus.messages]
    assert result["actual_run"] is True
    assert len(result["samples"]) == 15
    assert any("/edge/edge-rongdong/state" in topic for topic in topics)
    assert any("/cloud/strategy/" in topic for topic in topics)
    assert any("/edge/edge-rongdong/feedback" in topic for topic in topics)
    assert max(sample["guidance_count"] for sample in result["samples"]) > 0
    transitions = [
        event.get("detail", "")
        for event in result["events"]
        if event["event"] == "EDGE_MODE_TRANSITION"
    ]
    assert any("RECOVERY_SYNC" in detail for detail in transitions)
    assert any("CLOUD_COORDINATED" in detail for detail in transitions)
    artifacts = result["artifacts"]
    assert Path(artifacts["html"]).is_file()
    assert Path(artifacts["json"]).is_file()

