"""Strict S01-S07 scenario profile overlays."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from traffic_platform.scenario_engine.models import Disturbance


class ProfileDisturbance(BaseModel):
    """One profile-level disturbance overlay."""

    model_config = ConfigDict(strict=True, extra="forbid")

    type: Literal[
        "event_dispersal",
        "roadwork",
        "incident",
        "emergency_vehicle",
        "cloud_offline",
    ]
    start_s: float = Field(ge=0)
    duration_s: float = Field(gt=0)
    target: str
    multiplier: float | None = Field(default=None, gt=0)


class ScenarioProfile(BaseModel):
    """One named benchmark/demo profile."""

    model_config = ConfigDict(strict=True, extra="forbid")

    code: Literal["S01", "S02", "S03", "S04", "S05", "S06", "S07"]
    name: str
    flow_multiplier: float = Field(gt=0)
    connected_vehicle_penetration: float = Field(ge=0, le=1)
    communication_profile: Literal[
        "N0", "N1", "N2", "N3", "N4", "N5", "N6", "N7", "N8"
    ]
    disturbances: list[ProfileDisturbance]

    def physical_disturbances(self) -> list[Disturbance]:
        """Convert only SUMO-side profile events into the runtime contract."""

        result: list[Disturbance] = []
        for index, item in enumerate(self.disturbances):
            if item.type == "cloud_offline":
                continue
            parameters: dict[str, float | str | bool] = {}
            if item.multiplier is not None:
                parameters["flow_multiplier"] = item.multiplier
            result.append(
                Disturbance(
                    event_id=(
                        f"{self.code.lower()}_{item.type}_{int(item.start_s)}_{index}"
                    ),
                    type=item.type,
                    simulation_time_s=item.start_s,
                    duration_s=item.duration_s,
                    target=item.target,
                    parameters=parameters,
                )
            )
        return result

    def cloud_outage_window(self) -> tuple[float, float] | None:
        """Return the validated cloud outage encoded by this profile, if any."""

        outage = next(
            (item for item in self.disturbances if item.type == "cloud_offline"),
            None,
        )
        return None if outage is None else (outage.start_s, outage.duration_s)


class ScenarioProfileSet(BaseModel):
    """Complete profile set required by Phase 1."""

    model_config = ConfigDict(strict=True, extra="forbid")

    schema_version: str = Field(pattern=r"^\d+\.\d+$")
    base_scenario_id: str
    profiles: list[ScenarioProfile]

    @model_validator(mode="after")
    def require_all_profiles(self) -> "ScenarioProfileSet":
        """Reject missing or duplicate S01-S07 definitions."""

        codes = [profile.code for profile in self.profiles]
        expected = {f"S{index:02d}" for index in range(1, 8)}
        if set(codes) != expected or len(codes) != len(expected):
            raise ValueError("profiles must define S01 through S07 exactly once")
        return self

    @classmethod
    def from_yaml(cls, path: Path) -> "ScenarioProfileSet":
        """Load a UTF-8 profile overlay document."""

        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))

    def get(self, code: str) -> ScenarioProfile:
        """Return one validated profile by code."""

        for profile in self.profiles:
            if profile.code == code:
                return profile
        raise KeyError(code)
