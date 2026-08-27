"""Atomic fan-out hub for two synchronized SUMO digital twins."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from traffic_platform.comparison_service.metrics import LiveComparisonAccumulator
from traffic_platform.comparison_service.models import (
    ComparisonStream,
    PairedDigitalTwinMessage,
)
from traffic_platform.realtime.encoder import RealtimeDeltaEncoder
from traffic_platform.realtime.hub import load_scene_reference
from traffic_platform.realtime.models import DigitalTwinSourceFrame

Role = Literal["baseline", "candidate"]


def _message_sequence(message: Mapping[str, object]) -> int:
    value = message.get("sequence")
    return value if isinstance(value, int) else -1


class PairedDigitalTwinHub:
    """Pair frames by simulation time and publish them as one indivisible message."""

    def __init__(self, workspace: Path, *, max_frames: int = 120, window_s: float = 60.0):
        self.workspace = workspace
        scene = load_scene_reference(workspace, "xiongan_rongdong_20", allow_missing=True)
        self.baseline_encoder = RealtimeDeltaEncoder(scene)
        self.candidate_encoder = RealtimeDeltaEncoder(scene)
        self.accumulator = LiveComparisonAccumulator(window_s=window_s)
        self.frames: deque[dict[str, Any]] = deque(maxlen=max_frames)
        self.sequence = 0
        self.status = "idle"
        self.pair_id = ""
        self.baseline_algorithm = ""
        self.candidate_algorithm = ""
        self.baseline_experiment_id = ""
        self.candidate_experiment_id = ""
        self.fairness_manifest: dict[str, Any] = {}
        self.fairness_fingerprint = ""
        self._baseline_pending: DigitalTwinSourceFrame | None = None
        self._candidate_pending: DigitalTwinSourceFrame | None = None
        self._has_published = False

    def configure(
        self,
        *,
        pair_id: str,
        scenario_id: str,
        baseline_algorithm: str,
        candidate_algorithm: str,
        baseline_experiment_id: str,
        candidate_experiment_id: str,
        fairness_manifest: Mapping[str, Any],
        fairness_fingerprint: str,
    ) -> None:
        scene = load_scene_reference(self.workspace, scenario_id)
        self.baseline_encoder = RealtimeDeltaEncoder(scene)
        self.candidate_encoder = RealtimeDeltaEncoder(scene)
        self.accumulator = LiveComparisonAccumulator(window_s=self.accumulator.window_s)
        self.frames.clear()
        self.sequence += 1
        self.status = "configured"
        self.pair_id = pair_id
        self.baseline_algorithm = baseline_algorithm
        self.candidate_algorithm = candidate_algorithm
        self.baseline_experiment_id = baseline_experiment_id
        self.candidate_experiment_id = candidate_experiment_id
        self.fairness_manifest = dict(fairness_manifest)
        self.fairness_fingerprint = fairness_fingerprint
        self._baseline_pending = None
        self._candidate_pending = None
        self._has_published = False
        self.frames.append(self.initial_message())

    def publish_baseline(self, frame: DigitalTwinSourceFrame) -> None:
        self._accept("baseline", frame)

    def publish_candidate(self, frame: DigitalTwinSourceFrame) -> None:
        self._accept("candidate", frame)

    def set_status(self, status: str) -> None:
        if status == self.status:
            return
        self.status = status
        self.sequence += 1
        self.frames.append(self.initial_message())

    def invalidate(self, reason: str) -> None:
        self.accumulator.invalidate(reason)
        self._baseline_pending = None
        self._candidate_pending = None
        self.set_status("invalid")

    def messages_after(self, sequence: int) -> list[dict[str, Any]]:
        if sequence >= self.sequence:
            return []
        oldest = _message_sequence(self.frames[0]) if self.frames else -1
        if not self.frames or sequence < oldest - 1:
            return [self.initial_message()]
        return [frame for frame in self.frames if _message_sequence(frame) > sequence]

    def initial_message(self) -> dict[str, Any]:
        return self._message(
            message_type="comparison-init",
            baseline_message=self.baseline_encoder.initial(
                self.sequence, self.status
            ).model_dump(mode="json", by_alias=True),
            candidate_message=self.candidate_encoder.initial(
                self.sequence, self.status
            ).model_dump(mode="json", by_alias=True),
        )

    def _accept(self, role: Role, frame: DigitalTwinSourceFrame) -> None:
        if self.status == "invalid":
            return
        expected_experiment_id = (
            self.baseline_experiment_id if role == "baseline" else self.candidate_experiment_id
        )
        if frame.experiment_id != expected_experiment_id:
            self.invalidate(
                f"{role} experiment mismatch: expected={expected_experiment_id} "
                f"actual={frame.experiment_id}"
            )
            return

        attribute = "_baseline_pending" if role == "baseline" else "_candidate_pending"
        if getattr(self, attribute) is not None:
            self.invalidate(f"{role} advanced before its paired stream reached the barrier")
            return
        setattr(self, attribute, frame)
        if self._baseline_pending is None or self._candidate_pending is None:
            return

        baseline = self._baseline_pending
        candidate = self._candidate_pending
        self._baseline_pending = None
        self._candidate_pending = None
        try:
            self.accumulator.add(baseline, candidate)
        except ValueError:
            self.set_status("invalid")
            return

        self.sequence += 1
        if self.status in {"configured", "starting"}:
            self.status = "running"
        baseline_delta = self.baseline_encoder.encode(baseline, self.sequence)
        candidate_delta = self.candidate_encoder.encode(candidate, self.sequence)
        if not self._has_published:
            baseline_message = self.baseline_encoder.initial(
                self.sequence, self.status
            ).model_dump(mode="json", by_alias=True)
            candidate_message = self.candidate_encoder.initial(
                self.sequence, self.status
            ).model_dump(mode="json", by_alias=True)
            message_type: Literal["comparison-init", "comparison-delta"] = "comparison-init"
            self._has_published = True
        else:
            baseline_message = baseline_delta.model_dump(mode="json", by_alias=True)
            candidate_message = candidate_delta.model_dump(mode="json", by_alias=True)
            message_type = "comparison-delta"
        self.frames.append(
            self._message(
                message_type=message_type,
                baseline_message=baseline_message,
                candidate_message=candidate_message,
            )
        )

    def _message(
        self,
        *,
        message_type: Literal["comparison-init", "comparison-delta"],
        baseline_message: dict[str, Any],
        candidate_message: dict[str, Any],
    ) -> dict[str, Any]:
        simulation_time = min(
            self.baseline_encoder.simulation_time_s,
            self.candidate_encoder.simulation_time_s,
        )
        model = PairedDigitalTwinMessage(
            type=message_type,
            sequence=self.sequence,
            status=self.status,
            pair_id=self.pair_id,
            simulation_time_s=simulation_time,
            fairness_fingerprint=self.fairness_fingerprint,
            fairness_manifest=self.fairness_manifest,
            baseline=ComparisonStream(
                role="baseline",
                algorithm=self.baseline_algorithm,
                experiment_id=self.baseline_experiment_id,
                message=baseline_message,
            ),
            candidate=ComparisonStream(
                role="candidate",
                algorithm=self.candidate_algorithm,
                experiment_id=self.candidate_experiment_id,
                message=candidate_message,
            ),
            comparison=self.accumulator.summary(),
        )
        return model.model_dump(mode="json", by_alias=True)
