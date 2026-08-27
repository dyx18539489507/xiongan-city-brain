"""Generate 300 dpi PNG and SVG charts from processed rapid-run statistics."""

# ruff: noqa: RUF001

from __future__ import annotations

import csv
import html
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / "tables" / "aggregate_statistics.csv"
OUTPUT = ROOT / "figures"
COLORS = {"B0": "#3B4A5A", "B1": "#2E7D6E", "B2": "#D08C32", "B3": "#B34B5E"}


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with TABLE.open(encoding="utf-8-sig", newline="") as source:
        rows = [row for row in csv.DictReader(source) if row["suite"] == "rapid"]
    rows.sort(key=lambda row: row["controller_code"])
    figures = (
        ("figure_01_average_speed", "图 1 平均速度 / Average Speed", "average_speed_m_s", "m/s"),
        ("figure_02_average_queue", "图 2 平均排队 / Average Queue", "avg_queue_vehicles", "veh"),
        ("figure_03_max_queue", "图 3 最大排队 / Maximum Queue", "max_queue_vehicles", "veh"),
        ("figure_04_fuel", "图 4 评估窗口燃油 / Fuel", "fuel_mg", "mg"),
        ("figure_05_realtime_factor", "图 5 仿真实时因子 / Real-time Factor", "simulation_realtime_factor", "x"),
    )
    generated = 0
    for filename, title, metric, unit in figures:
        values = [number(row.get(f"{metric}_mean")) for row in rows]
        if not rows or all(value is None for value in values):
            continue
        chart(filename, title, metric, unit, rows)
        generated += 1
    print(f"figures={generated}")
    return 0


def chart(filename: str, title: str, metric: str, unit: str, rows: list[dict[str, str]]) -> None:
    width, height = 1800, 1200
    margin_left, margin_right, margin_top, margin_bottom = 190, 110, 160, 190
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom
    values = [float(row[f"{metric}_mean"]) for row in rows]
    lows = [number(row.get(f"{metric}_ci95_low")) for row in rows]
    highs = [number(row.get(f"{metric}_ci95_high")) for row in rows]
    ymax = max([*values, *(value for value in highs if value is not None)], default=1.0)
    ymax = ymax * 1.22 if ymax > 0 else 1.0
    image = Image.new("RGB", (width, height), "#FFFFFF")
    draw = ImageDraw.Draw(image)
    font_path = Path("C:/Windows/Fonts/msyh.ttc")
    font_title = ImageFont.truetype(str(font_path), 48)
    font_axis = ImageFont.truetype(str(font_path), 31)
    font_label = ImageFont.truetype(str(font_path), 34)
    font_value = ImageFont.truetype(str(font_path), 28)
    draw.text((width / 2, 65), title, fill="#15212B", font=font_title, anchor="mm")
    x0, y0 = margin_left, height - margin_bottom
    draw.line((x0, margin_top, x0, y0), fill="#26343E", width=3)
    draw.line((x0, y0, width - margin_right, y0), fill="#26343E", width=3)
    for tick in range(6):
        value = ymax * tick / 5
        y = y0 - plot_h * tick / 5
        draw.line((x0, y, width - margin_right, y), fill="#DDE3E7", width=2)
        draw.text((x0 - 24, y), f"{value:.2f}", fill="#40515D", font=font_axis, anchor="rm")
    draw.text((55, margin_top + plot_h / 2), unit, fill="#40515D", font=font_axis, anchor="mm")
    slot = plot_w / max(1, len(rows))
    bar_w = slot * 0.55
    for index, row in enumerate(rows):
        code = row["controller_code"]
        value = values[index]
        cx = x0 + slot * (index + 0.5)
        top = y0 - value / ymax * plot_h
        draw.rectangle((cx - bar_w / 2, top, cx + bar_w / 2, y0), fill=COLORS[code])
        low, high = lows[index], highs[index]
        if low is not None and high is not None:
            y_low = y0 - low / ymax * plot_h
            y_high = y0 - high / ymax * plot_h
            draw.line((cx, y_low, cx, y_high), fill="#111820", width=4)
            draw.line((cx - 18, y_low, cx + 18, y_low), fill="#111820", width=4)
            draw.line((cx - 18, y_high, cx + 18, y_high), fill="#111820", width=4)
        draw.text((cx, y0 + 58), code, fill="#26343E", font=font_label, anchor="mm")
        draw.text((cx, max(margin_top + 25, top - 30)), f"{value:.3g}", fill="#15212B", font=font_value, anchor="ms")
    draw.text(
        (width / 2, height - 48),
        "误差棒：95% CI；n=5 相同 SUMO seeds；60 s 快速评估窗口",
        fill="#53636E",
        font=font_axis,
        anchor="mm",
    )
    image.save(OUTPUT / f"{filename}.png", dpi=(300, 300))
    svg_chart(OUTPUT / f"{filename}.svg", title, metric, unit, rows, ymax)


def svg_chart(
    path: Path,
    title: str,
    metric: str,
    unit: str,
    rows: list[dict[str, str]],
    ymax: float,
) -> None:
    width, height = 1200, 800
    left, bottom, plot_w, plot_h = 120, 680, 1000, 520
    slot = plot_w / len(rows)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="600" y="52" text-anchor="middle" font-family="Microsoft YaHei,sans-serif" font-size="30" fill="#15212B">{html.escape(title)}</text>',
    ]
    for tick in range(6):
        value = ymax * tick / 5
        y = bottom - plot_h * tick / 5
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="1120" y2="{y:.1f}" stroke="#DDE3E7"/>')
        parts.append(f'<text x="105" y="{y + 7:.1f}" text-anchor="end" font-size="18" fill="#40515D">{value:.2f}</text>')
    for index, row in enumerate(rows):
        code = row["controller_code"]
        value = float(row[f"{metric}_mean"])
        x = left + slot * index + slot * 0.23
        bar_w = slot * 0.54
        y = bottom - value / ymax * plot_h
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bottom-y:.1f}" fill="{COLORS[code]}"/>')
        parts.append(f'<text x="{x + bar_w / 2:.1f}" y="720" text-anchor="middle" font-size="24" fill="#26343E">{code}</text>')
    parts.append(f'<text x="35" y="390" transform="rotate(-90 35 390)" text-anchor="middle" font-size="20" fill="#40515D">{html.escape(unit)}</text>')
    parts.append('<text x="600" y="775" text-anchor="middle" font-family="Microsoft YaHei,sans-serif" font-size="17" fill="#53636E">95% CI; n=5 paired SUMO seeds; 60 s rapid window</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
