"""Machine-readable specification and JSON Schema contract tests."""

import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from traffic_platform.api.app import create_app
from traffic_platform.specification import validate_specs


def test_all_specs_and_generated_schemas_validate() -> None:
    result = validate_specs(Path.cwd())
    assert result["status"] == "valid"
    assert result["json_schema_count"] == 19
    assert "xiongan_rongdong_20" in result["scenario_ids"]
    for path in Path("specs/jsonschema").glob("*.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        assert schema["examples"]
        Draft202012Validator(schema).validate(schema["examples"][0])


def test_every_mqtt_topic_references_a_generated_contract() -> None:
    mqtt = yaml.safe_load(Path("specs/mqtt_topics.yaml").read_text(encoding="utf-8"))
    schema_names = {
        path.stem for path in Path("specs/jsonschema").glob("*.json")
    }
    unresolved = {
        topic["model"]
        for topic in mqtt["topics"].values()
        if topic["model"] not in schema_names
    }
    assert unresolved == set()


def test_runtime_openapi_paths_and_methods_match_formal_specification() -> None:
    specification = yaml.safe_load(
        Path("specs/openapi.yaml").read_text(encoding="utf-8")
    )
    runtime = create_app().openapi()
    websocket_paths = {"/ws/v1/realtime", "/ws/v1/digital-twin"}
    specification_paths = set(specification["paths"]) - websocket_paths
    runtime_paths = set(runtime["paths"])
    assert runtime_paths == specification_paths
    for path in specification_paths:
        expected_methods = {
            method
            for method in specification["paths"][path]
            if method in {"get", "post", "put", "patch", "delete"}
        }
        assert set(runtime["paths"][path]) == expected_methods
    runtime_route_paths = {route.path for route in create_app().routes}
    assert websocket_paths <= runtime_route_paths
