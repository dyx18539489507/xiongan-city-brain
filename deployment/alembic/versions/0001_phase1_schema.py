"""Create Phase 1 experiment, metric and event tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_phase1"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the initial platform schema."""

    op.create_table(
        "experiments",
        sa.Column("id", sa.String(length=96), nullable=False),
        sa.Column("scenario_id", sa.String(length=96), nullable=False),
        sa.Column("algorithm", sa.String(length=96), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_experiments_scenario_id", "experiments", ["scenario_id"])
    op.create_index("ix_experiments_algorithm", "experiments", ["algorithm"])
    op.create_index("ix_experiments_status", "experiments", ["status"])
    for table_name, value_column in (
        ("metric_samples", sa.Column("values", sa.JSON(), nullable=False)),
        ("events", sa.Column("payload", sa.JSON(), nullable=False)),
    ):
        columns: list[sa.Column[object]] = [
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("experiment_id", sa.String(length=96), nullable=False),
            sa.Column("simulation_time_s", sa.Float(), nullable=False),
        ]
        if table_name == "events":
            columns.append(sa.Column("event_type", sa.String(length=96), nullable=False))
        columns.extend(
            [
                value_column,
                sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
                sa.ForeignKeyConstraint(
                    ["experiment_id"],
                    ["experiments.id"],
                    ondelete="CASCADE",
                ),
                sa.PrimaryKeyConstraint("id"),
            ]
        )
        op.create_table(table_name, *columns)
        op.create_index(
            f"ix_{table_name}_experiment_id",
            table_name,
            ["experiment_id"],
        )
        op.create_index(
            f"ix_{table_name}_simulation_time_s",
            table_name,
            ["simulation_time_s"],
        )
    op.create_index("ix_events_event_type", "events", ["event_type"])


def downgrade() -> None:
    """Remove the complete Phase 1 schema."""

    op.drop_table("events")
    op.drop_table("metric_samples")
    op.drop_table("experiments")
