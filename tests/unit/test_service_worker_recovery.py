"""Independent edge worker persistence and restart recovery tests."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from pytest import MonkeyPatch
from tests.factories import cloud_strategy, edge_factory, intersection, regional

from traffic_platform.common.runtime_registry import RuntimeRegistry
from traffic_platform.contracts.factory import MessageFactory
from traffic_platform.contracts.models import ExperimentEvent, SourceType
from traffic_platform.edge_service.state_machine import EdgeMode
from traffic_platform.messaging.in_memory import InMemoryMessageBus
from traffic_platform.service_workers import ServiceWorker


class _Registry:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], dict[str, Any]] = {}

    async def get_latest(
        self,
        category: str,
        identifier: str,
    ) -> dict[str, Any] | None:
        return self.values.get((category, identifier))

    async def set_latest(
        self,
        category: str,
        identifier: str,
        payload: dict[str, Any],
        *,
        ttl_s: int = 3600,
    ) -> None:
        del ttl_s
        self.values[(category, identifier)] = dict(payload)


async def test_rsu_worker_creates_real_sumo_rsu_edge_message_chain() -> None:
    bus = InMemoryMessageBus()
    await bus.connect()
    registry = _Registry()
    rsu = ServiceWorker(
        "rsu-service",
        bus,
        cast(RuntimeRegistry, registry),
        environment="test",
        instance_id="rsu-one",
    )
    edge = ServiceWorker(
        "edge-service",
        bus,
        cast(RuntimeRegistry, registry),
        environment="test",
        instance_id="edge-one",
    )
    await rsu._subscribe_role()
    await edge._subscribe_role()
    forwarded: list[bytes] = []

    async def capture(_topic: str, payload: bytes) -> None:
        forwarded.append(payload)

    await bus.subscribe("traffic/test/edge/+/state", capture, qos=1)
    factory = edge_factory()
    observation = regional(factory, intersection(factory))
    await bus.publish(
        "traffic/test/sumo/runner-one/observation",
        observation.model_dump_json().encode(),
        qos=1,
    )
    second = regional(factory, intersection(factory))
    await bus.publish(
        "traffic/test/sumo/runner-one/observation",
        second.model_dump_json().encode(),
        qos=1,
    )
    assert ("rsu-regional-state", observation.experiment_id) in registry.values
    assert len(forwarded) == 2
    assert json.loads(forwarded[0])["source_type"] == SourceType.EDGE.value
    assert json.loads(forwarded[1])["sequence_number"] > json.loads(forwarded[0])["sequence_number"]
    for controller in edge._edge_controllers.values():
        controller.close()
    await bus.disconnect()


async def test_edge_worker_restores_versions_and_resynchronizes() -> None:
    bus = InMemoryMessageBus()
    await bus.connect()
    registry = _Registry()
    worker = ServiceWorker(
        "edge-service",
        bus,
        cast(RuntimeRegistry, registry),
        environment="test",
        instance_id="edge-one",
    )
    factory = edge_factory()
    state = regional(factory, intersection(factory))
    await worker._edge_regional_state("traffic/test/edge/e/state", state.model_dump_json().encode())
    await worker._edge_strategy(
        "traffic/test/cloud/strategy/J1",
        cloud_strategy(factory, version=1).model_dump_json().encode(),
    )
    assert worker._edge_machines["experiment-test"].mode == EdgeMode.RECOVERY_SYNC
    snapshot = registry.values[("edge-degradation", "experiment-test")]
    assert snapshot["last_strategy_versions"] == {"J1": 1}

    restarted = ServiceWorker(
        "edge-service",
        bus,
        cast(RuntimeRegistry, registry),
        environment="test",
        instance_id="edge-one",
    )
    await restarted._edge_strategy(
        "traffic/test/cloud/strategy/J1",
        cloud_strategy(factory, version=2).model_dump_json().encode(),
    )
    restored_machine = restarted._edge_machines["experiment-test"]
    assert restored_machine.last_strategy_versions == {"J1": 2}
    assert restored_machine.mode == EdgeMode.RECOVERY_SYNC
    assert any(
        transition.reason == "EDGE_RESTART_RESTORED" for transition in restored_machine.transitions
    )
    restored_machine.tick(30.0)
    await restarted._edge_strategy(
        "traffic/test/cloud/strategy/J1",
        cloud_strategy(factory, version=3).model_dump_json().encode(),
    )
    assert restored_machine.last_simulation_time == 30.0
    assert all(
        transition.reason != "SIMULATION_TIME_ROLLBACK"
        for transition in restored_machine.transitions
    )
    for controller in [
        *worker._edge_controllers.values(),
        *restarted._edge_controllers.values(),
    ]:
        controller.close()
    await bus.disconnect()


async def test_report_worker_generates_independent_artifacts(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("RESULTS_ROOT", str(tmp_path))
    experiment_dir = tmp_path / "exp-report"
    experiment_dir.mkdir()
    result_path = experiment_dir / "result.json"
    result_path.write_text(
        json.dumps(
            {
                "experiment_id": "exp-report",
                "algorithm": "fixed-time",
                "metrics": {"mean_speed_m_s": 8.0},
                "samples": [
                    {
                        "mean_speed_m_s": 8.0,
                        "total_queue_vehicles": 2,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    registry = _Registry()
    worker = ServiceWorker(
        "report-service",
        InMemoryMessageBus(),
        cast(RuntimeRegistry, registry),
        environment="test",
        instance_id="report-one",
    )
    factory = MessageFactory(
        source_id="experiment-api",
        source_type=SourceType.EXPERIMENT,
        scenario_id="scenario-test",
        experiment_id="exp-report",
        environment="test",
    )
    event = factory.build(
        ExperimentEvent,
        simulation_time=10.0,
        event_type="REPORT_READY",
        payload={"result_file": str(result_path)},
    )
    await worker._generate_independent_report(event)
    assert (experiment_dir / "report-service" / "report.html").is_file()
    assert ("report-artifact", "exp-report") in registry.values


async def test_worker_applies_shared_real_mqtt_fault_profile() -> None:
    registry = _Registry()
    bus = InMemoryMessageBus()
    await bus.connect()
    worker = ServiceWorker(
        "cloud-service",
        bus,
        cast(RuntimeRegistry, registry),
        environment="test",
        instance_id="cloud-one",
    )
    state = regional(edge_factory(), intersection(edge_factory()))
    registry.values[("communication-fault-profile", "active")] = {
        "faults": [
            {
                "fault_type": "packet_loss",
                "target": "cloud_edge",
                "experiment_ids": [state.experiment_id],
                "parameters": {"packet_loss_rate": 1.0},
                "expires_at": (datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
            }
        ]
    }

    assert not await worker._communication_allowed(
        state,
        channel="cloud_edge",
    )
    assert any(
        key[0] == "communication-event" and value["dropped"] is True
        for key, value in registry.values.items()
    )

    registry.values[("communication-fault-profile", "active")] = {
        "faults": [
            {
                "fault_type": "packet_loss",
                "target": "cloud_edge",
                "experiment_ids": ["another-experiment"],
                "parameters": {"packet_loss_rate": 1.0},
                "expires_at": (datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
            }
        ]
    }
    assert await worker._communication_allowed(state, channel="cloud_edge")

    registry.values[("communication-fault-profile", "active")] = {
        "faults": [
            {
                "fault_type": "packet_loss",
                "target": "cloud_edge",
                "parameters": {"packet_loss_rate": 1.0},
                "expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
            }
        ]
    }
    assert await worker._communication_allowed(state, channel="cloud_edge")
    await bus.disconnect()
