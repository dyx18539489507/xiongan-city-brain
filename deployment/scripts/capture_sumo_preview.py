"""Capture a deterministic SUMO-GUI screenshot for a generated scenario."""

import argparse
import os
import sys
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--simulation-time", type=float, default=900.0)
    parser.add_argument("--junction-id", default="J")
    parser.add_argument("--view-radius-m", type=float, default=250.0)
    parser.add_argument(
        "--view-scheme",
        default="competition simple shapes",
        help="visualization scheme embedded in the scenario GUI settings file",
    )
    parser.add_argument(
        "--capture-delay-ms",
        type=float,
        default=0.0,
        help="temporary GUI delay override used only while capturing an automated preview",
    )
    return parser


def main() -> int:
    """Run SUMO-GUI to a requested time and save its real network view."""

    args = _parser().parse_args()
    sumo_home_value = os.environ.get("SUMO_HOME")
    if not sumo_home_value:
        raise RuntimeError("SUMO_HOME is required")
    sumo_home = Path(sumo_home_value)
    sys.path.insert(0, str(sumo_home / "tools"))
    import traci  # type: ignore[import-untyped,import-not-found]

    config = args.config if args.config.is_absolute() else Path.cwd() / args.config
    output = args.output if args.output.is_absolute() else Path.cwd() / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    binary = sumo_home / "bin" / ("sumo-gui.exe" if os.name == "nt" else "sumo-gui")
    traci.start(
        [
            str(binary),
            "-c",
            str(config),
            "--start",
            "--quit-on-end",
            "--no-step-log",
            "true",
            "--delay",
            str(args.capture_delay_ms),
        ]
    )
    try:
        while traci.simulation.getTime() < args.simulation_time:
            traci.simulationStep()
        view = traci.gui.DEFAULT_VIEW
        center_x, center_y = traci.junction.getPosition(args.junction_id)
        xmin = center_x - args.view_radius_m
        ymin = center_y - args.view_radius_m
        xmax = center_x + args.view_radius_m
        ymax = center_y + args.view_radius_m
        traci.gui.setBoundary(view, xmin, ymin, xmax, ymax)
        traci.gui.setSchema(view, args.view_scheme)
        traci.gui.screenshot(view, str(output), width=1200, height=800)
        for _ in range(5):
            traci.simulationStep()
    finally:
        traci.close()
    if not output.is_file():
        raise RuntimeError(f"SUMO-GUI did not create {output}")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
