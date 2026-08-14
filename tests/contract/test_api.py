"""FastAPI paths, strict requests and actual scenario inventory."""

import json
from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from traffic_platform.api.app import create_app


def test_required_rest_paths_and_scenarios() -> None:
    app = create_app()
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").json()["status"] == "ready"
        scenarios = client.get("/api/v1/scenarios").json()["items"]
        assert {item["scenario_id"] for item in scenarios} == {
            "official_20_independent",
            "xiongan_rongdong_20",
        }
        algorithms = client.get("/api/v1/algorithms").json()["items"]
        assert len(algorithms) == 5
        intersections = client.get("/api/v1/intersections").json()["items"]
        assert len(intersections) == 20
        scene = client.get("/api/v1/scenes/xiongan_rongdong_20/3d")
        assert scene.status_code == 200
        assert scene.headers["content-type"].startswith("application/json")
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
            "scenarioId": "xiongan_rongdong_20",
            "simulationTimeS": 1.0,
            "status": "running",
        },
        {"type": "delta", "simulationTimeS": 2.0},
        {"type": "init", "simulationTimeS": 60.0, "status": "completed"},
    ]
    replay_path.write_text(
        "\n".join(json.dumps(frame) for frame in frames) + "\n",
        encoding="utf-8",
    )
    app = create_app(tmp_path)
    with TestClient(app) as client:
        item = client.get("/api/v1/replays").json()["items"][0]
        assert item["simulationTimeS"] == 60.0
        assert item["status"] == "completed"
        assert item["frameCount"] == 3
        response = client.get("/api/v1/replays/exp-replay")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/x-ndjson")
        assert client.get("/api/v1/replays/../escape").status_code == 404
