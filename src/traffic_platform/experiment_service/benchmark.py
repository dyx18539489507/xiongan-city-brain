"""Fair multi-algorithm benchmark orchestration and evidence summaries."""

import asyncio
import csv
import html
import json
import math
import statistics
from pathlib import Path
from typing import Any

from traffic_platform.experiment_service.engine import ExperimentRunner, smoke_config


async def run_benchmark(
    *,
    sumo_home: Path,
    algorithms: list[str],
    seeds: list[int],
    duration_s: float,
    output_dir: Path,
) -> dict[str, Any]:
    """Run a fair matrix where only the algorithm changes within each seed."""

    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for seed in seeds:
        for algorithm in algorithms:
            config = smoke_config(
                algorithm,
                duration_s=duration_s,
                seed=seed,
                result_root=output_dir / "runs",
            )
            result = await ExperimentRunner(config, sumo_home=sumo_home).run()
            metrics = result["metrics"]
            if not isinstance(metrics, dict):
                raise TypeError("experiment metrics must be a dictionary")
            rows.append(
                {
                    "experiment_id": result["experiment_id"],
                    "scenario_id": result["scenario_id"],
                    "algorithm": algorithm,
                    "seed": seed,
                    "duration_s": duration_s,
                    **metrics,
                }
            )
            await asyncio.sleep(0)
    matrix = {
        "schema_version": "1.0",
        "actual_run": True,
        "fairness_controls": {
            "same_network": True,
            "same_od_and_departures_within_seed": True,
            "same_vehicle_types": True,
            "same_duration": True,
            "same_disturbances": True,
            "only_algorithm_changes": True,
        },
        "algorithms": algorithms,
        "seeds": seeds,
        "duration_s": duration_s,
        "rows": rows,
        "aggregate_95ci": _aggregate_confidence_intervals(rows, algorithms),
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
        f"<td>{int(float(row.get('completed_trips', 0)))}</td>"
        "</tr>"
        for row in rows
    )
    (output_dir / "benchmark.html").write_text(
        """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>Phase 1 基准实验</title><style>
body{font-family:system-ui;background:#071521;color:#d9efff;padding:32px}
table{border-collapse:collapse;width:100%}th,td{padding:9px;border-bottom:1px solid #27414f}
</style></head><body><h1>Phase 1 实际基准实验</h1>
<p>同一种子下保持路网、OD、车辆、时长和扰动一致。只改变算法。</p>
<table><thead><tr><th>算法</th><th>种子</th><th>平均速度 m/s</th>
<th>平均排队 veh</th><th>完成车辆</th></tr></thead><tbody>"""
        + table_rows
        + "</tbody></table></body></html>",
        encoding="utf-8",
    )
    return matrix


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
            values = [float(row[key]) for row in algorithm_rows if key in row]
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


def _student_t_critical_95(degrees_of_freedom: int) -> float:
    table = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571}
    if degrees_of_freedom <= 0:
        return 0.0
    return table.get(degrees_of_freedom, 1.96)
