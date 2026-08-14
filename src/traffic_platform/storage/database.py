"""SQLAlchemy 2 persistence schema and batch sink."""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    create_engine,
    delete,
    select,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from traffic_platform.storage.buffer import WriteItem


class Base(DeclarativeBase):
    """Declarative persistence base."""


class ExperimentRecord(Base):
    """One immutable experiment execution identity."""

    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    scenario_id: Mapped[str] = mapped_column(String(96), index=True)
    algorithm: Mapped[str] = mapped_column(String(96), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )


class MetricRecord(Base):
    """Sampled experiment metric row, intended for batched inserts."""

    __tablename__ = "metric_samples"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"),
        index=True,
    )
    simulation_time_s: Mapped[float] = mapped_column(Float, index=True)
    values: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        primary_key=True,
        default=lambda: datetime.now(UTC),
    )


class EventRecord(Base):
    """Control, communication, safety or disturbance event."""

    __tablename__ = "events"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"),
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(96), index=True)
    simulation_time_s: Mapped[float] = mapped_column(Float, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        primary_key=True,
        default=lambda: datetime.now(UTC),
    )


class VehicleTrajectoryBatchRecord(Base):
    """One sampled vehicle batch, avoiding per-vehicle synchronous writes."""

    __tablename__ = "vehicle_trajectory_batches"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"),
        index=True,
    )
    simulation_time_s: Mapped[float] = mapped_column(Float, index=True)
    vehicle_count: Mapped[int] = mapped_column(Integer)
    samples: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        primary_key=True,
        default=lambda: datetime.now(UTC),
        index=True,
    )


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    """Configurable retention windows for volume-controlled runtime data."""

    metric_days: int = 30
    trajectory_days: int = 14
    event_days: int = 180

    def __post_init__(self) -> None:
        if min(self.metric_days, self.trajectory_days, self.event_days) <= 0:
            raise ValueError("retention days must be positive")


class SqlAlchemyBatchSink:
    """Insert homogeneous buffered rows in one SQLAlchemy transaction."""

    def __init__(self, database_url: str) -> None:
        self._engine = create_engine(database_url, pool_pre_ping=True)
        self._session_factory = sessionmaker(self._engine, expire_on_commit=False)

    def create_schema(self) -> None:
        """Create local development tables; production uses Alembic."""

        Base.metadata.create_all(self._engine)

    async def __call__(self, items: list[WriteItem]) -> None:
        """Persist one batch without blocking the asyncio control loop."""

        await asyncio.to_thread(self._write_sync, items)

    async def upsert_experiment(
        self,
        experiment_id: str,
        *,
        scenario_id: str,
        algorithm: str,
        status: str,
        parameters: dict[str, Any],
    ) -> None:
        """Create or update one experiment identity outside the sample buffer."""

        await asyncio.to_thread(
            self._upsert_experiment_sync,
            experiment_id,
            scenario_id,
            algorithm,
            status,
            parameters,
        )

    async def update_experiment_status(
        self,
        experiment_id: str,
        status: str,
    ) -> None:
        """Persist a lifecycle transition without blocking the event loop."""

        await asyncio.to_thread(
            self._update_experiment_status_sync,
            experiment_id,
            status,
        )

    async def apply_retention(
        self,
        policy: RetentionPolicy,
        *,
        now: datetime | None = None,
    ) -> dict[str, int]:
        """Delete expired sampled data while retaining experiment identities."""

        if await asyncio.to_thread(self._timescale_enabled_sync):
            return {
                MetricRecord.__tablename__: 0,
                VehicleTrajectoryBatchRecord.__tablename__: 0,
                EventRecord.__tablename__: 0,
            }
        return await asyncio.to_thread(
            self._apply_retention_sync,
            policy,
            now or datetime.now(UTC),
        )

    async def timescale_status(self) -> dict[str, Any]:
        """Return extension, hypertable and policy evidence for readiness."""

        return await asyncio.to_thread(self._timescale_status_sync)

    def close(self) -> None:
        """Release the SQLAlchemy connection pool."""

        self._engine.dispose()

    def _write_sync(self, items: list[WriteItem]) -> None:
        rows: list[MetricRecord | EventRecord | VehicleTrajectoryBatchRecord] = []
        for item in items:
            if item.kind == "metric":
                rows.append(
                    MetricRecord(
                        experiment_id=str(item.payload["experiment_id"]),
                        simulation_time_s=float(item.payload["simulation_time_s"]),
                        values=dict(item.payload["values"]),
                    )
                )
            elif item.kind == "event":
                rows.append(
                    EventRecord(
                        experiment_id=str(item.payload["experiment_id"]),
                        event_type=str(item.payload["event_type"]),
                        simulation_time_s=float(item.payload["simulation_time_s"]),
                        payload=dict(item.payload.get("payload", {})),
                    )
                )
            elif item.kind == "trajectory":
                samples = item.payload.get("samples", [])
                if not isinstance(samples, list):
                    raise TypeError("trajectory samples must be a list")
                rows.append(
                    VehicleTrajectoryBatchRecord(
                        experiment_id=str(item.payload["experiment_id"]),
                        simulation_time_s=float(item.payload["simulation_time_s"]),
                        vehicle_count=len(samples),
                        samples=samples,
                    )
                )
        if not rows:
            return
        with self._session_factory.begin() as session:
            session.add_all(rows)

    def _timescale_enabled_sync(self) -> bool:
        if self._engine.dialect.name != "postgresql":
            return False
        with self._engine.connect() as connection:
            return connection.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_extension "
                    "WHERE extname = 'timescaledb')"
                )
            ) is True

    def _timescale_status_sync(self) -> dict[str, Any]:
        if self._engine.dialect.name != "postgresql":
            return {
                "provider": self._engine.dialect.name,
                "enabled": False,
                "hypertables": [],
                "policy_count": 0,
            }
        with self._engine.connect() as connection:
            version = connection.scalar(
                text(
                    "SELECT extversion FROM pg_extension "
                    "WHERE extname = 'timescaledb'"
                )
            )
            if version is None:
                return {
                    "provider": "postgresql",
                    "enabled": False,
                    "hypertables": [],
                    "policy_count": 0,
                }
            hypertables = list(
                connection.scalars(
                    text(
                        "SELECT hypertable_name FROM "
                        "timescaledb_information.hypertables "
                        "WHERE hypertable_schema = 'public' "
                        "ORDER BY hypertable_name"
                    )
                )
            )
            policy_count = int(
                connection.scalar(
                    text(
                        "SELECT COUNT(*) FROM timescaledb_information.jobs "
                        "WHERE hypertable_schema = 'public' AND proc_name IN "
                        "('policy_compression', 'policy_retention')"
                    )
                )
                or 0
            )
            required = {
                "events",
                "metric_samples",
                "vehicle_trajectory_batches",
            }
            return {
                "provider": "timescaledb",
                "enabled": required <= set(hypertables),
                "extension_version": str(version),
                "hypertables": hypertables,
                "policy_count": policy_count,
            }

    def _upsert_experiment_sync(
        self,
        experiment_id: str,
        scenario_id: str,
        algorithm: str,
        status: str,
        parameters: dict[str, Any],
    ) -> None:
        with self._session_factory.begin() as session:
            record = session.scalar(
                select(ExperimentRecord).where(
                    ExperimentRecord.id == experiment_id
                )
            )
            if record is None:
                session.add(
                    ExperimentRecord(
                        id=experiment_id,
                        scenario_id=scenario_id,
                        algorithm=algorithm,
                        status=status,
                        parameters=parameters,
                    )
                )
                return
            record.status = status
            record.parameters = parameters

    def _update_experiment_status_sync(
        self,
        experiment_id: str,
        status: str,
    ) -> None:
        with self._session_factory.begin() as session:
            record = session.scalar(
                select(ExperimentRecord).where(
                    ExperimentRecord.id == experiment_id
                )
            )
            if record is not None:
                record.status = status

    def _apply_retention_sync(
        self,
        policy: RetentionPolicy,
        now: datetime,
    ) -> dict[str, int]:
        statements = (
            (
                MetricRecord.__tablename__,
                delete(MetricRecord).where(
                    MetricRecord.created_at
                    < now - timedelta(days=policy.metric_days)
                ),
            ),
            (
                VehicleTrajectoryBatchRecord.__tablename__,
                delete(VehicleTrajectoryBatchRecord).where(
                    VehicleTrajectoryBatchRecord.created_at
                    < now - timedelta(days=policy.trajectory_days)
                ),
            ),
            (
                EventRecord.__tablename__,
                delete(EventRecord).where(
                    EventRecord.created_at
                    < now - timedelta(days=policy.event_days)
                ),
            ),
        )
        deleted: dict[str, int] = {}
        with self._session_factory.begin() as session:
            for table_name, statement in statements:
                result = session.execute(statement)
                deleted[table_name] = int(
                    getattr(result, "rowcount", 0) or 0
                )
        return deleted
