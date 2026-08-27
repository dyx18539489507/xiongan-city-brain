"""Bounded in-process fan-out buffer for WebSocket digital-twin clients."""

from __future__ import annotations

import json
import re
from collections import deque
from pathlib import Path
from typing import TextIO

from traffic_platform.realtime.encoder import RealtimeDeltaEncoder
from traffic_platform.realtime.models import DigitalTwinSourceFrame, SceneReference


def _message_sequence(message: dict[str, object]) -> int:
    value = message.get("sequence")
    return value if isinstance(value, int) else -1


def load_scene_reference(
    workspace: Path,
    scenario_id: str,
    *,
    allow_missing: bool = False,
) -> SceneReference:
    """Load the immutable scene contract shared by single and paired hubs."""

    manifest_path = workspace / "generated" / "scenes" / f"{scenario_id}.scene.manifest.json"
    if not manifest_path.is_file():
        if not allow_missing:
            raise FileNotFoundError(f"static scene manifest is missing for {scenario_id}")
        manifest: dict[str, object] = {
            "sceneId": scenario_id,
            "schemaVersion": "1.1",
            "sceneSha256": "unavailable_scene_not_generated",
            "sceneBytes": 0,
            "counts": {},
        }
    else:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scene_id = str(manifest["sceneId"])
    raw_counts = manifest.get("counts", {})
    counts = raw_counts if isinstance(raw_counts, dict) else {}
    return SceneReference(
        scene_id=scene_id,
        schema_version=str(manifest["schemaVersion"]),
        url=f"/api/v1/scenes/{scene_id}/3d",
        sha256=str(manifest["sceneSha256"]),
        bytes=int(manifest["sceneBytes"]),
        counts={str(key): int(value) for key, value in counts.items()},
    )


class DigitalTwinHub:
    """Keep a current snapshot and bounded deltas without retaining trajectories."""

    def __init__(self, workspace: Path, *, max_frames: int = 120) -> None:
        self.workspace = workspace
        self.encoder = RealtimeDeltaEncoder(
            load_scene_reference(workspace, "xiongan_rongdong_20", allow_missing=True)
        )
        self.sequence = 0
        self.status = "idle"
        self.frames: deque[dict[str, object]] = deque(maxlen=max_frames)
        self.replay_stream: TextIO | None = None
        self.replay_experiment_id: str | None = None

    def select_scene(self, scenario_id: str) -> None:
        """Switch the realtime contract before a run, never after deltas start."""

        if self.encoder.scene.scene_id == scenario_id:
            return
        self.close()
        self.encoder = RealtimeDeltaEncoder(load_scene_reference(self.workspace, scenario_id))
        self.status = "idle"
        self.sequence += 1
        self.frames.clear()
        self.frames.append(self.initial_message())

    def publish(self, frame: DigitalTwinSourceFrame) -> None:
        previous_experiment_id = self.encoder.experiment_id
        self.sequence += 1
        self.status = "running"
        message = self.encoder.encode(frame, self.sequence)
        if previous_experiment_id != frame.experiment_id:
            # An experiment boundary is a full resynchronization point. This
            # keeps a client connected across reset/start from applying a delta
            # to entities owned by the prior run.
            initial = self.initial_message()
            self.frames.append(initial)
            self._begin_replay(frame.experiment_id, initial)
        else:
            delta = message.model_dump(mode="json", by_alias=True)
            self.frames.append(delta)
            self._append_replay(delta)

    def set_status(self, status: str) -> None:
        if status == self.status:
            return
        self.status = status
        self.sequence += 1
        initial = self.initial_message()
        self.frames.append(initial)
        self._append_replay(initial)
        if status in {"completed", "failed", "stopped"}:
            self.close()

    def initial_message(self) -> dict[str, object]:
        return self.encoder.initial(self.sequence, self.status).model_dump(
            mode="json", by_alias=True
        )

    def messages_after(self, sequence: int) -> list[dict[str, object]]:
        if sequence >= self.sequence:
            return []
        oldest_sequence = _message_sequence(self.frames[0]) if self.frames else -1
        if not self.frames or sequence < oldest_sequence - 1:
            return [self.initial_message()]
        return [frame for frame in self.frames if _message_sequence(frame) > sequence]

    def close(self) -> None:
        if self.replay_stream is not None:
            self.replay_stream.close()
        self.replay_stream = None
        self.replay_experiment_id = None

    def _begin_replay(
        self,
        experiment_id: str,
        initial: dict[str, object],
    ) -> None:
        self.close()
        safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", experiment_id)
        replay_path = self.workspace / "results" / safe_id / "digital_twin.replay.ndjson"
        replay_path.parent.mkdir(parents=True, exist_ok=True)
        self.replay_stream = replay_path.open("w", encoding="utf-8", buffering=1)
        self.replay_experiment_id = experiment_id
        self._append_replay(initial)

    def _append_replay(self, message: dict[str, object]) -> None:
        if self.replay_stream is None:
            return
        self.replay_stream.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")))
        self.replay_stream.write("\n")
