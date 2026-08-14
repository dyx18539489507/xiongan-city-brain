"""B4 formal future-model integration point without fabricated predictions."""

from pathlib import Path

from traffic_platform.algorithm_sdk.base import BaseTrafficController
from traffic_platform.algorithm_sdk.types import (
    ControlDecision,
    ControlObservation,
    DecisionStatus,
)


class PredictiveAIControllerPlaceholder(BaseTrafficController):
    """Expose ONNX/PyTorch model lifecycle while failing honestly without a model."""

    name = "predictive-controller-placeholder"
    version = "1.0.0"

    def decide(self, state: ControlObservation) -> ControlDecision:
        """Return MODEL_NOT_AVAILABLE unless a supported runtime is implemented."""

        config, _ = self.require_initialized()
        model_path = config.parameters.get("model_path")
        available = isinstance(model_path, str) and Path(model_path).is_file()
        self.observe(state)
        self.decisions += 1
        return ControlDecision(
            status=(
                DecisionStatus.DEGRADED if available else DecisionStatus.MODEL_NOT_AVAILABLE
            ),
            intersection_id=state.intersection.intersection_id,
            requested_phase_id=None,
            action_type="fallback_fixed_time",
            requested_duration_s=None,
            scores={},
            reason_codes=[
                "MODEL_RUNTIME_NOT_IMPLEMENTED" if available else "MODEL_NOT_AVAILABLE"
            ],
            explanation=(
                "A model file was found but Phase 1 does not claim inference support."
                if available
                else "No model is configured; no random or surrogate prediction was generated."
            ),
        )

