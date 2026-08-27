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
        self.simulation_rate: float | None = None
        self._digital_twin_next_time_s = 0.0
        self._digital_twin_decisions: dict[float, float | None] = {}
        self._fault_manifests: dict[str, dict[str, object]] = {}
        self._fault_failure_reason: str | None = None
        self.baseline.set_fault_status_callback(self._fault_callback("baseline"))
        self.candidate.set_fault_status_callback(self._fault_callback("candidate"))

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
        if rate is not None and (rate <= 0 or rate > 32):
            raise ValueError("simulation rate must be in (0, 32]")
        self.simulation_rate = rate
        self.baseline.set_simulation_rate(rate)
        self.candidate.set_simulation_rate(rate)

    def digital_twin_interval_for(
        self,
        simulation_time_s: float,
        base_interval_s: float,
    ) -> float | None:
        """Return one shared visualization decision for a paired SUMO timestamp."""

        if base_interval_s <= 0:
            raise ValueError("digital twin base interval must be positive")
        timestamp = round(float(simulation_time_s), 6)
        if timestamp in self._digital_twin_decisions:
            return self._digital_twin_decisions[timestamp]
        if simulation_time_s + 1e-9 < self._digital_twin_next_time_s:
            interval = None
        else:
            interval = (
                base_interval_s
                if self.simulation_rate is None
                else max(base_interval_s, self.simulation_rate / 4.0)
            )
            self._digital_twin_next_time_s = simulation_time_s + interval
        self._digital_twin_decisions[timestamp] = interval
        return interval

    def inject_fault(
        self,
        fault_type: str,
        parameters: dict[str, float | str | bool],
        *,
        event_id: str | None = None,
        target: str | None = None,
        seed: int = 0,
    ) -> dict[str, object]:
        if event_id is None:
            self.baseline.inject_fault(fault_type, dict(parameters))
            self.candidate.inject_fault(fault_type, dict(parameters))
            return {}

        duration_s = float(parameters.get("duration_s", 30.0))
        apply_at = (
            max(
                self.baseline.simulation_time_s,
                self.candidate.simulation_time_s,
            )
            + 1.0
        )
        canonical_parameters = {
            **parameters,
            "duration_s": duration_s,
            "target": target or str(parameters.get("target", "network")),
            "event_seed": seed,
        }
        manifest: dict[str, object] = {
            "id": event_id,
            "event_id": event_id,
            "fault_type": fault_type,
            "target": canonical_parameters["target"],
            "parameters": dict(canonical_parameters),
            "duration_s": duration_s,
            "deterministic_seed": seed,
            "injection_simulation_time_s": apply_at,
            "expires_at_simulation_time": apply_at + duration_s,
            "status": "pending",
            "runner_status": {
                "baseline": {"status": "pending"},
                "candidate": {"status": "pending"},
            },
        }
        self._fault_manifests[event_id] = manifest
        self.baseline.queue_fault(
            event_id=event_id,
            fault_type=fault_type,
            apply_at_simulation_time_s=apply_at,
            parameters=dict(canonical_parameters),
        )
        self.candidate.queue_fault(
            event_id=event_id,
            fault_type=fault_type,
            apply_at_simulation_time_s=apply_at,
            parameters=dict(canonical_parameters),
        )
        return manifest

    def clear_faults(self) -> None:
        self.baseline.clear_faults()
        self.candidate.clear_faults()

    def fault_manifest(self, event_id: str) -> dict[str, object] | None:
        return self._fault_manifests.get(event_id)

    @property
    def fault_failure_reason(self) -> str | None:
        return self._fault_failure_reason

    def _fault_callback(
        self,
        role: Role,
    ) -> Callable[[str, str, float, str | None], None]:
        def receive(
            event_id: str,
            status: str,
            simulation_time_s: float,
            detail: str | None,
        ) -> None:
            manifest = self._fault_manifests.get(event_id)
            if manifest is None:
                return
            runner_status = manifest["runner_status"]
            assert isinstance(runner_status, dict)
            runner_status[role] = {
                "status": status,
                "simulation_time_s": simulation_time_s,
                **({"detail": detail} if detail else {}),
            }
            statuses = {
                str(item.get("status")) for item in runner_status.values() if isinstance(item, dict)
            }
            if statuses == {"applied"}:
                baseline_status = runner_status.get("baseline")
                candidate_status = runner_status.get("candidate")
                physical_details = {
                    str(item.get("detail"))
                    for item in (baseline_status, candidate_status)
                    if isinstance(item, dict) and item.get("detail") is not None
                }
                if (
                    manifest.get("fault_type")
                    in {
                        "incident",
                        "roadwork",
                        "flow_surge",
                        "large_event",
                    }
                    and len(physical_details) > 1
                ):
                    manifest["status"] = "failed"
                    self._fault_failure_reason = (
                        f"paired event {event_id} selected mismatched physical targets: "
                        f"baseline={baseline_status}, candidate={candidate_status}"
                    )
                else:
                    manifest["status"] = "applied"
                    manifest["applied_at_simulation_time_s"] = simulation_time_s
                    manifest["physical_target"] = next(iter(physical_details), None)
            elif statuses == {"expired"}:
                manifest["status"] = "expired"
            elif statuses == {"cleared"}:
                manifest["status"] = "cleared"
            elif "failed" in statuses:
                manifest["status"] = "failed"
                self._fault_failure_reason = (
                    f"paired event {event_id} failed physical application: "
                    f"baseline={runner_status.get('baseline')}, "
                    f"candidate={runner_status.get('candidate')}"
                )
            elif "scheduled" in statuses or "applied" in statuses:
                manifest["status"] = "applying"
            else:
                manifest["status"] = "pending"

        return receive


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

        def paired_step_callback(role: Role) -> Callable[[float], Awaitable[None]]:
            async def synchronize(simulation_time_s: float) -> None:
                await barrier.wait(role, simulation_time_s)
                if self.control.fault_failure_reason is not None:
                    raise PairSynchronizationError(self.control.fault_failure_reason)

            return synchronize

        baseline_runner = ExperimentRunner(
            self.baseline_config,
            sumo_home=self.sumo_home,
            bus=self.baseline_bus,
            control=self.control.baseline,
            snapshot_callback=self._snapshot_callback("baseline"),
            snapshot_detail="progress",
            digital_twin_callback=self.hub.publish_baseline,
            digital_twin_schedule_callback=self.control.digital_twin_interval_for,
            step_barrier_callback=paired_step_callback("baseline"),
        )
        candidate_runner = ExperimentRunner(
            self.candidate_config,
            sumo_home=self.sumo_home,
            bus=self.candidate_bus,
            control=self.control.candidate,
            snapshot_callback=self._snapshot_callback("candidate"),
            snapshot_detail="progress",
            digital_twin_callback=self.hub.publish_candidate,
            digital_twin_schedule_callback=self.control.digital_twin_interval_for,
            step_barrier_callback=paired_step_callback("candidate"),
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
