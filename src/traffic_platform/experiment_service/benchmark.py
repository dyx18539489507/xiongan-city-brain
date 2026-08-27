"""Fair multi-algorithm benchmark orchestration and evidence summaries."""

import asyncio
import csv
import hashlib
import html
import json
import math
import shutil
import statistics
import tempfile
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, TypeGuard, cast

from traffic_platform.algorithms import builtin_registry
from traffic_platform.experiment_service.engine import ExperimentRunner, smoke_config
from traffic_platform.sumo_adapter import TraciSumoAdapter

COMPARISON_METRICS: dict[str, bool] = {
    "mean_travel_time": False,
    "mean_waiting_time": False,
    "mean_queue_vehicles": False,
    "max_queue": False,
    "mean_speed": True,
    "completed_trips": True,
    "completed_vehicles": True,
    "fuel_consumption_mg": False,
    "fuel_per_completed_vehicle_mg": False,
    "co2_mg": False,
    "co2_per_completed_vehicle_mg": False,
    "nox_per_completed_vehicle_mg": False,
    "emergency_braking_per_1000_completed_vehicles": False,
    "conflicts_per_1000_completed_vehicles": False,
    "end_to_end_control_latency_ms": False,
}
B3_NAME = "coordinated-max-pressure"


async def run_benchmark(
    *,
    sumo_home: Path,
    algorithms: list[str],
    seeds: list[int],
    duration_s: float,
    output_dir: Path,
    warmup_s: float = 0.0,
    progress: Callable[[int, int, dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run a fair matrix where only the algorithm changes within each seed."""

    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    fairness_inputs: list[dict[str, Any]] = []
    completed = 0
    total = len(seeds) * len(algorithms)
    for seed in seeds:
        warmup_state: Path | None = None
        warmup_state_sha256: str | None = None
        if warmup_s > 0:
            warmup_state, warmup_state_sha256 = await _prepare_warmup_state(
                sumo_home=sumo_home,
                seed=seed,
                warmup_s=warmup_s,
                output_dir=output_dir,
            )
        for algorithm in algorithms:
            config = smoke_config(
                algorithm,
                duration_s=duration_s,
                seed=seed,
                result_root=output_dir / "runs",
            )
            config = replace(
                config,
                isolate_algorithms=False,
                publish_feedback_to_bus=False,
                publish_runtime_telemetry_to_bus=False,
                include_communication_events=False,
                surrogate_safety_interval_s=5.0,
                sumo_extra_args=(
                    ("--load-state", str(warmup_state.resolve()))
                    if warmup_state is not None
                    else ()
                ),
            )
            result = _load_completed_run(
                output_dir / "runs",
                algorithm=algorithm,
                seed=seed,
                duration_s=duration_s,
                warmup_s=warmup_s,
                warmup_state=warmup_state,
                expected_algorithm_version=next(
                    item["version"]
                    for item in builtin_registry().discover()
                    if item["name"] == algorithm
                ),
            )
            if result is None:
                result = await ExperimentRunner(config, sumo_home=sumo_home).run()
            result["benchmark_warmup_s"] = warmup_s
            result["benchmark_warmup_state_sha256"] = warmup_state_sha256
            metrics = result["metrics"]
            if not isinstance(metrics, dict):
                raise TypeError("experiment metrics must be a dictionary")
            raw_evaluation_start = result.get("evaluation_start_simulation_time_s")
            evaluation_start_s = (
                float(raw_evaluation_start)
                if isinstance(raw_evaluation_start, int | float)
                else warmup_s
            )
            row = {
                "experiment_id": result["experiment_id"],
                "scenario_id": result["scenario_id"],
                "algorithm": algorithm,
                "seed": seed,
                "duration_s": duration_s,
                "evaluation_start_s": evaluation_start_s,
                "warmup_state_sha256": warmup_state_sha256,
                **metrics,
            }
            fairness = _benchmark_input_facts(result)
            row["input_fingerprint"] = fairness["input_fingerprint"]
            rows.append(row)
            fairness_inputs.append(fairness)
            completed += 1
            if progress is not None:
                progress(completed, total, row)
            await asyncio.sleep(0)
    aggregate = _aggregate_confidence_intervals(rows, algorithms)
    pairwise = _paired_b3_comparisons(rows, algorithms)
    rankings = _rank_algorithms(aggregate, algorithms)
    fairness_controls = _fairness_controls(
        fairness_inputs,
        algorithms=algorithms,
        seeds=seeds,
        duration_s=duration_s,
    )
    matrix = {
        "schema_version": "1.0",
        "actual_run": True,
        "fairness_controls": fairness_controls,
        "input_fingerprints": {
            str(seed): sorted(
                {
                    item["input_fingerprint"]
                    for item in fairness_inputs
                    if item["seed"] == seed
                }
            )
            for seed in seeds
        },
        "algorithms": algorithms,
        "seeds": seeds,
        "duration_s": duration_s,
        "warmup_s": warmup_s,
        "rows": rows,
        "aggregate_95ci": aggregate,
        "rankings": rankings,
        "b3_pairwise": pairwise,
        "b3_verdict": _b3_verdict(
            pairwise,
            rows,
            algorithms,
            fairness_controls=fairness_controls,
        ),
    }
    (output_dir / "benchmark.json").write_text(
        json.dumps(matrix, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    keys = sorted({key for row in rows for key in row})
    with (output_dir / "benchmark.csv").open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as target:
        writer = csv.DictWriter(target, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)
    table_rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(row['algorithm']))}</td>"
        f"<td>{row['seed']}</td>"
        f"<td>{float(row.get('mean_speed', 0)):.3f}</td>"
        f"<td>{float(row.get('mean_queue_vehicles', 0)):.3f}</td>"
        f"<td>{int(float(row.get('completed_vehicles', row.get('completed_trips', 0))))}</td>"
        "</tr>"
        for row in rows
    )
    (output_dir / "benchmark.html").write_text(
        """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>Phase 1 基准实验</title><style>
body{font-family:system-ui;background:#071521;color:#d9efff;padding:32px}
table{border-collapse:collapse;width:100%}th,td{padding:9px;border-bottom:1px solid #27414f}
</style></head><body><h1>Phase 1 实际基准实验</h1>
<p>同一种子下保持预热状态、路网、OD、车辆、时长和扰动一致。只改变算法。</p>
<table><thead><tr><th>算法</th><th>种子</th><th>平均速度 m/s</th>
<th>平均排队 veh</th><th>完成车辆</th></tr></thead><tbody>"""
        + table_rows
        + "</tbody></table></body></html>",
        encoding="utf-8",
    )
    return matrix


async def _prepare_warmup_state(
    *,
    sumo_home: Path,
    seed: int,
    warmup_s: float,
    output_dir: Path,
) -> tuple[Path, str]:
    """Create one native fixed-plan SUMO state shared by every algorithm."""

    if warmup_s <= 0:
        raise ValueError("warmup_s must be positive")
    destination = output_dir / "warmup_states" / f"seed-{seed}-at-{warmup_s:g}s.xml.gz"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file():
        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        return destination, digest
    adapter = TraciSumoAdapter(
        sumo_home=sumo_home,
        label=f"benchmark-warmup-{seed}",
    )
    with tempfile.TemporaryDirectory(prefix="xiongan-benchmark-warmup-") as temporary:
        state_path = Path(temporary) / "state.xml.gz"
        try:
            await asyncio.to_thread(
                adapter.start_simulation,
                Path("scenarios/generated/xiongan_rongdong_20/xiongan_rongdong_20.sumocfg"),
                seed=seed,
            )
            await asyncio.to_thread(adapter.step, warmup_s)
            await asyncio.to_thread(adapter.save_state, state_path)
        finally:
            if adapter.running:
                await asyncio.to_thread(adapter.stop_simulation)
        shutil.copy2(state_path, destination)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    return destination, digest


def _load_completed_run(
    run_root: Path,
    *,
    algorithm: str,
    seed: int,
    duration_s: float,
    warmup_s: float,
    warmup_state: Path | None,
    expected_algorithm_version: str,
) -> dict[str, Any] | None:
    """Reuse only a complete run whose immutable evaluation inputs match."""

    expected_args = (
        ["--load-state", str(warmup_state.resolve())]
        if warmup_state is not None
        else []
    )
    for result_path in sorted(run_root.glob("*/result.json")):
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("algorithm") != algorithm or payload.get("seed") != seed:
            continue
        if (
            algorithm == B3_NAME
            and payload.get("algorithm_version") != expected_algorithm_version
        ):
            continue
        if payload.get("actual_run") is not True:
            continue
        raw_start = payload.get("evaluation_start_simulation_time_s")
        if not _is_number(raw_start) or not math.isclose(float(raw_start), warmup_s):
            continue
        options = payload.get("runner_options")
        if not isinstance(options, dict) or options.get("sumo_extra_args") != expected_args:
            continue
        manifest = payload.get("manifest")
        provenance = manifest.get("provenance") if isinstance(manifest, dict) else None
        raw_duration = provenance.get("duration_s") if isinstance(provenance, dict) else None
        if not _is_number(raw_duration) or not math.isclose(float(raw_duration), duration_s):
            continue
        samples = payload.get("samples")
        if not isinstance(samples, list) or len(samples) != round(duration_s):
            continue
        return cast(dict[str, Any], payload)
    return None


def _aggregate_confidence_intervals(
    rows: list[dict[str, Any]],
    algorithms: list[str],
) -> dict[str, dict[str, dict[str, float | int]]]:
    """Compute transparent Student-t 95% intervals across actual seed runs."""

    result: dict[str, dict[str, dict[str, float | int]]] = {}
    for algorithm in algorithms:
        algorithm_rows = [row for row in rows if row["algorithm"] == algorithm]
        numeric_keys = sorted(
            {
                key
                for row in algorithm_rows
                for key, value in row.items()
                if isinstance(value, int | float) and key not in {"seed", "duration_s"}
            }
        )
        summaries: dict[str, dict[str, float | int]] = {}
        for key in numeric_keys:
            values = [
                float(value)
                for row in algorithm_rows
                if _is_number(value := row.get(key))
            ]
            if not values:
                continue
            mean = statistics.fmean(values)
            standard_deviation = statistics.stdev(values) if len(values) > 1 else 0.0
            t_critical = _student_t_critical_95(len(values) - 1)
            half_width = (
                t_critical * standard_deviation / math.sqrt(len(values)) if len(values) > 1 else 0.0
            )
            summaries[key] = {
                "n": len(values),
                "mean": mean,
                "standard_deviation": standard_deviation,
                "ci95_low": mean - half_width,
                "ci95_high": mean + half_width,
            }
        result[algorithm] = summaries
    return result


def _paired_b3_comparisons(
    rows: list[dict[str, Any]],
    algorithms: list[str],
) -> dict[str, dict[str, dict[str, float | int | str | None]]]:
    """Compare B3 against every included baseline using common random seeds."""

    by_algorithm: dict[str, dict[int, dict[str, Any]]] = {}
    for row in rows:
        by_algorithm.setdefault(str(row["algorithm"]), {})[int(row["seed"])] = row
    b3_rows = by_algorithm.get(B3_NAME, {})
    output: dict[str, dict[str, dict[str, float | int | str | None]]] = {}
    for baseline in algorithms:
        if baseline == B3_NAME or baseline not in by_algorithm:
            continue
        metrics: dict[str, dict[str, float | int | str | None]] = {}
        baseline_rows = by_algorithm[baseline]
        common_seeds = sorted(set(baseline_rows) & set(b3_rows))
        for metric, higher_better in COMPARISON_METRICS.items():
            pairs = [
                (float(baseline_rows[seed][metric]), float(b3_rows[seed][metric]))
                for seed in common_seeds
                if _is_number(baseline_rows[seed].get(metric))
                and _is_number(b3_rows[seed].get(metric))
            ]
            if not pairs:
                continue
            improvements = [
                _benefit_percent(baseline_value, b3_value, higher_better)
                for baseline_value, b3_value in pairs
            ]
            finite_improvements = [value for value in improvements if value is not None]
            wins = sum(
                b3_value > baseline_value if higher_better else b3_value < baseline_value
                for baseline_value, b3_value in pairs
            )
            mean_improvement = (
                statistics.fmean(finite_improvements) if finite_improvements else None
            )
            ci_low, ci_high = _confidence_interval(finite_improvements)
            metrics[metric] = {
                "n": len(pairs),
                "baseline_mean": statistics.fmean(value[0] for value in pairs),
                "b3_mean": statistics.fmean(value[1] for value in pairs),
                "improvement_percent": mean_improvement,
                "ci95_low": ci_low,
                "ci95_high": ci_high,
                "win_count": wins,
                "win_rate": wins / len(pairs),
                "status": (
                    "significant_improvement"
                    if mean_improvement is not None
                    and mean_improvement > 0
                    and ci_low is not None
                    and ci_low > 0
                    else "observed_improvement"
                    if mean_improvement is not None and mean_improvement > 0
                    else "not_improved"
                ),
            }
        output[baseline] = metrics
    return output


def _rank_algorithms(
    aggregate: dict[str, dict[str, dict[str, float | int]]],
    algorithms: list[str],
) -> dict[str, list[dict[str, float | int | str]]]:
    """Rank all four algorithms per metric without collapsing unlike units."""

    output: dict[str, list[dict[str, float | int | str]]] = {}
    for metric, higher_better in COMPARISON_METRICS.items():
        values = [
            (algorithm, aggregate.get(algorithm, {}).get(metric, {}).get("mean"))
            for algorithm in algorithms
        ]
        numeric = [(algorithm, float(value)) for algorithm, value in values if _is_number(value)]
        numeric.sort(key=lambda item: item[1], reverse=higher_better)
        output[metric] = [
            {"rank": index, "algorithm": algorithm, "mean": value}
            for index, (algorithm, value) in enumerate(numeric, start=1)
        ]
    return output


def _b3_verdict(
    pairwise: dict[str, dict[str, dict[str, float | int | str | None]]],
    rows: list[dict[str, Any]],
    algorithms: list[str],
    *,
    fairness_controls: dict[str, bool],
) -> dict[str, Any]:
    required = {
        "fixed-time",
        "actuated-control",
        "max-pressure",
        B3_NAME,
    }
    seed_count = len({int(row["seed"]) for row in rows if row["algorithm"] == B3_NAME})
    if not required.issubset(algorithms) or seed_count < 3:
        return {
            "status": "insufficient_evidence",
            "label": "证据不足, 尚不能判定 B3 最优",
            "seed_count": seed_count,
            "checks": [],
        }
    if not fairness_controls or not all(fairness_controls.values()):
        return {
            "status": "not_proven",
            "label": "公平性门禁未通过, 不能判定 B3 最优",
            "seed_count": seed_count,
            "checks": [],
        }
    b3_rows = [row for row in rows if row["algorithm"] == B3_NAME]
    robust = all(
        int(row.get("algorithm_timeout_count", 0)) == 0
        and int(row.get("algorithm_failure_count", 0)) == 0
        for row in b3_rows
    )
    if not robust:
        return {
            "status": "not_proven",
            "label": "B3 存在算法超时或失败, 不能判定综合最优",
            "seed_count": seed_count,
            "checks": [],
        }
    checks: list[dict[str, Any]] = []
    for baseline in sorted(required - {B3_NAME}):
        metrics = pairwise.get(baseline, {})
        for metric in ("mean_queue_vehicles", "mean_speed"):
            evidence = metrics.get(metric)
            improvement = evidence.get("improvement_percent") if evidence else None
            win_rate = evidence.get("win_rate") if evidence else None
            passed = bool(
                _is_number(improvement)
                and improvement > 0
                and _is_number(win_rate)
                and win_rate >= 0.6
                and evidence is not None
                and evidence.get("status") == "significant_improvement"
            )
            checks.append({"baseline": baseline, "metric": metric, "passed": passed})
    passed = bool(checks) and all(check["passed"] for check in checks)
    return {
        "status": "best" if passed else "not_proven",
        "label": (
            "B3 在冻结矩阵中综合最优"
            if passed
            else "B3 尚未全面优于全部基线"
        ),
        "seed_count": seed_count,
        "checks": checks,
    }


def _benchmark_input_facts(result: dict[str, Any]) -> dict[str, Any]:
    raw_manifest = result.get("manifest")
    manifest: dict[str, Any] = raw_manifest if isinstance(raw_manifest, dict) else {}
    raw_provenance = manifest.get("provenance")
    provenance = (
        raw_provenance
        if isinstance(raw_provenance, dict)
        else {}
    )
    raw_files = manifest.get("files")
    files = raw_files if isinstance(raw_files, list) else []
    common = {
        "scenario_id": result.get("scenario_id"),
        "scenario_profile": result.get("scenario_profile"),
        "scenario_hash": manifest.get("scenario_hash"),
        "files": files,
        "seed": result.get("seed"),
        "duration_s": provenance.get("duration_s"),
        "benchmark_warmup_s": result.get("benchmark_warmup_s", 0.0),
        "benchmark_warmup_state_sha256": result.get(
            "benchmark_warmup_state_sha256"
        ),
        "runner_options": result.get("runner_options", {}),
    }
    fingerprint = hashlib.sha256(
        json.dumps(common, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    return {
        **common,
        "algorithm": result.get("algorithm"),
        "input_fingerprint": fingerprint,
    }


def _fairness_controls(
    facts: list[dict[str, Any]],
    *,
    algorithms: list[str],
    seeds: list[int],
    duration_s: float,
) -> dict[str, bool]:
    by_seed = {
        seed: [item for item in facts if int(item.get("seed", -1)) == seed]
        for seed in seeds
    }
    complete = all(
        {str(item.get("algorithm")) for item in items} == set(algorithms)
        for items in by_seed.values()
    )
    same_inputs = all(
        len({str(item.get("input_fingerprint")) for item in items}) == 1
        for items in by_seed.values()
        if items
    )
    return {
        "same_warmup_state": same_inputs,
        "same_network": same_inputs,
        "same_od_and_departures_within_seed": same_inputs,
        "same_vehicle_types": same_inputs,
        "same_duration": all(
            float(item.get("duration_s", -1)) == duration_s for item in facts
        ),
        "same_disturbances": same_inputs,
        "only_algorithm_changes": complete and same_inputs,
    }


def _confidence_interval(values: list[float]) -> tuple[float | None, float | None]:
    if len(values) < 2:
        return None, None
    mean = statistics.fmean(values)
    std = statistics.stdev(values)
    half_width = _student_t_critical_95(len(values) - 1) * std / math.sqrt(len(values))
    return mean - half_width, mean + half_width


def _benefit_percent(
    baseline: float,
    candidate: float,
    higher_better: bool,
) -> float | None:
    if baseline == 0:
        return None
    return (
        (candidate - baseline) / abs(baseline) * 100
        if higher_better
        else (baseline - candidate) / abs(baseline) * 100
    )


def _is_number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _student_t_critical_95(degrees_of_freedom: int) -> float:
    table = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571}
    if degrees_of_freedom <= 0:
        return 0.0
    return table.get(degrees_of_freedom, 1.96)
