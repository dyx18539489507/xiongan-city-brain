"""Small dependency-light report renderer for reproducible experiment evidence."""

import csv
import html
import json
from pathlib import Path
from typing import Any


def _svg_line(samples: list[dict[str, Any]], key: str, title: str) -> str:
    width, height = 800, 260
    if not samples:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
            f'height="{height}"><text x="20" y="40">尚未运行</text></svg>'
        )
    values = [float(sample[key]) for sample in samples]
    low, high = min(values), max(values)
    span = max(high - low, 1e-9)
    points = []
    for index, value in enumerate(values):
        x = 40 + index * (width - 80) / max(1, len(values) - 1)
        y = height - 35 - (value - low) / span * (height - 75)
        points.append(f"{x:.1f},{y:.1f}")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        'viewBox="0 0 800 260">'
        '<rect width="800" height="260" fill="#071521"/>'
        f'<text x="40" y="25" fill="#d9efff" font-family="sans-serif">{html.escape(title)}</text>'
        '<line x1="40" y1="225" x2="760" y2="225" stroke="#446477"/>'
        f'<polyline points="{" ".join(points)}" fill="none" stroke="#39d9b5" '
        'stroke-width="3"/>'
        f'<text x="40" y="248" fill="#9bb7c8" font-family="sans-serif">{low:.2f}</text>'
        f'<text x="700" y="248" fill="#9bb7c8" font-family="sans-serif">{high:.2f}</text>'
        "</svg>"
    )


def generate_report(
    result: dict[str, Any],
    output_dir: Path,
) -> dict[str, str]:
    """Write report artifacts derived only from one actual result dictionary."""

    output_dir.mkdir(parents=True, exist_ok=True)
    raw_json = output_dir / "result.json"
    raw_json.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary_csv = output_dir / "summary.csv"
    metrics = result.get("metrics", {"status": "尚未运行"})
    with summary_csv.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.writer(target)
        writer.writerow(["metric", "value"])
        writer.writerows(sorted(metrics.items()))
    samples = result.get("samples", [])
    speed_chart = output_dir / "mean_speed.svg"
    speed_chart.write_text(
        _svg_line(samples, "mean_speed_m_s", "Network mean speed (m/s)"),
        encoding="utf-8",
    )
    queue_chart = output_dir / "total_queue.svg"
    queue_chart.write_text(
        _svg_line(samples, "total_queue_vehicles", "Total queue (vehicles)"),
        encoding="utf-8",
    )
    report = output_dir / "report.html"
    metric_rows = "".join(
        f"<tr><th>{html.escape(str(key))}</th><td>{html.escape(str(value))}</td></tr>"
        for key, value in sorted(metrics.items())
    )
    manifest = html.escape(
        json.dumps(result.get("manifest", {}), ensure_ascii=False, indent=2)
    )
    report.write_text(
        f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>车路云实验报告</title>
<style>
body{{font-family:system-ui,sans-serif;background:#071521;color:#d9efff;margin:0;padding:32px}}
main{{max-width:1080px;margin:auto}}h1{{font-size:30px}}p{{color:#9bb7c8}}
table{{border-collapse:collapse;width:100%;background:#0c2231}}
th,td{{padding:10px;border-bottom:1px solid #244253;text-align:left}}
img{{max-width:100%;margin-top:24px}}pre{{white-space:pre-wrap;background:#0c2231;padding:16px}}
</style></head><body><main>
<h1>车路云协同实验报告</h1>
<p>实验 {html.escape(str(result.get("experiment_id", "unknown")))}
 · 算法 {html.escape(str(result.get("algorithm", "unknown")))}
 · 本页只展示本次实际运行输出。</p>
<table>{metric_rows}</table>
<img src="mean_speed.svg" alt="平均速度曲线">
<img src="total_queue.svg" alt="排队曲线">
<h2>可追溯清单</h2><pre>{manifest}</pre>
</main></body></html>""",
        encoding="utf-8",
    )
    return {
        "json": str(raw_json),
        "csv": str(summary_csv),
        "html": str(report),
        "speed_chart": str(speed_chart),
        "queue_chart": str(queue_chart),
    }

