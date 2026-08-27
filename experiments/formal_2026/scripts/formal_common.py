"""Shared definitions for the append-only formal experiment campaign."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

CAMPAIGN_DIR = Path(__file__).resolve().parents[1]
WORKSPACE = CAMPAIGN_DIR.parents[1]
CONFIG_DIR = CAMPAIGN_DIR / "configs"
RAW_DIR = CAMPAIGN_DIR / "raw"
PROCESSED_DIR = CAMPAIGN_DIR / "processed"
FIGURES_DIR = CAMPAIGN_DIR / "figures"
TABLES_DIR = CAMPAIGN_DIR / "tables"
LOGS_DIR = CAMPAIGN_DIR / "logs"
METADATA_DIR = CAMPAIGN_DIR / "metadata"

ALGORITHMS = {
    "B0": "fixed-time",
    "B1": "actuated-control",
    "B2": "max-pressure",
    "B3": "coordinated-max-pressure",
}
ALGORITHM_CODES = {value: key for key, value in ALGORITHMS.items()}
DEFAULT_SEEDS = (42, 123, 2026, 3407, 9001)
DEMANDS = {
    "Low": {"profile": "S01", "multiplier": 0.75},
    "Medium": {"profile": "S03", "multiplier": 1.0},
    "High": {"profile": "S04", "multiplier": 1.2},
    "Oversaturated": {"profile": "S02", "multiplier": 1.6},
}
NETWORK_PROFILES: dict[str, dict[str, float]] = {
    "N0": {},
    "LAT50": {"base_latency_ms": 50.0},
    "LAT100": {"base_latency_ms": 100.0},
    "LAT200": {"base_latency_ms": 200.0},
    "JITTER50": {"base_latency_ms": 100.0, "jitter_ms": 50.0},
    "LOSS1": {"packet_loss_rate": 0.01},
    "LOSS5": {"packet_loss_rate": 0.05},
    "LOSS10": {"packet_loss_rate": 0.10},
    "REORDER1": {"base_latency_ms": 50.0, "jitter_ms": 20.0, "reorder_rate": 0.01},
    "BROKER60": {},
    "CLOUD60": {},
}


@dataclass(frozen=True, slots=True)
class FormalJob:
    """One fully specified run before an immutable attempt ID is assigned."""

    suite: str
    scenario: str
    demand: str
    profile: str
    controller: str
    seed: int
    disturbance: str
    network_profile: str
    duration_s: float
    warmup_s: float
    profile_mode: str = "no_disturbance"
    disturbance_time_scale: float = 1.0
    scheduled_faults: tuple[dict[str, Any], ...] = ()
    capture_trajectory: bool = False
    isolate_algorithms: bool = False
    publish_feedback_to_bus: bool = False
    publish_runtime_telemetry_to_bus: bool = False
    include_communication_events: bool = False
    surrogate_safety_interval_s: float = 5.0

    @property
    def controller_code(self) -> str:
        return ALGORITHM_CODES[self.controller]

    @property
    def run_key(self) -> str:
        fields = (
            self.suite,
            self.demand,
            self.controller_code,
            f"s{self.seed}",
            self.disturbance,
            self.network_profile,
            f"d{self.duration_s:g}",
            f"w{self.warmup_s:g}",
        )
        return sanitize("-".join(fields)).lower()

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "run_key": self.run_key, "controller_code": self.controller_code}


def sanitize(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")


def ensure_directories() -> None:
    for path in (
        RAW_DIR,
        PROCESSED_DIR,
        FIGURES_DIR,
        TABLES_DIR,
        LOGS_DIR,
        METADATA_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)


def load_protocol() -> dict[str, Any]:
    value = yaml.safe_load((CONFIG_DIR / "formal_protocol.yaml").read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("formal protocol must be a mapping")
    return value


def build_jobs(
    suite: str,
    *,
    duration_s: float,
    warmup_s: float,
    seeds: tuple[int, ...],
) -> list[FormalJob]:
    if warmup_s < 0 or duration_s <= warmup_s:
        raise ValueError("duration_s must be greater than non-negative warmup_s")
    jobs: list[FormalJob] = []
    if suite in {"pilot", "all"}:
        for controller in (ALGORITHMS["B0"], ALGORITHMS["B3"]):
            jobs.append(
                base_job(
                    "pilot",
                    "Medium",
                    controller,
                    seeds[0],
                    duration_s,
                    warmup_s,
                    capture_trajectory=True,
                )
            )
    if suite in {"rapid", "all"}:
        for controller in ALGORITHMS.values():
            for seed in seeds:
                jobs.append(
                    base_job(
                        "rapid",
                        "Medium",
                        controller,
                        seed,
                        duration_s,
                        warmup_s,
                    )
                )
    if suite in {"baseline", "all"}:
        for demand in ("Low", "Medium", "High"):
            for controller in ALGORITHMS.values():
                for seed in seeds:
                    jobs.append(
                        base_job(
                            "baseline",
                            demand,
                            controller,
                            seed,
                            duration_s,
                            warmup_s,
                            capture_trajectory=(
                                demand == "Medium"
                                and seed == seeds[0]
                                and controller in {ALGORITHMS["B0"], ALGORITHMS["B3"]}
                            ),
                        )
                    )
    if suite in {"oversaturated", "all"}:
        for controller in ALGORITHMS.values():
            for seed in seeds:
                jobs.append(
                    base_job(
                        "oversaturated",
                        "Oversaturated",
                        controller,
                        seed,
                        duration_s,
                        warmup_s,
                    )
                )
    if suite in {"disturbance", "all"}:
        scale = 0.25
        for disturbance, demand, profile in (
            ("roadwork", "High", "S04"),
            ("event_dispersal", "Medium", "S03"),
        ):
            for controller in (ALGORITHMS["B0"], ALGORITHMS["B2"], ALGORITHMS["B3"]):
                for seed in seeds:
                    jobs.append(
                        FormalJob(
                            suite="disturbance",
                            scenario="xiongan_rongdong_20",
                            demand=demand,
                            profile=profile,
                            controller=controller,
                            seed=seed,
                            disturbance=disturbance,
                            network_profile="N0",
                            duration_s=duration_s,
                            warmup_s=warmup_s,
                            profile_mode="original",
                            disturbance_time_scale=scale,
                        )
                    )
    if suite in {"communication", "all"}:
        profiles = ("N0", "LAT100", "LAT200", "JITTER50", "LOSS5", "LOSS10", "CLOUD60")
        for profile in profiles:
            for seed in seeds:
                faults: tuple[dict[str, Any], ...] = ()
                if profile == "CLOUD60":
                    faults = (
                        {
                            "fault_type": "cloud_offline",
                            "start_s": max(warmup_s, duration_s * 0.4),
                            "duration_s": min(60.0, duration_s * 0.2),
                            "parameters": {},
                        },
                    )
                jobs.append(
                    FormalJob(
                        suite="communication",
                        scenario="xiongan_rongdong_20",
                        demand="Medium",
                        profile=DEMANDS["Medium"]["profile"],
                        controller=ALGORITHMS["B3"],
                        seed=seed,
                        disturbance="none",
                        network_profile=profile,
                        duration_s=duration_s,
                        warmup_s=warmup_s,
                        scheduled_faults=faults,
                        include_communication_events=True,
                    )
                )
    if suite in {"system", "all"}:
        jobs.append(
            FormalJob(
                suite="system",
                scenario="xiongan_rongdong_20",
                demand="Medium",
                profile=DEMANDS["Medium"]["profile"],
                controller=ALGORITHMS["B3"],
                seed=seeds[0],
                disturbance="none",
                network_profile="N0",
                duration_s=duration_s,
                warmup_s=warmup_s,
                isolate_algorithms=True,
                publish_feedback_to_bus=True,
                publish_runtime_telemetry_to_bus=True,
                include_communication_events=True,
                surrogate_safety_interval_s=1.0,
            )
        )
    if not jobs:
        raise ValueError(f"unsupported suite: {suite}")
    unique: dict[str, FormalJob] = {job.run_key: job for job in jobs}
    return list(unique.values())


def base_job(
    suite: str,
    demand: str,
    controller: str,
    seed: int,
    duration_s: float,
    warmup_s: float,
    *,
    capture_trajectory: bool = False,
) -> FormalJob:
    return FormalJob(
        suite=suite,
        scenario="xiongan_rongdong_20",
        demand=demand,
        profile=str(DEMANDS[demand]["profile"]),
        controller=controller,
        seed=seed,
        disturbance="none",
        network_profile="N0",
        duration_s=duration_s,
        warmup_s=warmup_s,
        capture_trajectory=capture_trajectory,
    )


def next_attempt(job: FormalJob) -> tuple[str, Path]:
    existing = sorted(RAW_DIR.glob(f"{job.run_key}-a[0-9][0-9]"))
    attempt = len(existing) + 1
    experiment_id = f"{job.run_key}-a{attempt:02d}"
    return experiment_id, RAW_DIR / experiment_id


def completed_run_keys() -> set[str]:
    completed: set[str] = set()
    for status_path in RAW_DIR.glob("*/status.json"):
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
            config = json.loads((status_path.parent / "run_config.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if status.get("status") == "completed":
            completed.add(str(config.get("run_key", "")))
    return completed


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_metadata() -> dict[str, Any]:
    def run(*args: str) -> str:
        return subprocess.check_output(
            ["git", "-C", str(WORKSPACE), *args],
            text=True,
            encoding="utf-8",
            errors="replace",
        ).strip()

    return {
        "commit": run("rev-parse", "HEAD"),
        "branch": run("branch", "--show-current"),
        "dirty": bool(run("status", "--porcelain", "--untracked-files=no")),
    }
