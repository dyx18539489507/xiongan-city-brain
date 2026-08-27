"""Scheduled scenario disturbances execute deterministically and audibly."""

from collections.abc import Sequence

from traffic_platform.experiment_service.disturbances import DisturbanceRuntime
from traffic_platform.experiment_service.engine import ExperimentControl
from traffic_platform.scenario_engine.models import Disturbance, ScenarioConfig


class FakeAdapter:
    """Small protocol fake that records every runtime mutation."""

    def __init__(self) -> None:
        self.vehicle_ids = ["base-vehicle"]
        self.closed: list[str] = []
        self.reopened: list[str] = []
        self.stopped: list[tuple[str, float]] = []
        self.resumed: list[str] = []
        self.added: list[tuple[str, str, tuple[str, ...]]] = []

    def close_lane(self, lane_id: str) -> None:
        self.closed.append(lane_id)

    def reopen_lane(self, lane_id: str) -> None:
        self.reopened.append(lane_id)

    def inject_incident(self, vehicle_id: str, duration_s: float) -> bool:
        self.stopped.append((vehicle_id, duration_s))
        return True

    def clear_incident(self, vehicle_id: str) -> bool:
        self.resumed.append(vehicle_id)
        return True

    def get_vehicle_ids(
        self,
        preferred_edge_ids: set[str] | None = None,
    ) -> tuple[str, ...]:
        del preferred_edge_ids
        return tuple(sorted(self.vehicle_ids))

    def incident_is_stopped(self, vehicle_id: str) -> bool:
        return any(candidate == vehicle_id for candidate, _ in self.stopped)

    def get_representative_route(
        self,
        preferred_edge_ids: set[str] | None = None,
        *,
        vehicle_type: str | None = None,
    ) -> tuple[str, ...] | None:
        del preferred_edge_ids, vehicle_type
        return ("edge-a", "edge-b")

    def add_vehicle(
        self,
        vehicle_id: str,
        vehicle_type: str,
        route_edges: Sequence[str],
    ) -> None:
        self.vehicle_ids.append(vehicle_id)
        self.added.append((vehicle_id, vehicle_type, tuple(route_edges)))


def scenario() -> ScenarioConfig:
    """Build one strict short schedule for deterministic unit execution."""

    return ScenarioConfig.model_validate(
        {
            "schema_version": "1.0",
            "scenario_id": "test",
            "display_name": "test",
            "provenance": "engineering_demo_placeholder",
            "is_real_measured_network": False,
            "network_file": "network.net.xml",
            "simulation": {
                "duration_s": 10.0,
                "step_length_s": 1.0,
                "seed": 11,
                "gui": False,
            },
            "demand": [
                {
                    "origin_zone": "a",
                    "destination_zone": "b",
                    "flow_veh_h": 3600.0,
                    "begin_s": 0.0,
                    "end_s": 10.0,
                    "route_alternatives": True,
                }
            ],
            "vehicle_type_ratios": {
                "passenger": 1.0,
            },
            "connected_vehicle_penetration": 0.0,
            "flow_multiplier": 1.0,
            "signal_plan": "test",
            "disturbances": [
                {
                    "event_id": "works",
                    "type": "roadwork",
                    "simulation_time_s": 1.0,
                    "duration_s": 2.0,
                    "target": "lane",
                    "parameters": {},
                },
                {
                    "event_id": "incident",
                    "type": "incident",
                    "simulation_time_s": 2.0,
                    "duration_s": 2.0,
                    "target": "vehicle",
                    "parameters": {},
                },
                {
                    "event_id": "dispersal",
                    "type": "event_dispersal",
                    "simulation_time_s": 3.0,
                    "duration_s": 2.0,
                    "target": "zone",
                    "parameters": {"flow_multiplier": 2.0},
                },
                {
                    "event_id": "emergency",
                    "type": "emergency_vehicle",
                    "simulation_time_s": 4.0,
                    "duration_s": 1.0,
                    "target": "corridor",
                    "parameters": {"priority": True},
                },
            ],
            "communication": {
                "profile": "N0",
                "cloud_edge": {},
                "edge_vehicle": {},
            },
            "algorithm": {
                "name": "fixed-time",
                "parameters": {},
            },
            "sampling": {
                "control_hz": 1.0,
                "intersection_hz": 1.0,
                "dashboard_hz": 1.0,
                "vehicle_trajectory_hz": 0.0,
                "experiment_summary_hz": 0.2,
            },
        }
    )


def test_full_disturbance_schedule_mutates_adapter_and_records_events() -> None:
    adapter = FakeAdapter()
    runtime = DisturbanceRuntime(
        scenario(),
        seed=11,
        fallback_roadwork_lane="fallback-lane",
    )

    events = [
        event for timestamp in range(1, 6) for event in runtime.tick(float(timestamp), adapter)
    ]
    event_names = [str(event["event"]) for event in events]

    assert adapter.closed == ["fallback-lane"]
    assert adapter.reopened == ["fallback-lane"]
    assert adapter.stopped == [("base-vehicle", 2.0)]
    assert adapter.resumed == ["base-vehicle"]
    assert len(adapter.added) == 3
    assert adapter.added[-1][1] == "emergency"
    assert "EVENT_DISPERSAL_VEHICLE_INJECTED" in event_names
    assert "EMERGENCY_VEHICLE_INJECTED" in event_names
    assert runtime.active_event_ids(5.0) == []


def test_live_control_schedules_real_incident_and_event_dispersal() -> None:
    control = ExperimentControl()
    control.advance_simulation_time(12.0)
    control.inject_fault(
        "incident",
        {"duration_s": 30.0, "target": "downstream_bottleneck"},
    )
    control.inject_fault(
        "large_event",
        {
            "duration_s": 60.0,
            "target": "north_activity",
            "flow_multiplier": 2.5,
        },
    )
    pending = control.drain_pending_disturbances()
    assert [(item.type, item.simulation_time_s) for item in pending] == [
        ("incident", 12.0),
        ("event_dispersal", 12.0),
    ]
    assert pending[1].parameters["flow_multiplier"] == 2.5
    assert control.drain_pending_disturbances() == []

    adapter = FakeAdapter()
    runtime = DisturbanceRuntime(
        scenario().model_copy(update={"disturbances": []}),
        seed=11,
        fallback_roadwork_lane="fallback-lane",
    )
    for disturbance in pending:
        runtime.schedule(Disturbance.model_validate(disturbance.model_dump()))
    events = runtime.tick(12.0, adapter)
    assert {event["event"] for event in events} >= {
        "INCIDENT_VEHICLE_STOPPED",
        "EVENT_DISPERSAL_STARTED",
        "EVENT_DISPERSAL_VEHICLE_INJECTED",
    }


def test_incident_uses_the_canonical_paired_vehicle_when_provided() -> None:
    adapter = FakeAdapter()
    runtime = DisturbanceRuntime(
        scenario().model_copy(update={"disturbances": []}),
        seed=11,
        fallback_roadwork_lane="fallback-lane",
    )
    runtime.schedule(
        Disturbance(
            event_id="paired-incident",
            type="incident",
            simulation_time_s=5.0,
            duration_s=30.0,
            target="downstream_bottleneck",
            parameters={"vehicle_id": "shared-vehicle", "edge_id": "edge-a"},
        )
    )

    runtime.tick(5.0, adapter)

    assert adapter.stopped == [("shared-vehicle", 30.0)]


def test_paired_control_preserves_the_canonical_incident_target() -> None:
    control = ExperimentControl()
    control.queue_fault(
        event_id="paired-incident",
        fault_type="incident",
        apply_at_simulation_time_s=12.0,
        parameters={
            "duration_s": 30.0,
            "target": "downstream_bottleneck",
            "vehicle_id": "shared-vehicle",
            "edge_id": "edge-a",
        },
    )

    control.advance_simulation_time(12.0)

    pending = control.drain_pending_disturbances()
    assert len(pending) == 1
    assert pending[0].parameters == {
        "vehicle_id": "shared-vehicle",
        "edge_id": "edge-a",
    }
