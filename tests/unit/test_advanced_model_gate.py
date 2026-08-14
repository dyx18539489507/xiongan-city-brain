from pathlib import Path

from traffic_platform.algorithm_sdk.advanced_models import (
    AdvancedModelGate,
    AdvancedModelKind,
    ModelArtifactSpec,
)


def test_advanced_model_gate_never_claims_missing_model_ready(tmp_path: Path) -> None:
    spec = ModelArtifactSpec(
        model_id="stgnn-rongdong-v1",
        kind=AdvancedModelKind.STGNN,
        version="1.0.0",
        framework="onnx",
        artifact_path=tmp_path / "missing.onnx",
        artifact_sha256="0" * 64,
        feature_schema_version="1.0",
        topology_schema_version="1.0",
        trained=False,
        validated=False,
    )
    status = AdvancedModelGate(spec).activation_status()
    assert status["ready"] is False
    assert status["reason_codes"] == ["MODEL_NOT_AVAILABLE"]
