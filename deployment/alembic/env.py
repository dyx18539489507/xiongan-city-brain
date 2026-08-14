"""Alembic migration environment."""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from traffic_platform.storage.database import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def _database_url() -> str:
    """Resolve the migration URL from deployment environment variables."""

    configured = os.getenv("DATABASE_URL")
    if configured:
        return configured
    host = os.getenv("POSTGRES_HOST")
    if not host:
        return config.get_main_option("sqlalchemy.url")
    port = os.getenv("POSTGRES_PORT", "5432")
    database = os.getenv("POSTGRES_DB", "traffic_platform")
    username = os.getenv("POSTGRES_USER", "traffic_platform")
    password = os.getenv("POSTGRES_PASSWORD", "change-me")
    return f"postgresql+psycopg://{username}:{password}@{host}:{port}/{database}"


config.set_main_option("sqlalchemy.url", _database_url().replace("%", "%%"))


def run_migrations_offline() -> None:
    """Generate SQL without establishing a database connection."""

    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in one transaction against the configured database."""

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
