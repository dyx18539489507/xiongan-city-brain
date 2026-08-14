"""Add batched vehicle trajectory storage for tiered sampling."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_trajectory"
down_revision: str | Sequence[str] | None = "0001_phase1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create one row per sampled vehicle batch, not per vehicle."""

    op.create_table(
        "vehicle_trajectory_batches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("experiment_id", sa.String(length=96), nullable=False),
        sa.Column("simulation_time_s", sa.Float(), nullable=False),
        sa.Column("vehicle_count", sa.Integer(), nullable=False),
        sa.Column("samples", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["experiment_id"],
            ["experiments.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_vehicle_trajectory_batches_experiment_id",
        "vehicle_trajectory_batches",
        ["experiment_id"],
    )
    op.create_index(
        "ix_vehicle_trajectory_batches_simulation_time_s",
        "vehicle_trajectory_batches",
        ["simulation_time_s"],
    )
    op.create_index(
        "ix_vehicle_trajectory_batches_created_at",
        "vehicle_trajectory_batches",
        ["created_at"],
    )


def downgrade() -> None:
    """Remove batched trajectory storage."""

    op.drop_table("vehicle_trajectory_batches")
