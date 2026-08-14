"""Formal artifact gates for Phase 2 STGNN, MPC and multi-agent RL models."""

from __future__ import annotations

import hashlib
from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from traffic_platform.algorithm_sdk.types import ControlDecision, ControlObservation


class AdvancedModelKind(StrEnum):
    """Advanced model families reserved by the stable algorithm SDK."""

    STGNN = "spatiotemporal_graph_neural_network"
    MPC = "model_predictive_control"
    MULTI_AGENT_RL = "multi_agent_reinforcement_learning"


class ModelArtifactSpec(BaseModel):
    """Versioned model artifact metadata required before runtime activation."""

    model_config = ConfigDict(strict=True, extra="forbid")

    model_id: str
    kind: AdvancedModelKind
    version: str
    framework: Literal["onnx", "pytorch", "native_solver"]
    artifact_path: Path
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    feature_schema_version: str
    topology_schema_version: str
    trained: bool
    validated: bool

    def verify_artifact(self) -> tuple[bool, list[str]]:
        """Verify presence, provenance hash and activation gates without inference."""

        reasons: list[str] = []
        if not self.artifact_path.is_file():
            reasons.append("MODEL_NOT_AVAILABLE")
            return False, reasons
        digest = hashlib.sha256(self.artifact_path.read_bytes()).hexdigest()
        if digest != self.artifact_sha256:
            reasons.append("MODEL_HASH_MISMATCH")
        if not self.trained:
            reasons.append("MODEL_NOT_TRAINED")
        if not self.validated:
            reasons.append("MODEL_NOT_VALIDATED")
        return not reasons, reasons


class SpatioTemporalPredictor(Protocol):
    """Future regional traffic-state predictor interface."""

    artifact: ModelArtifactSpec

    def predict(self, observation: ControlObservation) -> dict[str, float]: ...


class ModelPredictiveOptimizer(Protocol):
    """Future constrained finite-horizon optimizer interface."""

    artifact: ModelArtifactSpec

    def optimize(self, observation: ControlObservation) -> ControlDecision: ...


class MultiAgentPolicy(Protocol):
    """Future decentralized policy interface with centralized training metadata."""

    artifact: ModelArtifactSpec

    def act(self, observation: ControlObservation) -> ControlDecision: ...


class AdvancedModelGate:
    """Reject unavailable/unverified model artifacts before plugin activation."""

    def __init__(self, artifact: ModelArtifactSpec) -> None:
        self.artifact = artifact

    def activation_status(self) -> dict[str, object]:
        """Return machine-readable readiness and honest unavailable reasons."""

        ready, reasons = self.artifact.verify_artifact()
        return {
            "model_id": self.artifact.model_id,
            "kind": self.artifact.kind.value,
            "version": self.artifact.version,
            "ready": ready,
            "reason_codes": reasons,
        }
