import json
from pathlib import Path

from traffic_platform.comparison_service import PairedDigitalTwinHub
from traffic_platform.realtime.models import DigitalTwinSourceFrame
from traffic_platform.sumo_adapter import VehicleSnapshot


def _workspace(tmp_path: Path) -> Path:
    manifest = tmp_path / "generated" / "scenes" / "scene.scene.manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "sceneId": "scene",
                "schemaVersion": "1.1",
                "sceneSha256": "abc123",
                "sceneBytes": 100,
                "counts": {"trafficLights": 1},
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


def _vehicle(vehicle_id: str, road_id: str, lane_id: str) -> VehicleSnapshot:
    return VehicleSnapshot(
        vehicle_id=vehicle_id,
        vehicle_type="passenger",
        vehicle_class="passenger",
        road_id=road_id,
        lane_id=lane_id,
        x_m=0.0,
        y_m=0.0,
        lane_position_m=10.0,
        speed_m_s=5.0,
        acceleration_m_s2=0.0,
        heading_deg=0.0,
        route_id="route-1",
        next_intersection_id=None,
        distance_to_stop_line_m=20.0,
        waiting_time_s=0.0,
        co2_mg_s=0.0,
        nox_mg_s=0.0,
        fuel_mg_s=0.0,
    )


def _frame(
    experiment_id: str,
    time_s: float,
    queue: int,
    vehicles: tuple[VehicleSnapshot, ...] = (),
) -> DigitalTwinSourceFrame:
    return DigitalTwinSourceFrame(
        experiment_id=experiment_id,
        scenario_id="scene",
        simulation_time_s=time_s,
        tick_hz=10.0,
        vehicles=vehicles,
        pedestrians=(),
        traffic_lights=(),
        events=(),
        metrics={"total_queue_vehicles": queue, "mean_speed_m_s": 5.0},
        intersection_metrics=(
            {"intersection_id": "K01", "queue_vehicles": queue, "spillback_risk": 0.1},
        ),
    )


def _configured_hub(tmp_path: Path) -> PairedDigitalTwinHub:
    hub = PairedDigitalTwinHub(_workspace(tmp_path))
    hub.configure(
        pair_id="pair-1",
        scenario_id="scene",
        baseline_algorithm="fixed-time",
        candidate_algorithm="coordinated-max-pressure",
        baseline_experiment_id="baseline-1",
        candidate_experiment_id="candidate-1",
        fairness_manifest={"seed": 42},
        fairness_fingerprint="fingerprint-1",
    )
    return hub


def test_paired_hub_emits_only_after_both_sumo_frames_arrive(tmp_path: Path) -> None:
    hub = _configured_hub(tmp_path)
    configured_sequence = hub.sequence

    hub.publish_baseline(_frame("baseline-1", 1.0, 10))
    assert hub.sequence == configured_sequence

    hub.publish_candidate(_frame("candidate-1", 1.0, 6))
    messages = hub.messages_after(configured_sequence)

    assert len(messages) == 1
    message = messages[0]
    assert message["type"] == "comparison-init"
    assert message["simulationTimeS"] == 1.0
    assert message["baseline"]["message"]["simulationTimeS"] == 1.0
    assert message["candidate"]["message"]["simulationTimeS"] == 1.0
    assert message["fairnessFingerprint"] == "fingerprint-1"
    assert message["comparison"]["paired_sample_count"] == 1


def test_paired_hub_invalidates_instead_of_combining_mismatched_times(tmp_path: Path) -> None:
    hub = _configured_hub(tmp_path)

    hub.publish_baseline(_frame("baseline-1", 1.0, 10))
    hub.publish_candidate(_frame("candidate-1", 2.0, 6))

    assert hub.status == "invalid"
    message = hub.initial_message()
    assert message["comparison"]["valid"] is False
    assert "simulation time mismatch" in message["comparison"]["reason"]


def test_paired_hub_rejects_one_side_advancing_twice(tmp_path: Path) -> None:
    hub = _configured_hub(tmp_path)

    hub.publish_baseline(_frame("baseline-1", 1.0, 10))
    hub.publish_baseline(_frame("baseline-1", 2.0, 9))

    assert hub.status == "invalid"
    assert "barrier" in hub.initial_message()["comparison"]["reason"]


def test_paired_hub_preserves_pause_during_an_in_flight_frame(tmp_path: Path) -> None:
    hub = _configured_hub(tmp_path)
    hub.publish_baseline(_frame("baseline-1", 1.0, 10))

    hub.set_status("paused")
    hub.publish_candidate(_frame("candidate-1", 1.0, 6))

    assert hub.status == "paused"
    assert hub.frames[-1]["status"] == "paused"


def test_paired_hub_selects_one_vehicle_on_the_same_physical_edge(tmp_path: Path) -> None:
    hub = _configured_hub(tmp_path)
    hub.publish_baseline(
        _frame(
            "baseline-1",
            10.0,
            3,
            (_vehicle("shared-1", "edge-a", "edge-a_0"),),
        )
    )
    hub.publish_candidate(
        _frame(
            "candidate-1",
            10.0,
            2,
            (
                _vehicle("shared-1", "edge-a", "edge-a_1"),
                _vehicle("candidate-only", "edge-b", "edge-b_0"),
            ),
        )
    )

    selected = hub.select_shared_incident_vehicle("downstream_bottleneck", 42)

    assert selected == {
        "vehicle_id": "shared-1",
        "edge_id": "edge-a",
        "baseline_lane_id": "edge-a_0",
        "candidate_lane_id": "edge-a_1",
    }
