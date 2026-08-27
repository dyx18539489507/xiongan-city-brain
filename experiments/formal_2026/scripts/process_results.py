"""Rebuild formal metrics and statistics exclusively from immutable raw runs."""

from __future__ import annotations

import csv
import json
import math
import statistics
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Any

from scipy import stats

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from formal_common import (  # noqa: E402
    METADATA_DIR,
    PROCESSED_DIR,
    RAW_DIR,
    TABLES_DIR,
    ensure_directories,
    sha256_file,
)

NA = "NA"
METRICS = (
    "travel_time_s",
    "waiting_time_s",
    "delay_s",
    "average_speed_m_s",
    "avg_queue_vehicles",
    "max_queue_vehicles",
    "p95_queue_vehicles",
    "avg_queue_m",
    "max_queue_m",
    "throughput_veh_h",
    "completed_trips",
    "unfinished_trips",
    "fuel_mg",
    "co2_mg",
    "nox_mg",
    "collisions",
    "teleports",
    "emergency_braking",
    "unsafe_command_rejections",
    "signal_actions_modified",
    "signal_actions_rejected",
    "communication_drop_count",
    "runtime_s",
    "simulation_realtime_factor",
)


def main() -> int:
    ensure_directories()
    rows: list[dict[str, Any]] = []
    validation: list[dict[str, Any]] = []
    for run_dir in sorted(RAW_DIR.iterdir() if RAW_DIR.is_dir() else []):
        if not run_dir.is_dir() or not (run_dir / "status.json").is_file():
            continue
        status = read_json(run_dir / "status.json")
        config = read_json(run_dir / "run_config.json")
        hash_ok, hash_detail = verify_hashes(run_dir)
        validation.append(
            {
                "experiment_id": status.get("experiment_id"),
                "status": status.get("status"),
                "hash_valid": hash_ok,
                "detail": hash_detail,
            }
        )
        if status.get("status") != "completed" or not hash_ok:
            continue
        result_path = run_dir / "result.json"
        if not result_path.is_file():
            continue
        result = read_json(result_path)
        rows.append(process_run(run_dir, config, status, result))
    write_csv(PROCESSED_DIR / "benchmark_summary.csv", rows)
    write_csv(METADATA_DIR / "raw_validation.csv", validation)
    aggregates = aggregate(rows)
    write_csv(TABLES_DIR / "aggregate_statistics.csv", aggregates)
    paired = paired_comparisons(rows)
    write_csv(TABLES_DIR / "paired_comparisons.csv", paired)
    rapid = [item for item in aggregates if item["suite"] == "rapid"]
    write_csv(TABLES_DIR / "rapid_core_results.csv", rapid)
    snapshot = {
        "processed_run_count": len(rows),
        "completed_by_suite": count_by(rows, "suite"),
        "completed_by_controller": count_by(rows, "controller_code"),
        "aggregate_statistics": aggregates,
        "paired_comparisons": paired,
        "raw_validation": validation,
    }
    (PROCESSED_DIR / "result_snapshot.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"processed={len(rows)} aggregates={len(aggregates)} paired={len(paired)}",
        flush=True,
    )
    return 0


def process_run(
    run_dir: Path,
    config: dict[str, Any],
    status: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    warmup = float(config["warmup_s"])
    duration = float(config["duration_s"])
    samples = [
        sample
        for sample in result.get("samples", [])
        if isinstance(sample, dict) and warmup < float(sample.get("simulation_time_s", -1)) <= duration
    ]
    trip_metrics = parse_tripinfo(run_dir / "tripinfo.xml", warmup, duration)
    safety = parse_statistics(run_dir / "statistics.xml")
    queues = numeric(samples, "total_queue_vehicles")
    queue_m = numeric(samples, "total_queue_m")
    speeds = numeric(samples, "mean_speed_m_s")
    engine_metrics = result.get("metrics", {})
    eval_hours = (duration - warmup) / 3600.0
    completed = trip_metrics["completed_trips"]
    row: dict[str, Any] = {
        "experiment_id": status["experiment_id"],
        "run_key": config["run_key"],
        "suite": config["suite"],
        "scenario": config["scenario"],
        "demand": config["demand"],
        "profile": config["profile"],
        "controller": config["controller"],
        "controller_code": config["controller_code"],
        "seed": config["seed"],
        "disturbance": config["disturbance"],
        "network_profile": config["network_profile"],
        "duration_s": duration,
        "warmup_s": warmup,
        "travel_time_s": trip_metrics["travel_time_s"],
        "waiting_time_s": trip_metrics["waiting_time_s"],
        "delay_s": trip_metrics["delay_s"],
        "average_speed_m_s": mean_or_na(speeds),
        "avg_queue_vehicles": mean_or_na(queues),
        "max_queue_vehicles": max(queues) if queues else NA,
        "p95_queue_vehicles": percentile(queues, 0.95),
        "avg_queue_m": mean_or_na(queue_m),
        "max_queue_m": max(queue_m) if queue_m else NA,
        "throughput_veh_h": completed / eval_hours if eval_hours > 0 else NA,
        "completed_trips": completed,
        "unfinished_trips": trip_metrics["unfinished_trips"],
        "fuel_mg": sum(numeric(samples, "fuel_mg")) if samples else NA,
        "co2_mg": sum(numeric(samples, "co2_mg")) if samples else NA,
        "nox_mg": sum(numeric(samples, "nox_mg")) if samples else NA,
        "collisions": safety.get("collisions", NA),
        "teleports": safety.get("teleports", NA),
        "emergency_braking": safety.get("emergency_braking", NA),
        "unsafe_command_rejections": sum(numeric(samples, "signal_action_rejected_count"))
        + sum(numeric(samples, "guidance_rejection_count")),
        "signal_actions_modified": sum(numeric(samples, "signal_action_modified_count")),
        "signal_actions_rejected": sum(numeric(samples, "signal_action_rejected_count")),
        "communication_drop_count": engine_metrics.get("communication_drop_count", NA),
        "runtime_s": status.get("wall_duration_s", NA),
        "simulation_realtime_factor": status.get("simulation_realtime_factor", NA),
        "raw_data_path": str(run_dir.resolve()),
    }
    return row


def parse_tripinfo(path: Path, warmup: float, duration: float) -> dict[str, Any]:
    if not path.is_file():
        return trip_na()
    root = ET.parse(path).getroot()
    motor = []
    unfinished = 0
    for trip in root.findall("tripinfo"):
        type_id = (trip.get("vType") or "").lower()
        if "bicycle" in type_id:
            continue
        depart = float(trip.get("depart", "-1"))
        arrival = float(trip.get("arrival", "-1"))
        if arrival < 0:
            if depart >= warmup:
                unfinished += 1
            continue
        if depart >= warmup and arrival <= duration:
            motor.append(trip)
    if not motor:
        return {**trip_na(), "completed_trips": 0, "unfinished_trips": unfinished}
    return {
        "travel_time_s": statistics.fmean(float(item.get("duration", "0")) for item in motor),
        "waiting_time_s": statistics.fmean(
            float(item.get("waitingTime", "0")) for item in motor
        ),
        "delay_s": statistics.fmean(float(item.get("timeLoss", "0")) for item in motor),
        "completed_trips": len(motor),
        "unfinished_trips": unfinished,
    }


def trip_na() -> dict[str, Any]:
    return {
        "travel_time_s": NA,
        "waiting_time_s": NA,
        "delay_s": NA,
        "completed_trips": 0,
        "unfinished_trips": 0,
    }


def parse_statistics(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    root = ET.parse(path).getroot()
    teleports = root.find("teleports")
    safety = root.find("safety")
    return {
        "teleports": int(teleports.get("total", "0")) if teleports is not None else NA,
        "collisions": int(safety.get("collisions", "0")) if safety is not None else NA,
        "emergency_braking": (
            int(safety.get("emergencyBraking", "0")) if safety is not None else NA
        ),
    }


def aggregate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    keys = ("suite", "scenario", "demand", "controller_code", "controller", "disturbance", "network_profile")
    for row in rows:
        groups[tuple(row[key] for key in keys)].append(row)
    output = []
    for group_key, group_rows in sorted(groups.items(), key=lambda item: tuple(map(str, item[0]))):
        base = dict(zip(keys, group_key, strict=True)) | {"n": len(group_rows)}
        for metric in METRICS:
            values = [float(row[metric]) for row in group_rows if is_number(row.get(metric))]
            summary = summarize(values)
            for name, value in summary.items():
                base[f"{metric}_{name}"] = value
        output.append(base)
    return output


def paired_comparisons(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    lower_better = {"avg_queue_vehicles", "max_queue_vehicles", "p95_queue_vehicles", "fuel_mg", "co2_mg"}
    higher_better = {"average_speed_m_s", "throughput_veh_h", "completed_trips"}
    rapid = [row for row in rows if row["suite"] == "rapid"]
    by_controller = defaultdict(dict)
    for row in rapid:
        by_controller[row["controller_code"]][int(row["seed"])] = row
    baseline = by_controller.get("B0", {})
    for controller in ("B1", "B2", "B3"):
        for metric in sorted(lower_better | higher_better):
            pairs = [
                (float(baseline[seed][metric]), float(by_controller[controller][seed][metric]))
                for seed in sorted(set(baseline) & set(by_controller[controller]))
                if is_number(baseline[seed].get(metric))
                and is_number(by_controller[controller][seed].get(metric))
            ]
            if not pairs:
                continue
            b_values = [item[0] for item in pairs]
            x_values = [item[1] for item in pairs]
            b_mean = statistics.fmean(b_values)
            x_mean = statistics.fmean(x_values)
            improvement = (
                (b_mean - x_mean) / b_mean * 100
                if metric in lower_better and b_mean != 0
                else (x_mean - b_mean) / b_mean * 100
                if metric in higher_better and b_mean != 0
                else NA
            )
            t_p = stats.ttest_rel(b_values, x_values).pvalue if len(pairs) >= 2 else math.nan
            try:
                w_p = stats.wilcoxon(b_values, x_values).pvalue if len(pairs) >= 2 else math.nan
            except ValueError:
                w_p = math.nan
            output.append(
                {
                    "suite": "rapid",
                    "baseline": "B0",
                    "controller": controller,
                    "metric": metric,
                    "n_pairs": len(pairs),
                    "baseline_mean": b_mean,
                    "controller_mean": x_mean,
                    "improvement_percent": improvement,
                    "paired_t_p": t_p,
                    "wilcoxon_p": w_p,
                }
            )
    return output


def summarize(values: list[float]) -> dict[str, Any]:
    if not values:
        return {key: NA for key in ("mean", "std", "min", "max", "ci95_low", "ci95_high")}
    mean = statistics.fmean(values)
    std = statistics.stdev(values) if len(values) > 1 else 0.0
    half = stats.t.ppf(0.975, len(values) - 1) * std / math.sqrt(len(values)) if len(values) > 1 else 0.0
    return {
        "mean": mean,
        "std": std,
        "min": min(values),
        "max": max(values),
        "ci95_low": mean - half,
        "ci95_high": mean + half,
    }


def verify_hashes(run_dir: Path) -> tuple[bool, str]:
    manifest = run_dir / "SHA256SUMS.txt"
    if not manifest.is_file():
        return False, "missing SHA256SUMS.txt"
    for line in manifest.read_text(encoding="ascii").splitlines():
        expected, relative = line.split("  ", 1)
        path = run_dir / relative
        if not path.is_file() or sha256_file(path) != expected:
            return False, f"mismatch:{relative}"
    return True, "ok"


def numeric(rows: list[dict[str, Any]], key: str) -> list[float]:
    return [float(row[key]) for row in rows if is_number(row.get(key))]


def mean_or_na(values: list[float]) -> float | str:
    return statistics.fmean(values) if values else NA


def percentile(values: list[float], proportion: float) -> float | str:
    if not values:
        return NA
    ordered = sorted(values)
    index = (len(ordered) - 1) * proportion
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    result: dict[str, int] = defaultdict(int)
    for row in rows:
        result[str(row[key])] += 1
    return dict(result)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    fields = list(rows[0])
    with path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
