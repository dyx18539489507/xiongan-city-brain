"""Lockstep orchestration for two independent SUMO/TraCI runners."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal

from traffic_platform.comparison_service.hub import PairedDigitalTwinHub
from traffic_platform.experiment_service.engine import (
    ExperimentConfig,
    ExperimentControl,
    ExperimentRunner,
)
from traffic_platform.messaging.base import MessageBus

Role = Literal["baseline", "candidate"]


class PairSynchronizationError(RuntimeError):
    """Raised when two runners can no longer produce a credible pair."""


class PairedStepBarrier:
    """Release both runners only after the same completed simulation step."""

    def __init__(self, *, tolerance_s: float = 1e-6, timeout_s: float = 120.0) -> None:
        self.tolerance_s = tolerance_s
        self.timeout_s = timeout_s
        self._condition = asyncio.Condition()
        self._generation = 0
        self._waiting: dict[Role, float] = {}
        self._finished: set[Role] = set()
        self._abort_reason: str | None = None

    async def wait(self, role: Role, simulation_time_s: float) -> None:
        async with self._condition:
            self._raise_if_aborted()
            other: Role = "candidate" if role == "baseline" else "baseline"
            if other in self._finished:
                self._abort_locked(f"{other} runner finished before {role} reached the barrier")
                self._raise_if_aborted()
            if role in self._waiting:
                self._abort_locked(f"{role} reached the same barrier generation twice")
                self._raise_if_aborted()

            generation = self._generation
            self._waiting[role] = float(simulation_time_s)
            if len(self._waiting) == 2:
                baseline_time = self._waiting["baseline"]
                candidate_time = self._waiting["candidate"]
                if abs(baseline_time - candidate_time) > self.tolerance_s:
                    self._abort_locked(
                        "simulation time mismatch at step barrier: "
                        f"baseline={baseline_time:.6f}s candidate={candidate_time:.6f}s"
                    )
                    self._raise_if_aborted()
                self._waiting.clear()
                self._generation += 1
                self._condition.notify_all()
                return

            try:
                await asyncio.wait_for(
                    self._condition.wait_for(
                        lambda: self._generation != generation or self._abort_reason is not None
                    ),
                    timeout=self.timeout_s,
                )
            except TimeoutError:
                self._abort_locked(
                    f"{role} waited {self.timeout_s:g}s for {other} at simulation "
                    f"time {simulation_time_s:.6f}s"
                )
            self._raise_if_aborted()

    async def finish(self, role: Role) -> None:
        async with self._condition:
            self._finished.add(role)
            other: Role = "candidate" if role == "baseline" else "baseline"
            if other in self._waiting:
                self._abort_locked(
                    f"{role} runner finished while {other} was waiting at the step barrier"
                )
            self._condition.notify_all()

    async def abort(self, reason: str) -> None:
        async with self._condition:
            self._abort_locked(reason)

    def callback(self, role: Role) -> Callable[[float], Awaitable[None]]:
        async def wait_for_pair(simulation_time_s: float) -> None:
            await self.wait(role, simulation_time_s)

        return wait_for_pair

    def _abort_locked(self, reason: str) -> None:
        if self._abort_reason is None:
            self._abort_reason = reason
        self._condition.notify_all()

    def _raise_if_aborted(self) -> None:
        if self._abort_reason is not None:
            raise PairSynchronizationError(self._abort_reason)


class PairedExperimentControl:
    """Broadcast one user action atomically to both child runner controls."""

    def __init__(self) -> None:
        self.baseline = ExperimentControl()
        self.candidate = ExperimentControl()

    @property
    def stop_requested(self) -> bool:
        return self.baseline.stop_requested or self.candidate.stop_requested

    def pause(self) -> None:
        self.baseline.pause()
        self.candidate.pause()

    def resume(self) -> None:
        self.baseline.resume()
        self.candidate.resume()

    def stop(self) -> None:
        self.baseline.stop()
        self.candidate.stop()

    def set_simulation_rate(self, rate: float | None) -> None:
        self.baseline.set_simulation_rate(rate)
        self.candidate.set_simulation_rate(rate)

    def inject_fault(
        self,
        fault_type: str,
        parameters: dict[str, float | str | bool],
    ) -> None:
        self.baseline.inject_fault(fault_type, dict(parameters))
        self.candidate.inject_fault(fault_type, dict(parameters))

    def clear_faults(self) -> None:
        self.baseline.clear_faults()
        self.candidate.clear_faults()


class LivePairedExperimentRunner:
    """Run two real experiments and fail the pair if either child fails."""

    def __init__(
        self,
        *,
        baseline_config: ExperimentConfig,
        candidate_config: ExperimentConfig,
        sumo_home: Path,
        baseline_bus: MessageBus,
        candidate_bus: MessageBus,
        control: PairedExperimentControl,
        hub: PairedDigitalTwinHub,
        snapshot_callback: Callable[[Role, dict[str, object]], None] | None = None,
    ) -> None:
        self.baseline_config = baseline_config
        self.candidate_config = candidate_config
        self.sumo_home = sumo_home
        self.baseline_bus = baseline_bus
        self.candidate_bus = candidate_bus
        self.control = control
        self.hub = hub
        self.snapshot_callback = snapshot_callback

    async def run(self) -> dict[str, object]:
        barrier = PairedStepBarrier()
        baseline_runner = ExperimentRunner(
            self.baseline_config,
            sumo_home=self.sumo_home,
            bus=self.baseline_bus,
            control=self.control.baseline,
            snapshot_callback=self._snapshot_callback("baseline"),
            snapshot_detail="progress",
            digital_twin_callback=self.hub.publish_baseline,
            step_barrier_callback=barrier.callback("baseline"),
        )
        candidate_runner = ExperimentRunner(
            self.candidate_config,
            sumo_home=self.sumo_home,
            bus=self.candidate_bus,
            control=self.control.candidate,
            snapshot_callback=self._snapshot_callback("candidate"),
            snapshot_detail="progress",
            digital_twin_callback=self.hub.publish_candidate,
            step_barrier_callback=barrier.callback("candidate"),
        )

        async def run_role(role: Role, runner: ExperimentRunner) -> dict[str, object]:
            try:
                return await runner.run()
            finally:
                await barrier.finish(role)

        tasks = {
            "baseline": asyncio.create_task(
                run_role("baseline", baseline_runner), name="paired-sumo-baseline"
            ),
            "candidate": asyncio.create_task(
                run_role("candidate", candidate_runner), name="paired-sumo-candidate"
            ),
        }
        done, pending = await asyncio.wait(tasks.values(), return_when=asyncio.FIRST_EXCEPTION)
        failures = [task.exception() for task in done if task.exception() is not None]
        if failures:
            reason = f"paired runner failed: {type(failures[0]).__name__}: {failures[0]}"
            self.control.stop()
            await barrier.abort(reason)
            self.hub.invalidate(reason)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            raise PairSynchronizationError(reason) from failures[0]

        results = {role: task.result() for role, task in tasks.items()}
        return {
            "status": "stopped" if self.control.stop_requested else "completed",
            "baseline": results["baseline"],
            "candidate": results["candidate"],
            "comparison": self.hub.accumulator.summary(),
        }

    def _snapshot_callback(
        self,
        role: Role,
    ) -> Callable[[dict[str, object]], None] | None:
        callback = self.snapshot_callback
        if callback is None:
            return None

        def receive(snapshot: dict[str, object]) -> None:
            callback(role, snapshot)

        return receive
