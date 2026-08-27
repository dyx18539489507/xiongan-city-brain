import json
from pathlib import Path

from traffic_platform.api.app import PlatformState


def _state(workspace: Path) -> PlatformState:
    state = PlatformState.__new__(PlatformState)
    state.workspace = workspace
    return state


def test_loads_independent_runner_progress(tmp_path: Path) -> None:
    output_dir = tmp_path / "results" / "benchmarks" / "benchmark-formal"
    output_dir.mkdir(parents=True)
    (output_dir / "runner-status.json").write_text(
        json.dumps(
            {
                "id": "benchmark-formal",
                "status": "running",
                "started_at": "2026-08-27T05:13:55+00:00",
                "algorithms": ["fixed-time", "coordinated-max-pressure"],
                "seeds": [11, 23],
                "duration_s": 1800,
                "warmup_s": 600,
                "completed_runs": 2,
                "total_runs": 4,
                "progress": 50,
                "message": "Completed 2/4",
                "error": None,
            }
        ),
        encoding="utf-8",
    )

    record = _state(tmp_path)._load_benchmarks()["benchmark-formal"]

    assert record["status"] == "running"
    assert record["progress"] == 50
    assert record["completed_runs"] == 2
    assert record["request"].duration_s == 1800
    assert record["request"].warmup_s == 600
    assert record["result"] is None


def test_completed_matrix_takes_priority_over_runner_status(tmp_path: Path) -> None:
    output_dir = tmp_path / "results" / "benchmarks" / "benchmark-formal"
    output_dir.mkdir(parents=True)
    (output_dir / "runner-status.json").write_text(
        json.dumps(
            {
                "status": "running",
                "algorithms": ["fixed-time", "coordinated-max-pressure"],
                "seeds": [11],
                "duration_s": 300,
                "completed_runs": 1,
                "total_runs": 2,
                "progress": 50,
            }
        ),
        encoding="utf-8",
    )
    matrix = {
        "actual_run": True,
        "algorithms": ["fixed-time", "coordinated-max-pressure"],
        "seeds": [11],
        "duration_s": 300,
        "warmup_s": 600,
        "rows": [{"algorithm": "fixed-time"}, {"algorithm": "coordinated-max-pressure"}],
    }
    (output_dir / "benchmark.json").write_text(json.dumps(matrix), encoding="utf-8")

    record = _state(tmp_path)._load_benchmarks()["benchmark-formal"]

    assert record["status"] == "completed"
    assert record["progress"] == 100
    assert record["completed_runs"] == 2
    assert record["result"] == matrix
