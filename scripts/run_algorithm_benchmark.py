"""Run the formal algorithm matrix independently from the API process."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psutil

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE / "src") not in sys.path:
    sys.path.insert(0, str(WORKSPACE / "src"))

from traffic_platform.experiment_service.benchmark import run_benchmark  # noqa: E402

DEFAULT_ALGORITHMS = (
    "fixed-time",
    "actuated-control",
    "max-pressure",
    "coordinated-max-pressure",
)
DEFAULT_SEEDS = (11, 23, 37, 41, 59)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", required=True, help="Benchmark directory identifier")
    parser.add_argument("--duration", type=float, default=1800.0)
    parser.add_argument("--warmup", type=float, default=600.0)
    parser.add_argument("--seeds", nargs="+", type=int, default=DEFAULT_SEEDS)
    parser.add_argument("--algorithms", nargs="+", default=DEFAULT_ALGORITHMS)
    parser.add_argument("--sumo-home", type=Path, default=WORKSPACE / ".tools" / "sumo")
    return parser.parse_args()


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def write_status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def matching_runner_is_active(benchmark_id: str, status_path: Path) -> bool:
    if not status_path.is_file():
        return False
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
        pid = int(status.get("pid", 0))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False
    if pid <= 0 or pid == os.getpid() or not psutil.pid_exists(pid):
        return False
    try:
        command = psutil.Process(pid).cmdline()
    except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
        return False
    return benchmark_id in command and Path(__file__).name in " ".join(command)


async def run(args: argparse.Namespace) -> int:
    benchmark_id = str(args.id).strip()
    if not benchmark_id or Path(benchmark_id).name != benchmark_id:
        raise ValueError("--id must be a single directory name")
    if len(set(args.algorithms)) != len(args.algorithms):
        raise ValueError("algorithms must be unique")
    if len(set(args.seeds)) != len(args.seeds):
        raise ValueError("seeds must be unique")

    sumo_home = args.sumo_home.resolve()
    if not (sumo_home / "bin" / "sumo.exe").is_file():
        raise FileNotFoundError(f"SUMO executable not found under {sumo_home}")

    output_dir = WORKSPACE / "results" / "benchmarks" / benchmark_id
    status_path = output_dir / "runner-status.json"
    if matching_runner_is_active(benchmark_id, status_path):
        raise RuntimeError(f"benchmark runner {benchmark_id} is already active")

    os.chdir(WORKSPACE)
    os.environ["SUMO_HOME"] = str(sumo_home)
    total_runs = len(args.algorithms) * len(args.seeds)
    started_at = utc_now()
    status: dict[str, Any] = {
        "schema_version": "1.0",
        "id": benchmark_id,
        "status": "running",
        "pid": os.getpid(),
        "started_at": started_at,
        "updated_at": started_at,
        "algorithms": list(args.algorithms),
        "seeds": list(args.seeds),
        "duration_s": args.duration,
        "warmup_s": args.warmup,
        "completed_runs": 0,
        "total_runs": total_runs,
        "progress": 0,
        "message": "Preparing the formal paired benchmark matrix",
        "latest_row": None,
        "error": None,
    }
    write_status(status_path, status)

    def progress(completed: int, total: int, row: dict[str, Any]) -> None:
        status.update(
            updated_at=utc_now(),
            completed_runs=completed,
            total_runs=total,
            progress=round(completed / max(1, total) * 100),
            message=(
                f"Completed {completed}/{total}: "
                f"{row['algorithm']} seed {row['seed']}"
            ),
            latest_row=row,
        )
        write_status(status_path, status)

    try:
        matrix = await run_benchmark(
            sumo_home=sumo_home,
            algorithms=list(args.algorithms),
            seeds=list(args.seeds),
            duration_s=args.duration,
            warmup_s=args.warmup,
            output_dir=output_dir,
            progress=progress,
        )
    except BaseException as exc:
        status.update(
            status="failed",
            updated_at=utc_now(),
            message="Formal paired benchmark failed",
            error=f"{type(exc).__name__}: {exc}",
            traceback="".join(traceback.format_exception(exc)),
        )
        write_status(status_path, status)
        raise

    status.update(
        status="completed",
        updated_at=utc_now(),
        completed_runs=total_runs,
        progress=100,
        message="Formal paired benchmark completed",
        verdict=matrix.get("b3_verdict"),
        error=None,
    )
    write_status(status_path, status)
    return 0


def main() -> int:
    return asyncio.run(run(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
