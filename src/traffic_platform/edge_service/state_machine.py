"""Configurable cloud-edge fault degradation and smooth recovery state machine."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from traffic_platform.common.errors import ErrorCode, PlatformError
from traffic_platform.contracts.models import CloudStrategy


class EdgeMode(StrEnum):
    """Required edge operating modes."""

    CLOUD_COORDINATED = "CLOUD_COORDINATED"
    HOLD_LAST_VALID = "HOLD_LAST_VALID"
    EDGE_AUTONOMOUS = "EDGE_AUTONOMOUS"
    FIXED_TIME_SAFE = "FIXED_TIME_SAFE"
    RECOVERY_SYNC = "RECOVERY_SYNC"


@dataclass(frozen=True, slots=True)
class DegradationConfig:
    """Simulation-time state transition thresholds."""

    hold_timeout_s: float = 15.0
    autonomous_timeout_s: float = 30.0
    recovery_stable_s: float = 5.0

    def __post_init__(self) -> None:
        if not 0 < self.hold_timeout_s <= self.autonomous_timeout_s:
            raise ValueError("hold_timeout_s must be positive and <= autonomous_timeout_s")
        if self.recovery_stable_s <= 0:
            raise ValueError("recovery_stable_s must be positive")


@dataclass(frozen=True, slots=True)
class StateTransition:
    """Auditable state transition at one simulation time."""

    previous: EdgeMode
    current: EdgeMode
    simulation_time: float
    reason: str


class EdgeDegradationMachine:
    """Handle timeout, algorithm failure and version-synchronized recovery."""

    def __init__(self, config: DegradationConfig | None = None) -> None:
        self.config = config or DegradationConfig()
        self.mode = EdgeMode.EDGE_AUTONOMOUS
        self.last_cloud_time: float | None = None
        self.last_simulation_time: float | None = None
        self.last_strategy_version = 0
        self.last_strategy_versions: dict[str, int] = {}
        self.recovery_started_at: float | None = None
        self.transitions: list[StateTransition] = []

    def _transition(self, target: EdgeMode, simulation_time: float, reason: str) -> None:
        if target == self.mode:
            return
        self.transitions.append(
            StateTransition(self.mode, target, simulation_time, reason)
        )
        self.mode = target

    def tick(
        self,
        simulation_time: float,
        *,
        local_healthy: bool = True,
        state_sufficient: bool = True,
    ) -> EdgeMode:
        """Advance timeout and recovery transitions using simulation time."""

        if self.last_simulation_time is not None and simulation_time < self.last_simulation_time:
            self._transition(
                EdgeMode.FIXED_TIME_SAFE,
                simulation_time,
                "SIMULATION_TIME_ROLLBACK",
            )
            raise PlatformError(
                ErrorCode.INVALID_STATE_TRANSITION,
                "simulation time moved backwards",
            )
        self.last_simulation_time = simulation_time
        if not local_healthy or not state_sufficient:
            self._transition(EdgeMode.FIXED_TIME_SAFE, simulation_time, "LOCAL_FAILURE")
            return self.mode
        if (
            self.mode == EdgeMode.RECOVERY_SYNC
            and self.recovery_started_at is not None
            and simulation_time - self.recovery_started_at
            >= self.config.recovery_stable_s
        ):
            self._transition(
                EdgeMode.CLOUD_COORDINATED,
                simulation_time,
                "RECOVERY_STABLE",
            )
        if self.last_cloud_time is None:
            if self.mode != EdgeMode.FIXED_TIME_SAFE:
                self._transition(
                    EdgeMode.EDGE_AUTONOMOUS,
                    simulation_time,
                    "NO_CLOUD_STRATEGY",
                )
            return self.mode
        age = simulation_time - self.last_cloud_time
        if self.mode == EdgeMode.CLOUD_COORDINATED and age >= self.config.hold_timeout_s:
            self._transition(EdgeMode.HOLD_LAST_VALID, simulation_time, "CLOUD_SHORT_TIMEOUT")
        if age >= self.config.autonomous_timeout_s and self.mode in {
            EdgeMode.CLOUD_COORDINATED,
            EdgeMode.HOLD_LAST_VALID,
            EdgeMode.RECOVERY_SYNC,
        }:
            self._transition(EdgeMode.EDGE_AUTONOMOUS, simulation_time, "CLOUD_TIMEOUT")
        return self.mode

    def accept_strategy(
        self,
        strategy: CloudStrategy,
        *,
        simulation_time: float,
        experiment_id: str,
    ) -> bool:
        """Reject invalid/replayed strategies and enter synchronized recovery."""

        if strategy.experiment_id != experiment_id:
            raise PlatformError(
                ErrorCode.EXPERIMENT_MISMATCH,
                "cloud strategy belongs to another experiment",
            )
        if not strategy.valid_from <= simulation_time <= strategy.valid_until:
            return False
        last_target_version = self.last_strategy_versions.get(
            strategy.target_intersection_id,
            0,
        )
        if strategy.strategy_version <= last_target_version:
            return False
        self.last_strategy_versions[
            strategy.target_intersection_id
        ] = strategy.strategy_version
        self.last_strategy_version = strategy.strategy_version
        self.last_cloud_time = simulation_time
        if self.mode not in {
            EdgeMode.CLOUD_COORDINATED,
            EdgeMode.RECOVERY_SYNC,
        }:
            self.recovery_started_at = simulation_time
            self._transition(EdgeMode.RECOVERY_SYNC, simulation_time, "CLOUD_RECOVERED")
        return True

    def local_recovered(self, simulation_time: float, *, cloud_available: bool) -> EdgeMode:
        """Leave fixed-time mode through recovery or local autonomy."""

        if self.mode != EdgeMode.FIXED_TIME_SAFE:
            return self.mode
        if cloud_available:
            self.recovery_started_at = simulation_time
            self._transition(EdgeMode.RECOVERY_SYNC, simulation_time, "LOCAL_RECOVERED")
        else:
            self._transition(EdgeMode.EDGE_AUTONOMOUS, simulation_time, "LOCAL_RECOVERED")
        return self.mode

    def snapshot(self, *, experiment_id: str) -> dict[str, Any]:
        """Serialize restart-critical state without serializing live objects."""

        return {
            "schema_version": "1.0",
            "experiment_id": experiment_id,
            "mode": self.mode.value,
            "last_cloud_time": self.last_cloud_time,
            "last_simulation_time": self.last_simulation_time,
            "last_strategy_version": self.last_strategy_version,
            "last_strategy_versions": dict(self.last_strategy_versions),
            "recovery_started_at": self.recovery_started_at,
        }

    def restore(
        self,
        snapshot: dict[str, Any],
        *,
        experiment_id: str,
        simulation_time: float,
        cloud_available: bool,
    ) -> EdgeMode:
        """Restore after an edge restart and force a non-jumping resynchronization."""

        if snapshot.get("schema_version") != "1.0":
            raise PlatformError(
                ErrorCode.INVALID_STATE_TRANSITION,
                "unsupported degradation snapshot version",
            )
        if snapshot.get("experiment_id") != experiment_id:
            raise PlatformError(
                ErrorCode.EXPERIMENT_MISMATCH,
                "degradation snapshot belongs to another experiment",
            )
        stored_simulation_time = snapshot.get("last_simulation_time")
        if (
            isinstance(stored_simulation_time, int | float)
            and float(stored_simulation_time) > simulation_time
        ):
            self.mode = EdgeMode.FIXED_TIME_SAFE
            self.last_simulation_time = simulation_time
            self.transitions.append(
                StateTransition(
                    EdgeMode(snapshot["mode"]),
                    EdgeMode.FIXED_TIME_SAFE,
                    simulation_time,
                    "RESTART_SIMULATION_TIME_ROLLBACK",
                )
            )
            raise PlatformError(
                ErrorCode.INVALID_STATE_TRANSITION,
                "restored simulation time is ahead of the live simulation",
            )
        versions = snapshot.get("last_strategy_versions", {})
        if not isinstance(versions, dict) or not all(
            isinstance(key, str) and isinstance(value, int)
            for key, value in versions.items()
        ):
            raise PlatformError(
                ErrorCode.INVALID_STATE_TRANSITION,
                "invalid strategy-version snapshot",
            )
        previous = EdgeMode(snapshot["mode"])
        self.last_strategy_versions = {
            key: int(value) for key, value in versions.items()
        }
        self.last_strategy_version = int(snapshot.get("last_strategy_version", 0))
        cloud_time = snapshot.get("last_cloud_time")
        self.last_cloud_time = (
            float(cloud_time) if isinstance(cloud_time, int | float) else None
        )
        self.last_simulation_time = simulation_time
        self.recovery_started_at = simulation_time if cloud_available else None
        self.mode = (
            EdgeMode.RECOVERY_SYNC
            if cloud_available and self.last_strategy_versions
            else EdgeMode.EDGE_AUTONOMOUS
        )
        self.transitions.append(
            StateTransition(
                previous,
                self.mode,
                simulation_time,
                "EDGE_RESTART_RESTORED",
            )
        )
        return self.mode
