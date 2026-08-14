"""Persistent process isolation for traffic-control algorithm plugins."""

from __future__ import annotations

import multiprocessing as mp
import time
from multiprocessing.connection import Connection
from typing import Any, cast
from uuid import uuid4

from traffic_platform.algorithm_sdk.types import (
    AlgorithmConfig,
    AlgorithmHealth,
    ControlDecision,
    ControlObservation,
    HealthStatus,
    NetworkTopology,
)
from traffic_platform.common.errors import ErrorCode, PlatformError
from traffic_platform.contracts.models import ExecutionFeedback
from traffic_platform.observability.metrics import CONTROL_DECISION_SECONDS

ISOLATED_WORKER_STARTUP_TIMEOUT_S = 30.0


def _worker_loop(
    connection: Connection,
    algorithm_name: str,
    config_json: str,
    topology_json: str,
) -> None:
    """Own one plugin instance and communicate only through serialized models."""

    from traffic_platform.algorithms import builtin_registry

    algorithm = builtin_registry().create(algorithm_name)
    algorithm.initialize(
        AlgorithmConfig.model_validate_json(config_json),
        NetworkTopology.model_validate_json(topology_json),
    )
    connection.send({"ready": True, "algorithm": algorithm_name})
    try:
        while True:
            command = connection.recv()
            operation = command["operation"]
            request_id = command["request_id"]
            try:
                if operation == "decide":
                    observation = ControlObservation.model_validate_json(
                        command["payload"]
                    )
                    decision = algorithm.decide(observation)
                    result: dict[str, Any] = {
                        "request_id": request_id,
                        "ok": True,
                        "payload": decision.model_dump_json(),
                    }
                elif operation == "feedback":
                    feedback = ExecutionFeedback.model_validate_json(command["payload"])
                    algorithm.feedback(feedback)
                    result = {"request_id": request_id, "ok": True, "payload": None}
                elif operation == "reset":
                    algorithm.reset(int(command["payload"]))
                    result = {"request_id": request_id, "ok": True, "payload": None}
                elif operation == "health":
                    result = {
                        "request_id": request_id,
                        "ok": True,
                        "payload": algorithm.health().model_dump_json(),
                    }
                elif operation == "close":
                    result = {"request_id": request_id, "ok": True, "payload": None}
                    connection.send(result)
                    break
                else:
                    raise ValueError(f"unknown isolated algorithm operation: {operation}")
            except Exception as exc:
                result = {
                    "request_id": request_id,
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            connection.send(result)
    finally:
        algorithm.close()
        connection.close()


class IsolatedAlgorithmRunner:
    """Protocol-compatible plugin proxy with enforceable wall-clock deadlines."""

    def __init__(
        self,
        algorithm_name: str,
        config: AlgorithmConfig,
        topology: NetworkTopology,
    ) -> None:
        registry_instance = __import__(
            "traffic_platform.algorithms",
            fromlist=["builtin_registry"],
        ).builtin_registry()
        probe = registry_instance.create(algorithm_name)
        self.name = probe.name
        self.version = probe.version
        probe.close()
        self._config = config
        self._topology = topology
        self._parent: Any = None
        self._process: Any = None
        self._closed = False
        self._decisions = 0
        self._failures = 0
        self._last_decision_ms: float | None = None
        self._start()

    def initialize(self, config: AlgorithmConfig, topology: NetworkTopology) -> None:
        """Restart the isolated plugin with a new validated configuration."""

        self._config = config
        self._topology = topology
        self._restart()

    def reset(self, seed: int) -> None:
        """Reset the child plugin deterministically."""

        self._request("reset", seed, timeout_s=2.0)

    def observe(self, state: ControlObservation) -> None:
        """Observations are supplied atomically with each decision."""

    def decide(self, state: ControlObservation) -> ControlDecision:
        """Return within the configured timeout or terminate the child process."""

        started = time.perf_counter()
        try:
            response = self._request(
                "decide",
                state.model_dump_json(),
                timeout_s=self._config.decision_timeout_ms / 1000.0,
            )
        except PlatformError:
            self._failures += 1
            self._restart()
            raise
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        self._last_decision_ms = elapsed_ms
        self._decisions += 1
        CONTROL_DECISION_SECONDS.labels(algorithm=self.name).observe(elapsed_ms / 1000.0)
        payload = response.get("payload")
        if not isinstance(payload, str):
            self._failures += 1
            raise PlatformError(
                ErrorCode.ALGORITHM_FAILURE,
                f"{self.name} returned an invalid isolated decision payload",
            )
        return ControlDecision.model_validate_json(payload)

    def feedback(self, feedback: ExecutionFeedback) -> None:
        """Forward execution feedback without allowing it to block control."""

        try:
            self._request(
                "feedback",
                feedback.model_dump_json(),
                timeout_s=0.5,
            )
        except PlatformError:
            self._failures += 1
            self._restart()

    def health(self) -> AlgorithmHealth:
        """Report parent-observed health even if the child is unavailable."""

        alive = self._process is not None and self._process.is_alive()
        return AlgorithmHealth(
            status=(
                HealthStatus.CLOSED
                if self._closed
                else HealthStatus.HEALTHY
                if alive and self._failures == 0
                else HealthStatus.DEGRADED
            ),
            decisions=self._decisions,
            failures=self._failures,
            last_decision_ms=self._last_decision_ms,
            detail="isolated worker alive" if alive else "isolated worker unavailable",
        )

    def close(self) -> None:
        """Request graceful child shutdown, then terminate if necessary."""

        if self._closed:
            return
        try:
            if self._process is not None and self._process.is_alive():
                self._request("close", None, timeout_s=0.5)
        except PlatformError:
            pass
        self._terminate()
        self._closed = True

    def _start(self) -> None:
        context = mp.get_context("spawn")
        parent, child = context.Pipe(duplex=True)
        process = context.Process(
            target=_worker_loop,
            args=(
                child,
                self.name,
                self._config.model_dump_json(),
                self._topology.model_dump_json(),
            ),
            name=f"algorithm-{self.name}",
            daemon=True,
        )
        process.start()
        child.close()
        self._parent = parent
        self._process = process
        if not parent.poll(ISOLATED_WORKER_STARTUP_TIMEOUT_S):
            self._terminate()
            raise PlatformError(
                ErrorCode.ALGORITHM_FAILURE,
                (
                    f"{self.name} isolated worker startup exceeded "
                    f"{ISOLATED_WORKER_STARTUP_TIMEOUT_S:.0f}s"
                ),
            )
        ready = parent.recv()
        if not isinstance(ready, dict) or not ready.get("ready"):
            self._terminate()
            raise PlatformError(
                ErrorCode.ALGORITHM_FAILURE,
                f"{self.name} isolated worker failed readiness handshake",
            )

    def _restart(self) -> None:
        self._terminate()
        if not self._closed:
            self._start()

    def _terminate(self) -> None:
        if self._parent is not None:
            self._parent.close()
            self._parent = None
        if self._process is not None:
            if self._process.is_alive():
                self._process.terminate()
                self._process.join(timeout=1.0)
                if self._process.is_alive():
                    self._process.kill()
                    self._process.join(timeout=1.0)
            else:
                self._process.join(timeout=0.1)
            self._process = None

    def _request(
        self,
        operation: str,
        payload: object,
        *,
        timeout_s: float,
    ) -> dict[str, Any]:
        if self._closed:
            raise PlatformError(
                ErrorCode.ALGORITHM_FAILURE,
                f"{self.name} isolated runner is closed",
            )
        if self._process is None or self._parent is None or not self._process.is_alive():
            raise PlatformError(
                ErrorCode.ALGORITHM_FAILURE,
                f"{self.name} isolated worker is not alive",
            )
        request_id = uuid4().hex
        started = time.perf_counter()
        try:
            self._parent.send(
                {
                    "operation": operation,
                    "request_id": request_id,
                    "payload": payload,
                }
            )
            remaining_s = timeout_s - (time.perf_counter() - started)
            if remaining_s <= 0 or not self._parent.poll(remaining_s):
                raise PlatformError(
                    ErrorCode.ALGORITHM_TIMEOUT,
                    (
                        f"{self.name} exceeded the enforceable "
                        f"{timeout_s * 1000.0:.3f} ms deadline"
                    ),
                    details={"limit_ms": timeout_s * 1000.0},
                )
            response = self._parent.recv()
            if time.perf_counter() - started > timeout_s:
                raise PlatformError(
                    ErrorCode.ALGORITHM_TIMEOUT,
                    (
                        f"{self.name} exceeded the enforceable "
                        f"{timeout_s * 1000.0:.3f} ms deadline"
                    ),
                    details={"limit_ms": timeout_s * 1000.0},
                )
        except (EOFError, BrokenPipeError, OSError) as exc:
            raise PlatformError(
                ErrorCode.ALGORITHM_FAILURE,
                f"{self.name} isolated worker communication failed: {exc}",
            ) from exc
        if response.get("request_id") != request_id:
            raise PlatformError(
                ErrorCode.ALGORITHM_FAILURE,
                f"{self.name} isolated response correlation mismatch",
            )
        if not response.get("ok"):
            raise PlatformError(
                ErrorCode.ALGORITHM_FAILURE,
                (
                    f"{self.name} isolated decision failed: "
                    f"{response.get('error_type')}: {response.get('error')}"
                ),
            )
        return cast(dict[str, Any], response)
