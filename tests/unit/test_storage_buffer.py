"""Tests for tiered batching, backpressure and fallback behavior."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from traffic_platform.storage import (
    BufferedBatchWriter,
    DataPriority,
    RetentionPolicy,
    SqlAlchemyBatchSink,
    WriteItem,
)


async def test_buffer_batches_and_flushes_on_close() -> None:
    batches: list[list[WriteItem]] = []

    async def sink(items: list[WriteItem]) -> None:
        batches.append(items)

    writer = BufferedBatchWriter(sink, batch_size=2, max_items=4, flush_interval_s=10)
    await writer.start()
    await writer.submit(WriteItem("metric", {"value": 1}, DataPriority.METRIC))
    await writer.submit(WriteItem("event", {"value": 2}, DataPriority.EVENT))
    await writer.close()
    assert sum(len(batch) for batch in batches) == 2
    assert len(writer.write_latencies_ms) == 1


async def test_database_failure_falls_back_to_jsonl(tmp_path: Path) -> None:
    async def unavailable(_: list[WriteItem]) -> None:
        raise ConnectionError("database unavailable")

    fallback = tmp_path / "degraded" / "events.jsonl"
    writer = BufferedBatchWriter(
        unavailable,
        batch_size=1,
        max_items=2,
        fallback_path=fallback,
    )
    await writer.submit(WriteItem("event", {"critical": True}, DataPriority.EVENT))
    await writer.close()
    assert writer.fallback_batches == 1
    assert '"critical": true' in fallback.read_text(encoding="utf-8")


async def test_sqlalchemy_sink_persists_experiment_metrics_and_events(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "phase1.db"
    sink = SqlAlchemyBatchSink(f"sqlite:///{database_path.as_posix()}")
    sink.create_schema()
    timescale = await sink.timescale_status()
    assert timescale == {
        "provider": "sqlite",
        "enabled": False,
        "hypertables": [],
        "policy_count": 0,
    }
    await sink.upsert_experiment(
        "exp-storage-test",
        scenario_id="xiongan_rongdong_20",
        algorithm="actuated-control",
        status="created",
        parameters={"seed": 11},
    )
    writer = BufferedBatchWriter(sink, batch_size=2, max_items=10)
    await writer.start()
    await writer.submit(
        WriteItem(
            "metric",
            {
                "experiment_id": "exp-storage-test",
                "simulation_time_s": 1.0,
                "values": {"mean_speed_m_s": 8.5},
            },
            DataPriority.METRIC,
        )
    )
    await writer.submit(
        WriteItem(
            "event",
            {
                "experiment_id": "exp-storage-test",
                "event_type": "EDGE_STATE_PUBLISHED",
                "simulation_time_s": 1.0,
                "payload": {"trace_id": "trace-storage-test"},
            },
            DataPriority.EVENT,
        )
    )
    await writer.submit(
        WriteItem(
            "trajectory",
            {
                "experiment_id": "exp-storage-test",
                "simulation_time_s": 1.0,
                "samples": [
                    {
                        "vehicle_id": "veh-1",
                        "speed_m_s": 8.0,
                    }
                ],
            },
            DataPriority.TRAJECTORY,
        )
    )
    await writer.close()
    await sink.update_experiment_status("exp-storage-test", "completed")

    with sqlite3.connect(database_path) as connection:
        status = connection.execute(
            "SELECT status FROM experiments WHERE id = ?",
            ("exp-storage-test",),
        ).fetchone()
        metric_count = connection.execute(
            "SELECT COUNT(*) FROM metric_samples WHERE experiment_id = ?",
            ("exp-storage-test",),
        ).fetchone()
        event_count = connection.execute(
            "SELECT COUNT(*) FROM events WHERE experiment_id = ?",
            ("exp-storage-test",),
        ).fetchone()
        trajectory = connection.execute(
            """
            SELECT vehicle_count
            FROM vehicle_trajectory_batches
            WHERE experiment_id = ?
            """,
            ("exp-storage-test",),
        ).fetchone()
        connection.execute(
            """
            UPDATE vehicle_trajectory_batches
            SET created_at = '2020-01-01 00:00:00'
            WHERE experiment_id = ?
            """,
            ("exp-storage-test",),
        )
        connection.commit()
    deleted = await sink.apply_retention(
        RetentionPolicy(metric_days=30, trajectory_days=1, event_days=180),
        now=datetime.now(UTC),
    )
    sink.close()

    assert status == ("completed",)
    assert metric_count == (1,)
    assert event_count == (1,)
    assert trajectory == (1,)
    assert deleted["vehicle_trajectory_batches"] == 1
