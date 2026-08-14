"""Application settings loaded exclusively from environment variables."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Shared service configuration without embedded infrastructure secrets."""

    model_config = SettingsConfigDict(
        env_prefix="TRAFFIC_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = Field(default=8000, ge=1, le=65535)
    mqtt_host: str = "localhost"
    mqtt_port: int = Field(default=1883, ge=1, le=65535)
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    database_url: str = "sqlite:///runtime/traffic.db"
    redis_url: str = "redis://localhost:6379/0"
    sumo_binary: str = "sumo"
    scenario_root: str = "scenarios/generated"
    result_root: str = "results"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return one validated settings instance per process."""

    return Settings()

