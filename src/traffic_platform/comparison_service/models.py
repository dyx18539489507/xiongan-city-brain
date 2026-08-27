"""Versioned atomic WebSocket contract for live paired SUMO state."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from traffic_platform.realtime.models import RealtimeModel


class ComparisonStream(RealtimeModel):
    role: Literal["baseline", "candidate"]
    algorithm: str
    experiment_id: str
    message: dict[str, Any]


class PairedDigitalTwinMessage(RealtimeModel):
    type: Literal["comparison-init", "comparison-delta"]
    protocol_version: Literal["1.0"] = "1.0"
    sequence: int
    status: str
    pair_id: str
    simulation_time_s: float
    fairness_fingerprint: str
    fairness_manifest: dict[str, Any] = Field(default_factory=dict)
    baseline: ComparisonStream
    candidate: ComparisonStream
    comparison: dict[str, Any] = Field(default_factory=dict)
