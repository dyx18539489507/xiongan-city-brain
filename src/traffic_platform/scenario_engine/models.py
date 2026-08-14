"""Strict YAML scenario configuration models."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ScenarioModel(BaseModel):
    """Strict base model for scenario configuration."""

    model_config = ConfigDict(strict=True, extra="forbid", validate_assignment=True)


class SimulationConfig(ScenarioModel):
    """SUMO time and repeatability settings."""

    duration_s: float = Field(gt=0)
    step_length_s: float = Field(gt=0)
    seed: int = Field(ge=0)
    gui: bool = False


class OdDemand(ScenarioModel):
    """One configurable OD demand group."""

    origin_zone: str
    destination_zone: str
    flow_veh_h: float = Field(ge=0)
    begin_s: float = Field(ge=0)
    end_s: float = Field(gt=0)
    route_alternatives: bool = True
    route_scope: Literal["complete_network", "controlled_corridor"] = "complete_network"

    @model_validator(mode="after")
    def validate_window(self) -> "OdDemand":
        """Ensure demand ends after it begins."""

        if self.end_s <= self.begin_s:
            raise ValueError("OD demand end_s must be greater than begin_s")
        return self


class Disturbance(ScenarioModel):
    """Scheduled road, incident, event or emergency disturbance."""

    event_id: str
    type: Literal["roadwork", "incident", "event_dispersal", "emergency_vehicle"]
    simulation_time_s: float = Field(ge=0)
    duration_s: float = Field(gt=0)
    target: str
    parameters: dict[str, float | str | bool] = Field(default_factory=dict)


class CommunicationConfig(ScenarioModel):
    """Named and overrideable communication condition."""

    profile: str
    cloud_edge: dict[str, float | str | bool] = Field(default_factory=dict)
    edge_vehicle: dict[str, float | str | bool] = Field(default_factory=dict)


class AlgorithmSelection(ScenarioModel):
    """Algorithm plugin and validated parameter map."""

    name: str
    parameters: dict[str, float | str | int | bool] = Field(default_factory=dict)


class SamplingConfig(ScenarioModel):
    """Tiered data sampling frequencies."""

    control_hz: float = Field(gt=0)
    intersection_hz: float = Field(gt=0)
    dashboard_hz: float = Field(gt=0)
    vehicle_trajectory_hz: float = Field(ge=0)
    experiment_summary_hz: float = Field(gt=0)


class ActiveModeDemand(ScenarioModel):
    """One deterministic bicycle, e-bike or pedestrian OD demand group."""

    participant: Literal["bicycle", "electric_bicycle", "pedestrian"]
    origin_zone: str
    destination_zone: str
    flow_persons_h: float = Field(ge=0)
    begin_s: float = Field(ge=0)
    end_s: float = Field(gt=0)
    route_alternatives: bool = True

    @model_validator(mode="after")
    def validate_window(self) -> "ActiveModeDemand":
        """Ensure active-mode demand ends after it begins."""

        if self.end_s <= self.begin_s:
            raise ValueError("active-mode demand end_s must be greater than begin_s")
        return self


class MultimodalConfig(ScenarioModel):
    """Derived full-network pedestrian and bicycle modeling settings."""

    enabled: bool = True
    network_scope: Literal["complete_osm_network"] = "complete_osm_network"
    infrastructure_source: Literal["osm_plus_traceable_engineering_inference"] = (
        "osm_plus_traceable_engineering_inference"
    )
    pedestrian_signal_mode: Literal["conditional_parallel"] = "conditional_parallel"
    sidewalk_width_m: float = Field(default=2.5, gt=0)
    bicycle_lane_width_m: float = Field(default=2.0, gt=0)
    sidewalk_max_road_speed_m_s: float = Field(default=22.3, gt=0)
    bicycle_lane_max_road_speed_m_s: float = Field(default=19.5, gt=0)
    crossing_speed_threshold_m_s: float = Field(default=22.3, gt=0)
    pedestrian_min_green_s: float = Field(default=10.0, gt=0)
    pedestrian_clearance_s: float = Field(default=5.0, gt=0)
    demands: list[ActiveModeDemand] = Field(default_factory=list)


class ScenarioConfig(ScenarioModel):
    """Complete scenario input used to generate a traceable manifest."""

    schema_version: str = Field(pattern=r"^\d+\.\d+$")
    scenario_id: str
    display_name: str
    provenance: Literal[
        "organizer_supplied",
        "openstreetmap_plus_modeled_parameters",
        "engineering_demo_placeholder",
    ]
    is_real_measured_network: bool
    network_file: str
    simulation: SimulationConfig
    demand: list[OdDemand]
    vehicle_type_ratios: dict[str, float]
    connected_vehicle_penetration: float = Field(ge=0, le=1)
    flow_multiplier: float = Field(gt=0)
    signal_plan: str
    disturbances: list[Disturbance]
    communication: CommunicationConfig
    algorithm: AlgorithmSelection
    sampling: SamplingConfig
    multimodal: MultimodalConfig = Field(default_factory=MultimodalConfig)

    @model_validator(mode="after")
    def ratios_sum_to_one(self) -> "ScenarioConfig":
        """Require an explicit complete vehicle mix."""

        if abs(sum(self.vehicle_type_ratios.values()) - 1.0) > 1e-6:
            raise ValueError("vehicle_type_ratios must sum to 1")
        if any(ratio < 0 or ratio > 1 for ratio in self.vehicle_type_ratios.values()):
            raise ValueError("vehicle type ratios must be between 0 and 1")
        return self

    @classmethod
    def from_yaml(cls, path: Path) -> "ScenarioConfig":
        """Load and validate a UTF-8 YAML scenario file."""

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls.model_validate(data)
