"""B0 fixed-time baseline that preserves the active SUMO plan."""

from traffic_platform.algorithm_sdk.base import BaseTrafficController
from traffic_platform.algorithm_sdk.types import (
    ControlDecision,
    ControlObservation,
    DecisionStatus,
)


class FixedTimeController(BaseTrafficController):
    """Hold the current phase and let the loaded fixed plan advance."""

    name = "fixed-time"
    version = "1.0.0"

    def decide(self, state: ControlObservation) -> ControlDecision:
        """Return a no-override decision for SUMO's original timing plan."""

        self.require_initialized()
        self.observe(state)
        self.decisions += 1
        return ControlDecision(
            status=DecisionStatus.HOLD,
            intersection_id=state.intersection.intersection_id,
            requested_phase_id=state.intersection.current_phase_id,
            action_type="hold_phase",
            requested_duration_s=None,
            scores={},
            reason_codes=["FIXED_PLAN_ACTIVE"],
            explanation="B0 preserves the scenario's validated fixed-time plan.",
        )

