"""Algorithm registration, discovery and isolated timed execution."""

import gc
import time
from collections.abc import Callable

from traffic_platform.algorithm_sdk.base import BaseTrafficController, TrafficControlAlgorithm
from traffic_platform.algorithm_sdk.types import ControlDecision, ControlObservation
from traffic_platform.common.errors import ErrorCode, PlatformError
from traffic_platform.observability.metrics import CONTROL_DECISION_SECONDS

AlgorithmFactory = Callable[[], TrafficControlAlgorithm]


class AlgorithmRegistry:
    """Name/version registry with deterministic factory-based activation."""

    def __init__(self) -> None:
        self._factories: dict[str, AlgorithmFactory] = {}
        self._versions: dict[str, str] = {}

    def register(self, factory: AlgorithmFactory) -> None:
        """Register a controller factory and reject duplicate names."""

        instance = factory()
        if instance.name in self._factories:
            raise ValueError(f"algorithm already registered: {instance.name}")
        self._factories[instance.name] = factory
        self._versions[instance.name] = instance.version
        instance.close()

    def discover(self) -> list[dict[str, str]]:
        """List registered plugins in stable name order."""

        return [{"name": name, "version": self._versions[name]} for name in sorted(self._factories)]

    def create(self, name: str) -> TrafficControlAlgorithm:
        """Instantiate a named plugin."""

        try:
            return self._factories[name]()
        except KeyError as exc:
            raise PlatformError(
                ErrorCode.ALGORITHM_NOT_FOUND,
                f"algorithm is not registered: {name}",
            ) from exc

    def decide_with_timeout(
        self,
        algorithm: TrafficControlAlgorithm,
        observation: ControlObservation,
        timeout_ms: float,
    ) -> ControlDecision:
        """Run a synchronous decision and reject wall-clock timeout overruns."""

        started = time.perf_counter()
        gc_was_enabled = gc.isenabled()
        if gc_was_enabled:
            gc.disable()
        try:
            decision = algorithm.decide(observation)
        except Exception as exc:
            raise PlatformError(
                ErrorCode.ALGORITHM_FAILURE,
                f"{algorithm.name} decision failed: {exc}",
            ) from exc
        finally:
            if gc_was_enabled:
                gc.enable()
        elapsed_ms = (time.perf_counter() - started) * 1000
        CONTROL_DECISION_SECONDS.labels(algorithm=algorithm.name).observe(elapsed_ms / 1000)
        if elapsed_ms > timeout_ms:
            raise PlatformError(
                ErrorCode.ALGORITHM_TIMEOUT,
                f"{algorithm.name} took {elapsed_ms:.3f} ms (limit {timeout_ms:.3f} ms)",
                details={"elapsed_ms": elapsed_ms, "limit_ms": timeout_ms},
            )
        if isinstance(algorithm, BaseTrafficController):
            algorithm.last_decision_ms = elapsed_ms
        return decision
