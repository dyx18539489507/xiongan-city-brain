import json
from pathlib import Path

from traffic_platform.comparison_service import PairedDigitalTwinHub
from traffic_platform.realtime.models import DigitalTwinSourceFrame


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


def _frame(experiment_id: str, time_s: float, queue: int) -> DigitalTwinSourceFrame:
    return DigitalTwinSourceFrame(
        experiment_id=experiment_id,
        scenario_id="scene",
        simulation_time_s=time_s,
        tick_hz=10.0,
        vehicles=(),
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
