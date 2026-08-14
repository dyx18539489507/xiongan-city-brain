"""Protocol and reusable lifecycle implementation for algorithm plugins."""

from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

from traffic_platform.algorithm_sdk.types import (
    AlgorithmConfig,
    AlgorithmHealth,
    ControlDecision,
    ControlObservation,
    HealthStatus,
    NetworkTopology,
)
from traffic_platform.contracts.models import ExecutionFeedback


@runtime_checkable
class TrafficControlAlgorithm(Protocol):
    """Stable interface implemented by every traffic controller."""

    name: str
    version: str

    def initialize(self, config: AlgorithmConfig, topology: NetworkTopology) -> None: ...

    def reset(self, seed: int) -> None: ...

    def observe(self, state: ControlObservation) -> None: ...

    def decide(self, state: ControlObservation) -> ControlDecision: ...

    def feedback(self, feedback: ExecutionFeedback) -> None: ...

    def health(self) -> AlgorithmHealth: ...

    def close(self) -> None: ...


class BaseTrafficController(ABC):
    """Common deterministic lifecycle, counters and health implementation."""

    name = "base"
    version = "0.0.0"

    def __init__(self) -> None:
        self.config: AlgorithmConfig | None = None
        self.topology: NetworkTopology | None = None
        self.last_observation: ControlObservation | None = None
        self.last_feedback: ExecutionFeedback | None = None
        self.seed = 0
        self.decisions = 0
        self.failures = 0
        self.last_decision_ms: float | None = None
        self.closed = False

    def initialize(self, config: AlgorithmConfig, topology: NetworkTopology) -> None:
        """Initialize with validated configuration and immutable topology data."""

        self.config = config
        self.topology = topology
        self.closed = False

    def reset(self, seed: int) -> None:
        """Reset deterministic plugin state for a new experiment."""

        self.seed = seed
        self.last_observation = None
        self.last_feedback = None
        self.decisions = 0
        self.failures = 0
        self.last_decision_ms = None

    def observe(self, state: ControlObservation) -> None:
        """Store the most recent observation for diagnostics."""

        self.last_observation = state

    @abstractmethod
    def decide(self, state: ControlObservation) -> ControlDecision:
        """Return a candidate signal decision."""

    def feedback(self, feedback: ExecutionFeedback) -> None:
        """Accept execution feedback; stateless baselines require no update."""

        self.last_feedback = feedback

    def health(self) -> AlgorithmHealth:
        """Return lifecycle and decision counters."""

        status = HealthStatus.CLOSED if self.closed else HealthStatus.HEALTHY
        return AlgorithmHealth(
            status=status,
            decisions=self.decisions,
            failures=self.failures,
            last_decision_ms=self.last_decision_ms,
            detail="closed" if self.closed else "ready",
        )

    def close(self) -> None:
        """Release plugin resources and reject future execution."""

        self.closed = True

    def require_initialized(self) -> tuple[AlgorithmConfig, NetworkTopology]:
        """Return initialized dependencies or fail with an actionable error."""

        if self.closed:
            raise RuntimeError(f"algorithm {self.name} is closed")
        if self.config is None or self.topology is None:
            raise RuntimeError(f"algorithm {self.name} is not initialized")
        return self.config, self.topology
