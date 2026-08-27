"""Run append-only formal SUMO experiment suites with auditable metadata."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import csv
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import psutil

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from formal_common import (  # noqa: E402
    CONFIG_DIR,
    METADATA_DIR,
    NETWORK_PROFILES,
    RAW_DIR,
    WORKSPACE,
    FormalJob,
    build_jobs,
    completed_run_keys,
    ensure_directories,
    git_metadata,
    load_protocol,
    next_attempt,
    sha256_file,
    utc_now,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        choices=(
            "pilot",
            "rapid",
            "baseline",
            "oversaturated",
            "disturbance",
            "communication",
            "system",
            "all",
        ),
        default="pilot",
    )
    parser.add_argument("--duration", type=float)
    parser.add_argument("--warmup", type=float)
    parser.add_argument("--seeds", nargs="+", type=int)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--rerun-completed", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ensure_directories()
    protocol = load_protocol()
    defaults = protocol["pilot"] if args.suite in {"pilot", "rapid"} else protocol["formal_candidate"]
    duration_s = float(args.duration if args.duration is not None else defaults["duration_s"])
    warmup_s = float(args.warmup if args.warmup is not None else defaults["warmup_s"])
    seeds = tuple(args.seeds or protocol["seeds"])
    if args.workers < 1 or args.workers > int(protocol["runner"]["max_parallel_workers"]):
        raise ValueError(
            f"workers must be in [1, {protocol['runner']['max_parallel_workers']}]"
        )
    jobs = build_jobs(
        args.suite,
        duration_s=duration_s,
        warmup_s=warmup_s,
        seeds=seeds,
    )
    completed = completed_run_keys()
    selected = [
        job for job in jobs if args.rerun_completed or job.run_key not in completed
    ]
    write_planned_matrix(jobs, selected)
    print(
        f"suite={args.suite} planned={len(jobs)} selected={len(selected)} "
        f"duration={duration_s:g}s warmup={warmup_s:g}s workers={args.workers}",
        flush=True,
    )
    if args.dry_run or not selected:
        rebuild_campaign_tables()
        return 0

    attempts: list[tuple[FormalJob, str, Path]] = []
    for job in selected:
        experiment_id, run_dir = next_attempt(job)
        attempts.append((job, experiment_id, run_dir))

    outcomes: list[dict[str, Any]] = []
    if args.workers == 1:
        for index, attempt in enumerate(attempts, start=1):
            job, experiment_id, run_dir = attempt
            print(f"[{index}/{len(attempts)}] starting {experiment_id}", flush=True)
            outcome = run_one(job.to_dict(), experiment_id, str(run_dir))
            outcomes.append(outcome)
            append_campaign_manifest(outcome)
            print_outcome(outcome)
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            future_map = {
                executor.submit(run_one, job.to_dict(), experiment_id, str(run_dir)): (
                    experiment_id,
                    run_dir,
                    job,
                )
                for job, experiment_id, run_dir in attempts
            }
            for future in as_completed(future_map):
                experiment_id, run_dir, job = future_map[future]
                try:
                    outcome = future.result()
                except BaseException as exc:
                    outcome = parent_failure(job, experiment_id, run_dir, exc)
                outcomes.append(outcome)
                append_campaign_manifest(outcome)
                print_outcome(outcome)
    rebuild_campaign_tables()
    failed = sum(item["status"] != "completed" for item in outcomes)
    return 1 if failed else 0


def run_one(job_value: dict[str, Any], experiment_id: str, run_dir_value: str) -> dict[str, Any]:
    """Execute one run in the current or a process-pool worker."""

    from traffic_platform.communication_emulator.channel import ChannelConfig
    from traffic_platform.experiment_service.engine import (
        ExperimentConfig,
        ExperimentControl,
        ExperimentRunner,
        ScheduledFault,
    )
    from traffic_platform.messaging.emulated import EmulatedMessageBus

    os.chdir(WORKSPACE)
    run_dir = Path(run_dir_value)
    run_dir.mkdir(parents=True, exist_ok=False)
    started_at = utc_now()
    started_wall = time.perf_counter()
    job_value = {**job_value, "experiment_id": experiment_id, "started_at": started_at}
    write_json(run_dir / "run_config.json", job_value)
    environment = environment_metadata()
    write_json(run_dir / "environment.json", environment)
    log_path = run_dir / "execution.log"
    trajectory_handle = None
    try:
        sumo_home = Path(environment["sumo_home"])
        profile = str(job_value["profile"])
        generated = WORKSPACE / "scenarios" / "generated" / "xiongan_rongdong_20"
        config_file = generated / f"xiongan_rongdong_20.{profile}.sumocfg"
        profile_file = (
            CONFIG_DIR / "profiles_no_disturbance.yaml"
            if job_value["profile_mode"] == "no_disturbance"
            else WORKSPACE / "scenarios" / "configs" / "presets" / "S01-S07.yaml"
        )
        channel_config = ChannelConfig(**NETWORK_PROFILES[str(job_value["network_profile"])])
        control = ExperimentControl()
        control.channel_config = channel_config
        scheduled = tuple(
            ScheduledFault(**item) for item in job_value.get("scheduled_faults", ())
        )
        config = ExperimentConfig(
            experiment_id=experiment_id,
            scenario_id="xiongan_rongdong_20",
            algorithm=str(job_value["controller"]),
            seed=int(job_value["seed"]),
            duration_s=float(job_value["duration_s"]),
            config_file=config_file,
            selection_file=generated / "controlled_intersections.json",
            result_dir=run_dir,
            scenario_definition_file=(
                WORKSPACE / "scenarios" / "configs" / "xiongan_rongdong_20.yaml"
            ),
            scenario_profile_code=profile,
            scenario_profile_file=profile_file,
            gui=False,
            disturbance_time_scale=float(job_value["disturbance_time_scale"]),
            scheduled_faults=scheduled,
            isolate_algorithms=bool(job_value["isolate_algorithms"]),
            publish_feedback_to_bus=bool(job_value["publish_feedback_to_bus"]),
            publish_runtime_telemetry_to_bus=bool(
                job_value["publish_runtime_telemetry_to_bus"]
            ),
            include_communication_events=bool(job_value["include_communication_events"]),
            surrogate_safety_interval_s=float(job_value["surrogate_safety_interval_s"]),
            sumo_extra_args=("--device.emissions.probability", "1.0"),
        )
        if job_value["capture_trajectory"]:
            trajectory_handle = (run_dir / "trajectory.ndjson").open(
                "x", encoding="utf-8", newline="\n"
            )

        async def persist(kind: str, payload: dict[str, object]) -> None:
            if kind == "trajectory" and trajectory_handle is not None:
                trajectory_handle.write(
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
                )

        with (
            log_path.open("x", encoding="utf-8", newline="\n") as log,
            contextlib.redirect_stdout(log),
            contextlib.redirect_stderr(log),
        ):
            result = asyncio.run(
                ExperimentRunner(
                    config,
                    sumo_home=sumo_home,
                    bus=EmulatedMessageBus(channel_config, seed=int(job_value["seed"])),
                    control=control,
                    persistence_callback=persist if trajectory_handle is not None else None,
                ).run()
            )
        if trajectory_handle is not None:
            trajectory_handle.flush()
            trajectory_handle.close()
            trajectory_handle = None
        ended_at = utc_now()
        wall_duration_s = time.perf_counter() - started_wall
        metrics = result.get("metrics") if isinstance(result, dict) else None
        status = {
            "experiment_id": experiment_id,
            "run_key": job_value["run_key"],
            "status": "completed",
            "exit_status": 0,
            "started_at": started_at,
            "ended_at": ended_at,
            "wall_duration_s": wall_duration_s,
            "simulation_realtime_factor": (
                metrics.get("simulation_realtime_factor") if isinstance(metrics, dict) else None
            ),
            "raw_data_path": str(run_dir.resolve()),
        }
        write_json(run_dir / "status.json", status)
        write_hash_manifest(run_dir)
        return {**status, **job_value}
    except BaseException as exc:
        if trajectory_handle is not None:
            trajectory_handle.close()
        ended_at = utc_now()
        with log_path.open("a", encoding="utf-8", newline="\n") as log:
            log.write("\nFORMAL_RUN_FAILURE\n")
            log.write("".join(traceback.format_exception(exc)))
        status = {
            "experiment_id": experiment_id,
            "run_key": job_value["run_key"],
            "status": "failed",
            "exit_status": 1,
            "failure_type": type(exc).__name__,
            "exception": str(exc),
            "started_at": started_at,
            "ended_at": ended_at,
            "wall_duration_s": time.perf_counter() - started_wall,
            "raw_data_path": str(run_dir.resolve()),
            "log": str(log_path.resolve()),
            "retry": False,
        }
        write_json(run_dir / "status.json", status)
        write_hash_manifest(run_dir)
        return {**status, **job_value}


def environment_metadata() -> dict[str, Any]:
    sumo_home = locate_sumo_home()
    sumo_binary = sumo_home / "bin" / "sumo.exe"
    sumo_version = subprocess.check_output(
        [str(sumo_binary), "--version"],
        text=True,
        encoding="utf-8",
        errors="replace",
    ).splitlines()[0]
    packages = {}
    for name in ("pydantic", "numpy", "pandas", "scipy", "traci", "sumolib"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {
        "captured_at": utc_now(),
        "os": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER", "unknown"),
        "logical_cpu_count": psutil.cpu_count(logical=True),
        "physical_cpu_count": psutil.cpu_count(logical=False),
        "ram_total_bytes": psutil.virtual_memory().total,
        "python": platform.python_version(),
        "python_executable": sys.executable,
        "sumo_home": str(sumo_home.resolve()),
        "sumo_version": sumo_version,
        "packages": packages,
        "git": git_metadata(),
        "docker_engine_used": False,
        "mqtt_mode": "deterministic software emulation",
    }


def locate_sumo_home() -> Path:
    configured = os.environ.get("SUMO_HOME")
    candidates = [
        Path(configured) if configured else None,
        WORKSPACE
        / "exports"
        / "xiongan_3d_portable_v4"
        / "xiongan_3d_portable_v4"
        / "runtime"
        / "sumo",
    ]
    for candidate in candidates:
        if candidate is not None and (candidate / "bin" / "sumo.exe").is_file():
            return candidate.resolve()
    raise FileNotFoundError("no SUMO_HOME containing bin/sumo.exe is available")


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def write_hash_manifest(run_dir: Path) -> None:
    lines = []
    for path in sorted(item for item in run_dir.rglob("*") if item.is_file()):
        if path.name == "SHA256SUMS.txt":
            continue
        lines.append(f"{sha256_file(path)}  {path.relative_to(run_dir).as_posix()}")
    (run_dir / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="ascii")


def append_campaign_manifest(outcome: dict[str, Any]) -> None:
    path = METADATA_DIR / "experiment_manifest.jsonl"
    with path.open("a", encoding="utf-8", newline="\n") as target:
        target.write(json.dumps(outcome, ensure_ascii=False, separators=(",", ":")) + "\n")


def write_planned_matrix(jobs: list[FormalJob], selected: list[FormalJob]) -> None:
    selected_keys = {job.run_key for job in selected}
    path = METADATA_DIR / "planned_matrix.csv"
    fields = [
        "run_key",
        "suite",
        "scenario",
        "demand",
        "profile",
        "controller_code",
        "controller",
        "seed",
        "disturbance",
        "network_profile",
        "duration_s",
        "warmup_s",
        "selected_this_invocation",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        for job in jobs:
            row = job.to_dict()
            writer.writerow({key: row.get(key) for key in fields[:-1]} | {
                "selected_this_invocation": job.run_key in selected_keys
            })


def rebuild_campaign_tables() -> None:
    rows = []
    failures = []
    for run_config_path in sorted(RAW_DIR.glob("*/run_config.json")):
        try:
            config = json.loads(run_config_path.read_text(encoding="utf-8"))
            status = json.loads((run_config_path.parent / "status.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        row = {
            "Experiment": status.get("experiment_id"),
            "Scenario": config.get("scenario"),
            "Demand": config.get("demand"),
            "Controller": config.get("controller_code"),
            "Seed": config.get("seed"),
            "Disturbance": config.get("disturbance"),
            "Network Profile": config.get("network_profile"),
            "Duration": config.get("duration_s"),
            "Warmup": config.get("warmup_s"),
            "Status": status.get("status"),
            "Raw Path": str(run_config_path.parent.resolve()),
        }
        rows.append(row)
        if status.get("status") != "completed":
            failures.append(
                {
                    "experiment_id": status.get("experiment_id"),
                    "failure_type": status.get("failure_type"),
                    "exception": status.get("exception"),
                    "log": status.get("log"),
                    "retry": status.get("retry", False),
                    "final_status": status.get("status"),
                }
            )
    write_csv(METADATA_DIR / "formal_experiment_matrix.csv", rows)
    write_csv(METADATA_DIR / "experiment_failures.csv", failures)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    fields = list(rows[0])
    with path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def parent_failure(job: FormalJob, experiment_id: str, run_dir: Path, exc: BaseException) -> dict[str, Any]:
    run_dir.mkdir(parents=True, exist_ok=True)
    outcome = {
        **job.to_dict(),
        "experiment_id": experiment_id,
        "status": "failed",
        "exit_status": 1,
        "failure_type": type(exc).__name__,
        "exception": str(exc),
        "started_at": None,
        "ended_at": utc_now(),
        "wall_duration_s": None,
        "raw_data_path": str(run_dir.resolve()),
        "log": None,
        "retry": False,
    }
    write_json(run_dir / "run_config.json", outcome)
    write_json(run_dir / "status.json", outcome)
    write_hash_manifest(run_dir)
    return outcome


def print_outcome(outcome: dict[str, Any]) -> None:
    print(
        f"{outcome['experiment_id']} status={outcome['status']} "
        f"wall={outcome.get('wall_duration_s')}s",
        flush=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
