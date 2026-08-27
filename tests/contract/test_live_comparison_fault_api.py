"""Pair-scoped live fault API contracts."""

from fastapi.testclient import TestClient

from traffic_platform.api.app import create_app
from traffic_platform.experiment_service.engine import ExperimentControl


def test_live_comparison_faults_are_scoped_to_the_selected_pair() -> None:
    app = create_app()
    platform = app.state.platform
    for item in platform.live_comparisons.values():
        item["status"] = "stopped"
    for item in platform.experiments.values():
        item["status"] = "stopped"
    for item in platform.benchmarks.values():
        item["status"] = "completed"
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/live-comparisons",
            json={
                "baseline_algorithm": "fixed-time",
                "candidate_algorithm": "coordinated-max-pressure",
                "duration_s": 60.0,
            },
        )
        assert created.status_code == 201
        pair_id = created.json()["id"]
        platform.live_comparisons[pair_id]["status"] = "running"
        unrelated = ExperimentControl()
        platform.controls["unrelated-experiment"] = unrelated

        injected = client.post(
            f"/api/v1/live-comparisons/{pair_id}/faults/inject",
            json={
                "fault_type": "cloud_offline",
                "target": "cloud-coordinator",
                "duration_s": 30.0,
                "parameters": {},
            },
        )

        assert injected.status_code == 202
        control = platform.comparison_controls[pair_id]
        assert injected.json()["status"] == "pending"
        assert control.baseline.cloud_online is True
        assert control.candidate.cloud_online is True
        assert unrelated.cloud_online is True
        assert injected.json()["pair_id"] == pair_id
        assert set(injected.json()["experiment_ids"]) == {
            f"{pair_id}-baseline",
            f"{pair_id}-candidate",
        }
        apply_at = float(injected.json()["injection_simulation_time_s"])
        assert control.baseline.advance_simulation_time(apply_at) == []
        assert control.candidate.advance_simulation_time(apply_at) == []
        assert control.baseline.cloud_online is False
        assert control.candidate.cloud_online is False
        manifest = control.fault_manifest(injected.json()["id"])
        assert manifest is not None
        assert manifest["status"] == "applied"
        assert manifest["runner_status"] == {
            "baseline": {"status": "applied", "simulation_time_s": apply_at},
            "candidate": {"status": "applied", "simulation_time_s": apply_at},
        }

        cleared = client.post(f"/api/v1/live-comparisons/{pair_id}/faults/clear")
        assert cleared.status_code == 200
        assert cleared.json() == {"pair_id": pair_id, "cleared": 1}
        assert control.baseline.cloud_online is True
        assert control.candidate.cloud_online is True
