"""FastAPI paths, strict requests and actual scenario inventory."""

import json
import os
import time
from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from traffic_platform.api.app import create_app


def test_open_scenario_folder_only_reveals_registered_generated_scenario(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    scenario_id = "folder-test"
    commands: list[list[str]] = []
    monkeypatch.setattr(
        "traffic_platform.api.app.subprocess.Popen",
        lambda command: commands.append(command),
    )
    app = create_app(tmp_path)
    app.state.platform.scenarios[scenario_id] = object()
    (tmp_path / "scenarios" / "generated" / scenario_id).mkdir(parents=True)
    with TestClient(app) as client:
        response = client.post(f"/api/v1/scenarios/{scenario_id}/open-folder")
        missing = client.post("/api/v1/scenarios/not-a-scenario/open-folder")

    assert response.status_code == 200
    assert response.json() == {"opened": True, "scenario_id": scenario_id}
    assert Path(commands[0][-1]).name == scenario_id
    assert missing.status_code == 404


def test_open_scenario_in_project_sumo_uses_registered_generated_config(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    scenario_id = "sumo-open-test"
    launches: list[tuple[list[str], dict[str, object]]] = []
    monkeypatch.setattr(
        "traffic_platform.api.app.subprocess.Popen",
        lambda command, **kwargs: launches.append((command, kwargs)),
    )
    gui_name = "sumo-gui.exe" if os.name == "nt" else "sumo-gui"
    gui = tmp_path / ".tools" / "sumo" / "bin" / gui_name
    gui.parent.mkdir(parents=True)
    gui.write_bytes(b"test")
    scenario = tmp_path / "scenarios" / "generated" / scenario_id
    scenario.mkdir(parents=True)
    config = scenario / f"{scenario_id}.sumocfg"
    config.write_text("<configuration/>", encoding="utf-8")
    app = create_app(tmp_path)
    app.state.platform.scenarios[scenario_id] = object()

    with TestClient(app) as client:
        response = client.post(f"/api/v1/scenarios/{scenario_id}/open-sumo")
        missing = client.post("/api/v1/scenarios/not-a-scenario/open-sumo")

    assert response.status_code == 200
    assert response.json() == {
        "opened": True,
        "scenario_id": scenario_id,
        "config_file": str(config.resolve()),
    }
    assert launches[0][0] == [str(gui.resolve()), "-c", str(config.resolve())]
    assert launches[0][1]["cwd"] == str(scenario.resolve())
    assert launches[0][1]["env"]["SUMO_HOME"] == str((tmp_path / ".tools" / "sumo").resolve())
    if os.name == "nt":
        assert launches[0][1]["creationflags"] == __import__("subprocess").CREATE_NO_WINDOW
    else:
        assert "creationflags" not in launches[0][1]
    assert missing.status_code == 404


def test_planning_source_draft_api_requires_review_and_accepts_user_count(
    tmp_path: Path,
) -> None:
    app = create_app(tmp_path)
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[0, 50], [100, 50]],
                },
            },
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[50, 0], [50, 100]],
                },
            },
        ],
    }
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/scenario-drafts/planning",
            content=json.dumps(payload).encode(),
            headers={
                "content-type": "application/geo+json",
                "x-file-name": "roads.geojson",
            },
        )
        assert created.status_code == 202
        draft_id = created.json()["id"]
        for _attempt in range(100):
            draft = client.get(f"/api/v1/scenario-drafts/{draft_id}").json()
            if draft["status"] in {"ready", "failed"}:
                break
            time.sleep(0.01)
        assert draft["status"] == "ready"
        assert draft["confidence"] == "high"
        assert len(draft["preview"]["intersections"]) == 1
        intersection_id = draft["preview"]["intersections"][0]["intersection_id"]
        reviewed = client.patch(
            f"/api/v1/scenario-drafts/{draft_id}",
            json={
                "selected_intersection_ids": [intersection_id],
                "review_confirmed": True,
            },
        )
        assert reviewed.status_code == 200
        assert reviewed.json()["validation"]["valid"] is True
        assert reviewed.json()["validation"]["selected_intersection_count"] == 1


def test_osm_source_draft_rejects_invalid_bbox_before_download(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/scenario-drafts/osm",
            json={
                "bbox": {
                    "west": 115.92,
                    "south": 39.05,
                    "east": 115.91,
                    "north": 39.06,
                }
            },
        )
        assert response.status_code == 422


def test_required_rest_paths_and_scenarios() -> None:
    app = create_app()
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").json()["status"] == "ready"
        scenarios = client.get("/api/v1/scenarios").json()["items"]
        assert {
            "official_20_independent",
            "xiongan_rongdong_20",
        }.issubset({item["scenario_id"] for item in scenarios})
        assert all(item["duration_s"] > 0 for item in scenarios)
        assert all(item["seed"] >= 0 for item in scenarios)
        algorithms = client.get("/api/v1/algorithms").json()["items"]
        assert {item["name"] for item in algorithms} == {
            "fixed-time",
            "actuated-control",
            "max-pressure",
            "coordinated-max-pressure",
        }
        intersections = client.get("/api/v1/intersections").json()["items"]
        assert len(intersections) == 20
        scene = client.get("/api/v1/scenes/xiongan_rongdong_20/3d")
        assert scene.status_code == 200
        assert scene.headers["content-type"].startswith("application/json")
        assert scene.headers["cache-control"] == "public, max-age=86400, immutable"
        assert scene.json()["metadata"]["sceneId"] == "xiongan_rongdong_20"
        assert client.get("/api/v1/scenes/official_20_independent/3d").status_code == 404
        assert client.get("/metrics").status_code == 200
        official = next(
            item for item in scenarios if item["scenario_id"] == "official_20_independent"
        )
        connected = next(
            item for item in scenarios if item["scenario_id"] == "xiongan_rongdong_20"
        )
        assert official["runnable"] is False
        assert official["profiles"] == []
        assert {profile["code"] for profile in connected["profiles"]} == {
            "S01",
            "S02",
            "S03",
            "S04",
            "S05",
            "S06",
            "S07",
        }


def test_experiment_lifecycle_contract_before_run() -> None:
    app = create_app()
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/experiments",
            json={
                "scenario_id": "xiongan_rongdong_20",
                "algorithm": "fixed-time",
                "seed": 11,
                "duration_s": 5.0,
                "gui": False,
            },
        )
        assert created.status_code == 201
        experiment_id = created.json()["id"]
        assert client.get(f"/api/v1/experiments/{experiment_id}").json()["request"][
            "profile"
        ] == "BASE"
        assert client.get(
            f"/api/v1/experiments/{experiment_id}/metrics"
        ).json() == {"status": "尚未运行"}
        invalid = client.post(
            "/api/v1/algorithms/max-pressure/validate-config",
            json={"min_green_s": "10"},
        )
        assert invalid.status_code == 422
        assert invalid.json()["error_code"] == "VALIDATION_ERROR"
        assert invalid.json()["trace_id"] == invalid.headers["x-trace-id"]
        missing = client.get("/api/v1/experiments/does-not-exist")
        assert missing.status_code == 404
        assert missing.json()["error_code"] == "RESOURCE_NOT_FOUND"


def test_experiment_accepts_wall_clock_rate_without_changing_request() -> None:
    app = create_app()
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/experiments",
            json={
                "scenario_id": "xiongan_rongdong_20",
                "algorithm": "fixed-time",
                "seed": 12,
                "duration_s": 5.0,
                "gui": False,
            },
        )
        experiment_id = created.json()["id"]
        response = client.post(
            f"/api/v1/experiments/{experiment_id}/rate",
            json={"rate": 4.0},
        )
        assert response.status_code == 200
        assert response.json()["simulation_rate"] == 4.0
        assert app.state.platform.controls[experiment_id].simulation_rate == 4.0
        assert client.post(
            f"/api/v1/experiments/{experiment_id}/rate",
            json={"rate": None},
        ).json()["simulation_rate"] is None


def test_validated_scenario_profile_is_preserved_in_experiment_request() -> None:
    app = create_app()
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/experiments",
            json={
                "scenario_id": "xiongan_rongdong_20",
                "profile": "S04",
                "algorithm": "fixed-time",
                "seed": 11,
                "duration_s": 5.0,
                "gui": False,
            },
        )
        assert created.status_code == 201
        record = client.get(f"/api/v1/experiments/{created.json()['id']}").json()
        assert record["request"]["profile"] == "S04"

        invalid = client.post(
            "/api/v1/experiments",
            json={
                "scenario_id": "xiongan_rongdong_20",
                "profile": "S99",
                "algorithm": "fixed-time",
                "seed": 11,
                "duration_s": 5.0,
                "gui": False,
            },
        )
        assert invalid.status_code == 422
        assert invalid.json()["error_code"] == "VALIDATION_ERROR"


def test_independent_collection_cannot_start_as_regional_network() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/experiments",
            json={
                "scenario_id": "official_20_independent",
                "algorithm": "fixed-time",
                "seed": 11,
                "duration_s": 5.0,
                "gui": False,
            },
        )
        assert response.status_code == 422
        payload = response.json()
        assert payload["error_code"] == "VALIDATION_ERROR"
        assert "independent-intersection collection" in payload["message"]
        assert payload["trace_id"]


def test_realtime_websocket_closes_without_orphan_sender() -> None:
    app = create_app()
    with (
        TestClient(app) as client,
        client.websocket_connect("/ws/v1/realtime") as websocket,
    ):
        assert websocket.receive_json()["status"] == "idle"

    with (
        TestClient(app) as client,
        client.websocket_connect("/ws/v1/digital-twin") as websocket,
    ):
        initial = websocket.receive_json()
        assert initial["type"] == "init"
        assert initial["protocolVersion"] == "1.0"
        assert initial["scene"]["sceneId"] == "xiongan_rongdong_20"
        assert initial["entities"] == {"vehicles": [], "bicycles": [], "pedestrians": []}


def test_live_comparison_contract_locks_fairness_and_exposes_atomic_websocket() -> None:
    app = create_app()
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/live-comparisons",
            json={
                "scenario_id": "xiongan_rongdong_20",
                "baseline_algorithm": "fixed-time",
                "candidate_algorithm": "coordinated-max-pressure",
                "seed": 42,
                "duration_s": 120.0,
                "profile": "BASE",
                "gui": False,
            },
        )
        assert created.status_code == 201
        pair_id = created.json()["id"]
        assert len(created.json()["fairness_fingerprint"]) == 64

        record = client.get(f"/api/v1/live-comparisons/{pair_id}").json()
        assert "result" not in record
        assert "snapshots" not in record
        assert record["request"]["baseline_algorithm"] == "fixed-time"
        assert record["request"]["candidate_algorithm"] == "coordinated-max-pressure"
        assert record["fairness_manifest"]["seed"] == 42
        assert {item["role"] for item in record["fairness_manifest"]["files"]} >= {
            "sumo-config",
            "net-file",
            "route-files",
            "controlled-intersections",
            "scenario-definition",
        }
        paced = client.post(
            f"/api/v1/live-comparisons/{pair_id}/rate",
            json={"rate": 4.0},
        )
        assert paced.json()["simulation_rate"] == 4.0
        controls = app.state.platform.comparison_controls[pair_id]
        assert controls.baseline.simulation_rate == controls.candidate.simulation_rate == 4.0

        with client.websocket_connect("/ws/v1/digital-twin/comparison") as websocket:
            initial = websocket.receive_json()
            assert initial["type"] == "comparison-init"
            assert initial["pairId"] == pair_id
            assert initial["baseline"]["algorithm"] == "fixed-time"
            assert initial["candidate"]["algorithm"] == "coordinated-max-pressure"
            assert initial["fairnessFingerprint"] == created.json()["fairness_fingerprint"]

        conflicting = client.post(
            "/api/v1/experiments",
            json={
                "scenario_id": "xiongan_rongdong_20",
                "algorithm": "fixed-time",
                "seed": 42,
                "duration_s": 5.0,
                "gui": False,
            },
        )
        assert conflicting.status_code == 409

        stopped = client.post(f"/api/v1/live-comparisons/{pair_id}/stop")
        assert stopped.status_code == 200
        assert stopped.json()["status"] == "stopped"

        replacement = client.post(
            "/api/v1/live-comparisons",
            json={
                "baseline_algorithm": "fixed-time",
                "candidate_algorithm": "max-pressure",
                "duration_s": 60.0,
            },
        )
        assert replacement.status_code == 201
        old_record = client.get(f"/api/v1/live-comparisons/{pair_id}").json()
        assert old_record["status"] == "stopped"
        assert old_record["comparison"] is None


def test_live_comparison_remains_starting_until_paired_data_is_ready(
    monkeypatch: MonkeyPatch,
) -> None:
    app = create_app()

    async def wait_for_paired_data(_pair_id: str) -> None:
        return None

    monkeypatch.setattr(
        app.state.platform,
        "start_live_comparison",
        wait_for_paired_data,
    )
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/live-comparisons",
            json={
                "scenario_id": "xiongan_rongdong_20",
                "baseline_algorithm": "fixed-time",
                "candidate_algorithm": "coordinated-max-pressure",
                "duration_s": 60.0,
            },
        )
        pair_id = created.json()["id"]

        started = client.post(f"/api/v1/live-comparisons/{pair_id}/start")
        record = client.get(f"/api/v1/live-comparisons/{pair_id}").json()

        assert started.json()["status"] == "starting"
        assert record["status"] == "starting"
        assert app.state.platform.comparison_twin.status == "starting"


def test_stopping_a_completed_experiment_is_idempotent_and_does_not_block_comparison() -> None:
    app = create_app()
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/experiments",
            json={
                "scenario_id": "xiongan_rongdong_20",
                "algorithm": "fixed-time",
                "duration_s": 60.0,
            },
        )
        assert created.status_code == 201
        experiment_id = created.json()["id"]
        app.state.platform.experiments[experiment_id]["status"] = "completed"

        stopped = client.post(f"/api/v1/experiments/{experiment_id}/stop")

        assert stopped.status_code == 200
        assert stopped.json() == {"id": experiment_id, "status": "completed"}
        comparison = client.post(
            "/api/v1/live-comparisons",
            json={
                "scenario_id": "xiongan_rongdong_20",
                "baseline_algorithm": "fixed-time",
                "candidate_algorithm": "coordinated-max-pressure",
                "duration_s": 60.0,
            },
        )
        assert comparison.status_code == 201


def test_live_comparison_rejects_comparing_an_algorithm_with_itself() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/live-comparisons",
            json={
                "baseline_algorithm": "fixed-time",
                "candidate_algorithm": "fixed-time",
            },
        )

    assert response.status_code == 422
    assert "must be different" in response.json()["message"]


def test_database_outage_does_not_break_experiment_management(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    database_path = tmp_path / "missing-schema.db"
    fallback_path = tmp_path / "storage-fallback.jsonl"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    app = create_app()
    app.state.platform.storage_fallback_path = fallback_path
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/experiments",
            json={
                "scenario_id": "xiongan_rongdong_20",
                "algorithm": "fixed-time",
                "seed": 11,
                "duration_s": 5.0,
                "gui": False,
            },
        )
    assert response.status_code == 201
    assert '"operation": "upsert_experiment"' in fallback_path.read_text(
        encoding="utf-8"
    )


def test_replay_inventory_reports_terminal_duration_and_download(tmp_path: Path) -> None:
    replay_path = tmp_path / "results" / "exp-replay" / "digital_twin.replay.ndjson"
    replay_path.parent.mkdir(parents=True)
    frames = [
        {
            "type": "init",
            "sequence": 8,
            "scenarioId": "xiongan_rongdong_20",
            "simulationTimeS": 1.0,
            "status": "running",
        },
        {"type": "delta", "sequence": 9, "simulationTimeS": 2.0},
        {
            "type": "init",
            "sequence": 10,
            "simulationTimeS": 60.0,
            "status": "completed",
        },
    ]
    replay_path.write_text(
        "\n".join(json.dumps(frame) for frame in frames) + "\n",
        encoding="utf-8",
    )
    (replay_path.parent / "result.json").write_text(
        json.dumps(
            {
                "actual_run": True,
                "algorithm": "fixed-time",
                "scenario_profile": "BASE",
                "seed": 42,
                "metrics": {"mean_speed_m_s": 4.2},
                "samples": [{"simulation_time_s": index} for index in range(20_000)],
            }
        ),
        encoding="utf-8",
    )
    app = create_app(tmp_path)
    with TestClient(app) as client:
        item = client.get("/api/v1/replays").json()["items"][0]
        assert item["simulationTimeS"] == 60.0
        assert item["status"] == "completed"
        assert item["frameCount"] == 3
        assert item["algorithm"] == "fixed-time"
        assert item["profile"] == "BASE"
        assert item["seed"] == 42
        assert item["summaryMetrics"]["mean_speed_m_s"] == 4.2
        assert item["actualRun"] is True
        assert item["createdAt"]
        response = client.get("/api/v1/replays/exp-replay")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/x-ndjson")
        assert client.get("/api/v1/replays/../escape").status_code == 404


def test_experiment_evidence_returns_bounded_real_trace(tmp_path: Path) -> None:
    result_path = tmp_path / "results" / "exp-evidence" / "result.json"
    result_path.parent.mkdir(parents=True)
    result_path.write_text(
        json.dumps(
            {
                "experiment_id": "exp-evidence",
                "scenario_id": "xiongan_rongdong_20",
                "algorithm": "coordinated-max-pressure",
                "scenario_profile": "BASE",
                "seed": 11,
                "actual_run": True,
                "metrics": {"prediction_ready_ratio": 0.8},
                "samples": [
                    {
                        "simulation_time_s": float(index),
                        "intersection_queue_vehicles": {"J1": index, "J2": 1},
                        "core_corridor_queue_vehicles": index,
                        "mean_speed_m_s": 8.0,
                        "prediction_status": "ready",
                        "prediction_model_id": "online-graph-rls-v1",
                        "prediction_horizon_s": 60,
                        "prediction_confidence": 0.8,
                        "predicted_queue_vehicles": index + 2,
                        "predicted_spillback_risk": 0.1,
                        "signal_action_rejected_count": 0,
                    }
                    for index in range(500)
                ],
            }
        ),
        encoding="utf-8",
    )
    app = create_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/api/v1/experiments/exp-evidence/evidence")
        assert response.status_code == 200
        payload = response.json()
        assert payload["actual_run"] is True
        assert payload["source_sample_count"] == 500
        assert len(payload["series"]) <= 361
        assert payload["series"][0]["controlled_queue_vehicles"] == 1.0
        assert payload["series"][-1]["simulation_time_s"] == 499.0
        assert client.get("/api/v1/experiments/../escape/evidence").status_code == 404
