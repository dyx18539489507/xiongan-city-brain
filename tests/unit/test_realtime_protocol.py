"""Entity-level realtime protocol tests using actual SUMO snapshot types."""

import json
from pathlib import Path

from traffic_platform.realtime import DigitalTwinHub, DigitalTwinSourceFrame
from traffic_platform.sumo_adapter import (
    IntersectionSnapshot,
    PedestrianSnapshot,
    VehicleSnapshot,
)


def vehicle(identifier: str, *, x_m: float, vehicle_class: str = "passenger") -> VehicleSnapshot:
    return VehicleSnapshot(
        vehicle_id=identifier,
        vehicle_type="e_bike" if vehicle_class == "bicycle" else "passenger_car",
        vehicle_class=vehicle_class,
        road_id="edge-a",
        lane_id="edge-a_0",
        x_m=x_m,
        y_m=20.0,
        lane_position_m=x_m,
        speed_m_s=8.0,
        acceleration_m_s2=-0.8,
        heading_deg=359.0,
        route_id="route-a",
        next_intersection_id="tls-a",
        distance_to_stop_line_m=25.0,
        waiting_time_s=0.0,
        co2_mg_s=0.0,
        nox_mg_s=0.0,
        fuel_mg_s=0.0,
        signals=8,
        color_rgba=(10, 20, 30, 255),
    )


def pedestrian(identifier: str) -> PedestrianSnapshot:
    return PedestrianSnapshot(
        pedestrian_id=identifier,
        pedestrian_type="pedestrian",
        road_id=":tls-a_c0",
        lane_id=":tls-a_c0_0",
        x_m=12.0,
        y_m=15.0,
        speed_m_s=1.2,
        waiting_time_s=0.0,
        walking_stage_index=0,
        crossing_id=":tls-a_c0",
        waiting_area_id=None,
        heading_deg=90.0,
    )


def signal(state: str, phase: int) -> IntersectionSnapshot:
    return IntersectionSnapshot(
        intersection_id="tls-a",
        phase_index=phase,
        phase_state=state,
        phase_duration_s=30.0,
        next_switch_s=10.0,
        controlled_lane_ids=("edge-a_0",),
    )


def workspace(tmp_path: Path) -> Path:
    manifest = tmp_path / "generated" / "scenes" / "xiongan_rongdong_20.scene.manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "sceneId": "xiongan_rongdong_20",
                "schemaVersion": "1.1",
                "sceneSha256": "abc123",
                "sceneBytes": 100,
                "counts": {"trafficLights": 20},
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_hub_switches_to_the_selected_scenario_manifest(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    manifest = root / "generated" / "scenes" / "planning-cross.scene.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "sceneId": "planning-cross",
                "schemaVersion": "1.1",
                "sceneSha256": "planning123",
                "sceneBytes": 321,
                "counts": {"trafficLights": 1},
            }
        ),
        encoding="utf-8",
    )
    hub = DigitalTwinHub(root, max_frames=4)

    hub.select_scene("planning-cross")

    initial = hub.initial_message()
    assert initial["scene"]["sceneId"] == "planning-cross"
    assert initial["scene"]["sha256"] == "planning123"
    assert initial["scene"]["url"] == "/api/v1/scenes/planning-cross/3d"


def test_hub_splits_motor_bicycle_pedestrian_and_emits_deltas(tmp_path: Path) -> None:
    hub = DigitalTwinHub(workspace(tmp_path), max_frames=4)
    idle = hub.initial_message()
    assert idle["type"] == "init"
    assert idle["scene"]["sha256"] == "abc123"

    hub.publish(
        DigitalTwinSourceFrame(
            experiment_id="exp-1",
            scenario_id="xiongan_rongdong_20",
            simulation_time_s=1.0,
            tick_hz=1.0,
            vehicles=[vehicle("car-1", x_m=10.0), vehicle("bike-1", x_m=5.0, vehicle_class="bicycle")],
            pedestrians=[pedestrian("person-1")],
            traffic_lights=[signal("Gr", 0)],
            events=[],
            conflicts=[
                {
                    "conflict_id": "conflict-1",
                    "participant_a_id": "car-1",
                    "participant_b_id": "person-1",
                    "conflict_type": "motor_pedestrian",
                    "x_m": 11.0,
                    "y_m": 17.5,
                    "minimum_distance_m": 1.2,
                    "relative_speed_m_s": 4.1,
                    "ttc_s": 2.3,
                    "pet_s": None,
                    "severity": "warning",
                }
            ],
            metrics={"mean_speed_m_s": 4.5, "total_queue_vehicles": 3},
            intersection_metrics=[{"intersection_id": "K01", "queue_vehicles": 3}],
        )
    )
    first = hub.messages_after(0)[0]
    assert first["type"] == "init"
    assert [item["id"] for item in first["entities"]["vehicles"]] == ["car-1"]
    assert [item["id"] for item in first["entities"]["bicycles"]] == ["bike-1"]
    assert [item["id"] for item in first["entities"]["pedestrians"]] == ["person-1"]
    assert first["entities"]["vehicles"][0]["brake"] is True
    assert first["entities"]["vehicles"][0]["color"] == "#0A141E"
    assert first["metrics"]["mean_speed_m_s"] == 4.5
    assert first["intersectionMetrics"][0]["queue_vehicles"] == 3
    assert first["conflicts"][0]["id"] == "conflict-1"
    assert first["conflicts"][0]["conflictType"] == "motor_pedestrian"

    hub.publish(
        DigitalTwinSourceFrame(
            experiment_id="exp-1",
            scenario_id="xiongan_rongdong_20",
            simulation_time_s=2.0,
            tick_hz=1.0,
            vehicles=[vehicle("car-1", x_m=18.0)],
            pedestrians=[pedestrian("person-1")],
            traffic_lights=[signal("yr", 1)],
            events=[
                {
                    "simulation_time": 2.0,
                    "event": "ROADWORK_LANE_CLOSED",
                    "detail": "edge-a_0",
                }
            ],
            conflicts=[],
            metrics={"mean_speed_m_s": 5.0, "total_queue_vehicles": 2},
            intersection_metrics=[{"intersection_id": "K01", "queue_vehicles": 2}],
        )
    )
    second = hub.messages_after(1)[0]
    assert [item["id"] for item in second["update"]["vehicles"]] == ["car-1"]
    assert second["remove"]["bicycles"] == ["bike-1"]
    assert second["trafficLights"][0]["state"] == "yr"
    assert second["events"][0]["detail"] == "edge-a_0"
    assert second["metrics"]["total_queue_vehicles"] == 2
    assert second["intersectionMetrics"][0]["queue_vehicles"] == 2
    assert second["conflicts"] == []

    current = hub.initial_message()
    assert current["sequence"] == 2
    assert [item["id"] for item in current["entities"]["vehicles"]] == ["car-1"]
    assert current["entities"]["bicycles"] == []
    assert current["activeEvents"][0]["event"] == "ROADWORK_LANE_CLOSED"
    hub.set_status("completed")
    replay_path = tmp_path / "results" / "exp-1" / "digital_twin.replay.ndjson"
    replay_messages = [
        json.loads(line) for line in replay_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [item["type"] for item in replay_messages] == ["init", "delta", "init"]
    assert replay_messages[1]["simulationTimeS"] == 2.0
    assert replay_messages[1]["metrics"]["mean_speed_m_s"] == 5.0


def test_experiment_change_emits_a_fresh_init_snapshot(tmp_path: Path) -> None:
    hub = DigitalTwinHub(workspace(tmp_path), max_frames=4)
    for sequence, experiment_id in enumerate(("exp-1", "exp-2"), start=1):
        hub.publish(
            DigitalTwinSourceFrame(
                experiment_id=experiment_id,
                scenario_id="xiongan_rongdong_20",
                simulation_time_s=float(sequence),
                tick_hz=1.0,
                vehicles=[vehicle(f"car-{sequence}", x_m=float(sequence))],
                pedestrians=[],
                traffic_lights=[signal("Gr", 0)],
                events=[],
            )
        )
    message = hub.messages_after(1)[0]
    assert message["type"] == "init"
    assert message["experimentId"] == "exp-2"
    assert [item["id"] for item in message["entities"]["vehicles"]] == ["car-2"]
