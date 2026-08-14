"""Machine-readable specification and contract validation utilities."""

import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from traffic_platform.contracts.models import (
    BicycleState,
    CloudCommand,
    CloudStrategy,
    CommunicationEvent,
    EdgeControlAction,
    ExecutionFeedback,
    ExperimentEvent,
    FaultEvent,
    IntersectionState,
    LaneState,
    MetricSnapshot,
    PedestrianState,
    RegionalState,
    SafetyConflictEvent,
    ServiceHeartbeat,
    SpeedGuidance,
    VehicleGuidanceCommand,
    VehicleState,
)
from traffic_platform.scenario_engine.models import ScenarioConfig
from traffic_platform.scenario_engine.profiles import ScenarioProfileSet

CONTRACT_MODELS = (
    VehicleState,
    BicycleState,
    PedestrianState,
    SafetyConflictEvent,
    LaneState,
    IntersectionState,
    RegionalState,
    CloudStrategy,
    EdgeControlAction,
    ExecutionFeedback,
    CommunicationEvent,
    FaultEvent,
    ServiceHeartbeat,
    CloudCommand,
    ExperimentEvent,
    MetricSnapshot,
    SpeedGuidance,
    VehicleGuidanceCommand,
)
SCHEMA_MODELS = (*CONTRACT_MODELS, ScenarioConfig)


def _schema_example(
    schema: dict[str, Any],
    root: dict[str, Any],
    *,
    field_name: str = "",
) -> Any:
    """Build a deterministic JSON-Schema-valid documentation example."""

    if "$ref" in schema:
        target: Any = root
        for part in str(schema["$ref"]).removeprefix("#/").split("/"):
            target = target[part]
        return _schema_example(target, root, field_name=field_name)
    if "default" in schema:
        return schema["default"]
    if "enum" in schema:
        return schema["enum"][0]
    if "const" in schema:
        return schema["const"]
    if "anyOf" in schema:
        choice = next(
            (
                item
                for item in schema["anyOf"]
                if item.get("type") != "null"
            ),
            schema["anyOf"][0],
        )
        return _schema_example(choice, root, field_name=field_name)
    value_type = schema.get("type")
    if value_type == "object" or "properties" in schema:
        properties = schema.get("properties", {})
        return {
            key: _schema_example(value, root, field_name=key)
            for key, value in properties.items()
            if key in schema.get("required", [])
            or "default" in value
        }
    if value_type == "array":
        return []
    if value_type == "boolean":
        return False
    if value_type == "integer":
        return int(schema.get("minimum", 0))
    if value_type == "number":
        if "exclusiveMinimum" in schema:
            return float(schema["exclusiveMinimum"]) + 1.0
        return float(schema.get("minimum", 0.0))
    if value_type == "string":
        if schema.get("format") == "date-time":
            return (
                "2030-01-01T00:00:30Z"
                if field_name == "expires_at"
                else "2030-01-01T00:00:00Z"
            )
        if schema.get("format") == "uuid":
            return "00000000-0000-4000-8000-000000000001"
        if field_name == "schema_version":
            return "1.0"
        return f"example-{field_name or 'value'}"
    return {}


def generate_json_schemas(output_dir: Path) -> list[Path]:
    """Generate canonical Draft 2020-12 schemas from Pydantic contracts."""

    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for model in SCHEMA_MODELS:
        schema = model.model_json_schema(mode="serialization")
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["examples"] = [_schema_example(schema, schema)]
        path = output_dir / f"{model.__name__}.json"
        path.write_text(
            json.dumps(schema, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        paths.append(path)
    return paths


def validate_specs(workspace: Path) -> dict[str, Any]:
    """Validate YAML syntax, JSON schemas, OpenAPI shape and scenario models."""

    spec_dir = workspace / "specs"
    yaml_paths = sorted(spec_dir.glob("*.yaml"))
    parsed: dict[str, Any] = {}
    for path in yaml_paths:
        parsed[path.name] = yaml.safe_load(path.read_text(encoding="utf-8"))
    openapi = parsed["openapi.yaml"]
    if openapi.get("openapi") != "3.1.0":
        raise ValueError("OpenAPI must use version 3.1.0")
    required_paths = {
        "/health",
        "/ready",
        "/api/v1/system/status",
        "/api/v1/scenarios/validate",
        "/api/v1/scenarios/generate",
        "/api/v1/experiments",
        "/ws/v1/realtime",
    }
    missing_paths = required_paths - set(openapi.get("paths", {}))
    if missing_paths:
        raise ValueError(f"OpenAPI missing required paths: {sorted(missing_paths)}")
    schemas = generate_json_schemas(spec_dir / "jsonschema")
    for path in schemas:
        Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))
    scenario_paths = sorted((workspace / "scenarios" / "configs").glob("*.yaml"))
    scenarios = [ScenarioConfig.from_yaml(path) for path in scenario_paths]
    profiles = ScenarioProfileSet.from_yaml(
        workspace / "scenarios" / "configs" / "presets" / "S01-S07.yaml"
    )
    return {
        "status": "valid",
        "yaml_spec_count": len(yaml_paths),
        "json_schema_count": len(schemas),
        "scenario_count": len(scenarios),
        "scenario_ids": [scenario.scenario_id for scenario in scenarios],
        "scenario_profile_count": len(profiles.profiles),
        "scenario_profile_ids": [profile.code for profile in profiles.profiles],
    }
