"""Enable TimescaleDB hypertables, columnstore and retention policies.

This migration preserves existing rows by copying them into newly-created
hypertables.  Operators must still take a database backup before applying it to
an existing deployment because the conversion takes table locks.
"""

from __future__ import annotations

import os
from collections.abc import Sequence

from alembic import op

revision: str = "0003_timescaledb"
down_revision: str | Sequence[str] | None = "0002_trajectory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _days(name: str, default: int) -> int:
    value = int(os.environ.get(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _create_hypertable(
    table: str,
    *,
    columns_sql: str,
    copy_columns: str,
    chunk_interval: str,
    columnstore_after_days: int,
    retention_days: int,
) -> None:
    legacy = f"_{table}_pre_timescale"
    op.execute(f'ALTER TABLE "{table}" RENAME TO "{legacy}"')
    op.execute(
        f"""
        CREATE TABLE "{table}" ({columns_sql})
        WITH (
            tsdb.hypertable,
            tsdb.partition_column='created_at',
            tsdb.chunk_interval='{chunk_interval}',
            tsdb.segmentby='experiment_id',
            tsdb.orderby='created_at DESC'
        )
        """
    )
    op.execute(
        f'INSERT INTO "{table}" ({copy_columns}) '
        f'SELECT {copy_columns} FROM "{legacy}"'
    )
    op.execute(f'DROP TABLE "{legacy}"')
    op.execute(
        f'CREATE INDEX "ix_{table}_experiment_created_at" '
        f'ON "{table}" (experiment_id, created_at DESC)'
    )
    op.execute(
        f"CALL add_columnstore_policy('{table}', "
        f"after => INTERVAL '{columnstore_after_days} days', "
        "if_not_exists => TRUE)"
    )
    op.execute(
        f"SELECT add_retention_policy('{table}', "
        f"INTERVAL '{retention_days} days', if_not_exists => TRUE)"
    )


def upgrade() -> None:
    """Convert sampled runtime tables to policy-managed hypertables."""

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    metric_retention = _days("METRIC_RETENTION_DAYS", 30)
    trajectory_retention = _days("TRAJECTORY_RETENTION_DAYS", 14)
    event_retention = _days("EVENT_RETENTION_DAYS", 180)
    metric_columnstore = _days("METRIC_COLUMNSTORE_AFTER_DAYS", 7)
    trajectory_columnstore = _days("TRAJECTORY_COLUMNSTORE_AFTER_DAYS", 2)
    event_columnstore = _days("EVENT_COLUMNSTORE_AFTER_DAYS", 30)
    if metric_columnstore >= metric_retention:
        raise ValueError("metric columnstore age must be below retention age")
    if trajectory_columnstore >= trajectory_retention:
        raise ValueError("trajectory columnstore age must be below retention age")
    if event_columnstore >= event_retention:
        raise ValueError("event columnstore age must be below retention age")

    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    op.execute("LOCK TABLE experiments IN SHARE ROW EXCLUSIVE MODE")
    _create_hypertable(
        "metric_samples",
        columns_sql="""
            id VARCHAR(36) NOT NULL,
            experiment_id VARCHAR(96) NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
            simulation_time_s DOUBLE PRECISION NOT NULL,
            values JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (id, created_at)
        """,
        copy_columns="id, experiment_id, simulation_time_s, values, created_at",
        chunk_interval="1 day",
        columnstore_after_days=metric_columnstore,
        retention_days=metric_retention,
    )
    _create_hypertable(
        "events",
        columns_sql="""
            id VARCHAR(36) NOT NULL,
            experiment_id VARCHAR(96) NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
            simulation_time_s DOUBLE PRECISION NOT NULL,
            event_type VARCHAR(96) NOT NULL,
            payload JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (id, created_at)
        """,
        copy_columns="id, experiment_id, simulation_time_s, event_type, payload, created_at",
        chunk_interval="7 days",
        columnstore_after_days=event_columnstore,
        retention_days=event_retention,
    )
    op.execute("CREATE INDEX ix_events_event_type ON events (event_type)")
    _create_hypertable(
        "vehicle_trajectory_batches",
        columns_sql="""
            id VARCHAR(36) NOT NULL,
            experiment_id VARCHAR(96) NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
            simulation_time_s DOUBLE PRECISION NOT NULL,
            vehicle_count INTEGER NOT NULL,
            samples JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (id, created_at)
        """,
        copy_columns="id, experiment_id, simulation_time_s, vehicle_count, samples, created_at",
        chunk_interval="1 day",
        columnstore_after_days=trajectory_columnstore,
        retention_days=trajectory_retention,
    )


def _restore_regular_table(
    table: str,
    *,
    columns_sql: str,
    copy_columns: str,
) -> None:
    regular = f"_{table}_regular"
    op.execute(f'CREATE TABLE "{regular}" ({columns_sql})')
    op.execute(
        f'INSERT INTO "{regular}" ({copy_columns}) '
        f'SELECT {copy_columns} FROM "{table}"'
    )
    op.execute(f'DROP TABLE "{table}"')
    op.execute(f'ALTER TABLE "{regular}" RENAME TO "{table}"')
    op.execute(
        f'CREATE INDEX "ix_{table}_experiment_id" ON "{table}" (experiment_id)'
    )
    op.execute(
        f'CREATE INDEX "ix_{table}_simulation_time_s" '
        f'ON "{table}" (simulation_time_s)'
    )


def downgrade() -> None:
    """Copy hypertable rows back into ordinary PostgreSQL tables."""

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for table in ("metric_samples", "events", "vehicle_trajectory_batches"):
        op.execute(
            f"CALL remove_columnstore_policy('{table}', if_exists => TRUE)"
        )
        op.execute(
            f"SELECT remove_retention_policy('{table}', if_exists => TRUE)"
        )
    _restore_regular_table(
        "metric_samples",
        columns_sql="""
            id VARCHAR(36) PRIMARY KEY,
            experiment_id VARCHAR(96) NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
            simulation_time_s DOUBLE PRECISION NOT NULL,
            values JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL
        """,
        copy_columns="id, experiment_id, simulation_time_s, values, created_at",
    )
    _restore_regular_table(
        "events",
        columns_sql="""
            id VARCHAR(36) PRIMARY KEY,
            experiment_id VARCHAR(96) NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
            simulation_time_s DOUBLE PRECISION NOT NULL,
            event_type VARCHAR(96) NOT NULL,
            payload JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL
        """,
        copy_columns="id, experiment_id, simulation_time_s, event_type, payload, created_at",
    )
    op.execute("CREATE INDEX ix_events_event_type ON events (event_type)")
    _restore_regular_table(
        "vehicle_trajectory_batches",
        columns_sql="""
            id VARCHAR(36) PRIMARY KEY,
            experiment_id VARCHAR(96) NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
            simulation_time_s DOUBLE PRECISION NOT NULL,
            vehicle_count INTEGER NOT NULL,
            samples JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL
        """,
        copy_columns="id, experiment_id, simulation_time_s, vehicle_count, samples, created_at",
    )
    op.execute(
        "CREATE INDEX ix_vehicle_trajectory_batches_created_at "
        "ON vehicle_trajectory_batches (created_at)"
    )
