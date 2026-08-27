"""Four built-in traffic-control algorithms."""

from traffic_platform.algorithm_sdk.registry import AlgorithmRegistry
from traffic_platform.algorithms.actuated import ActuatedController
from traffic_platform.algorithms.coordinated import CoordinatedMaxPressureController
from traffic_platform.algorithms.fixed_time import FixedTimeController
from traffic_platform.algorithms.max_pressure import MaxPressureController


def builtin_registry() -> AlgorithmRegistry:
    """Return a registry containing all Phase 1 controllers."""

    registry = AlgorithmRegistry()
    registry.register(FixedTimeController)
    registry.register(ActuatedController)
    registry.register(MaxPressureController)
    registry.register(CoordinatedMaxPressureController)
    return registry


__all__ = [
    "ActuatedController",
    "CoordinatedMaxPressureController",
    "FixedTimeController",
    "MaxPressureController",
    "builtin_registry",
]
