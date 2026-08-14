"""Command-line entrypoints used by Makefile, Docker and CI."""

import argparse
import asyncio
import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

from traffic_platform.experiment_service.benchmark import run_benchmark
from traffic_platform.experiment_service.engine import (
    ExperimentRunner,
    smoke_config,
)
from traffic_platform.messaging.factory import message_bus_from_environment
from traffic_platform.observability.logging import configure_logging
from traffic_platform.report_service.generator import generate_report
from traffic_platform.scenario_engine.generator import generate_demo_scenario
from traffic_platform.scenario_engine.official_audit import write_official_audit
from traffic_platform.scenario_engine.official_builder import (
    build_official_intersections,
)
from traffic_platform.scenario_engine.official_inventory import (
    write_official_inventory,
)
from traffic_platform.scenario_engine.parameter_transfer import transfer_parameters
from traffic_platform.scene.generator import generate_scene_document
from traffic_platform.service_workers import run_service_worker
from traffic_platform.specification import validate_specs


def _workspace() -> Path:
    return Path.cwd()


def _sumo_home() -> Path:
    value = os.environ.get("SUMO_HOME")
    if not value:
        raise RuntimeError("SUMO_HOME must point to an Eclipse SUMO installation")
    path = Path(value)
    if not path.is_dir():
        raise FileNotFoundError(path)
    return path


def _validate(_: argparse.Namespace) -> int:
    result = validate_specs(_workspace())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run(
        "traffic_platform.api.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
    )
    return 0


def _worker(args: argparse.Namespace) -> int:
    asyncio.run(run_service_worker(args.role))
    return 0


def _generate_demo(args: argparse.Namespace) -> int:
    result = generate_demo_scenario(
        _workspace(),
        _sumo_home(),
        rebuild=not args.verify_only,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _generate_3d_scene(args: argparse.Namespace) -> int:
    output = Path(args.output) if args.output else None
    result = generate_scene_document(
        _workspace(),
        scenario_id=args.scenario_id,
        output_path=output,
        padding_m=args.padding_m,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _official_inventory(args: argparse.Namespace) -> int:
    result = write_official_inventory(
        Path(args.source_root),
        Path(args.output),
    )
    print(
        json.dumps(
            {
                "status": "inventoried",
                "output": args.output,
                **result["counts"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _generate_official_intersections(args: argparse.Namespace) -> int:
    result = build_official_intersections(
        _workspace(),
        Path(args.source_root),
        _sumo_home(),
        args.demo_ids,
        validate=not args.no_run,
        jobs=args.jobs,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _audit_official_intersections(args: argparse.Namespace) -> int:
    result = write_official_audit(
        _workspace(),
        Path(args.source_root),
        Path(args.output),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _demo(args: argparse.Namespace) -> int:
    config = smoke_config(
        args.algorithm,
        duration_s=args.duration,
        seed=args.seed,
        result_root=Path(args.output),
    )
    if args.gui:
        config = replace(config, gui=True)
    if args.cloud_outage:
        config = replace(
            config,
            cloud_outage_start_s=min(10.0, args.duration / 4),
            cloud_outage_duration_s=min(30.0, args.duration / 2),
        )
    if args.accelerate_disturbances:
        config = replace(config, disturbance_time_scale=0.01)
    result = asyncio.run(
        ExperimentRunner(
            config,
            sumo_home=_sumo_home(),
            bus=message_bus_from_environment(os.environ, seed=args.seed),
        ).run()
    )
    print(
        json.dumps(
            {
                "status": "completed",
                "actual_run": result["actual_run"],
                "experiment_id": result["experiment_id"],
                "algorithm": result["algorithm"],
                "metrics": result["metrics"],
                "artifacts": result["artifacts"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _benchmark(args: argparse.Namespace) -> int:
    result = asyncio.run(
        run_benchmark(
            sumo_home=_sumo_home(),
            algorithms=args.algorithms,
            seeds=args.seeds,
            duration_s=args.duration,
            output_dir=Path(args.output),
        )
    )
    print(
        json.dumps(
            {
                "status": "completed",
                "actual_run": True,
                "run_count": len(result["rows"]),
                "output": args.output,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _report(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    result = json.loads(input_path.read_text(encoding="utf-8"))
    artifacts = generate_report(result, Path(args.output))
    print(json.dumps(artifacts, ensure_ascii=False, indent=2))
    return 0


def _latest_report(args: argparse.Namespace) -> int:
    candidates = [
        path
        for path in Path(args.results_root).rglob("result.json")
        if Path(args.output) not in path.parents
    ]
    if not candidates:
        raise FileNotFoundError("no actual result.json exists; run demo or benchmark-smoke first")
    latest = max(candidates, key=lambda path: path.stat().st_mtime_ns)
    result = json.loads(latest.read_text(encoding="utf-8"))
    artifacts = generate_report(result, Path(args.output))
    print(
        json.dumps(
            {"source": str(latest), "artifacts": artifacts},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _transfer_parameters(args: argparse.Namespace) -> int:
    result = transfer_parameters(
        Path(args.processed_root),
        Path(args.net_file),
        Path(args.selection_file),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    modeled = sum(
        item["parameter_provenance"] == "modeled_from_organizer_data"
        for item in result["intersections"].values()
    )
    print(
        json.dumps(
            {
                "status": "generated",
                "output": str(output),
                "intersection_count": len(result["intersections"]),
                "modeled_intersection_count": modeled,
                "total_flow_conservation_error": round(
                    abs(
                        result["total_raw_peak_flow_veh_h"]
                        - result["total_balanced_peak_flow_veh_h"]
                    ),
                    6,
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the stable platform CLI parser."""

    parser = argparse.ArgumentParser(prog="traffic-platform")
    subcommands = parser.add_subparsers(dest="command", required=True)
    validate = subcommands.add_parser("validate", help="validate specs and contracts")
    validate.set_defaults(handler=_validate)
    generate = subcommands.add_parser(
        "generate-demo-scenario",
        help="reproducibly build or verify the Rongdong 20-intersection scenario",
    )
    generate.add_argument("--verify-only", action="store_true")
    generate.set_defaults(handler=_generate_demo)
    scene = subcommands.add_parser(
        "generate-3d-scene",
        help="generate the traceable static Web 3D scene document",
    )
    scene.add_argument("--scenario-id", default="xiongan_rongdong_20")
    scene.add_argument("--output", default=None)
    scene.add_argument("--padding-m", type=float, default=300.0)
    scene.set_defaults(handler=_generate_3d_scene)
    inventory = subcommands.add_parser(
        "official-inventory",
        help="hash the read-only organizer data collection",
    )
    inventory.add_argument(
        "--source-root",
        default=os.environ.get(
            "TRAFFIC_ORGANIZER_SOURCE_ROOT",
            "../挑战杯/赛题资料/赛题资料",
        ),
    )
    inventory.add_argument(
        "--output",
        default="scenarios/generated/official_20_independent/manifest.json",
    )
    inventory.set_defaults(handler=_official_inventory)
    official_generate = subcommands.add_parser(
        "generate-official-intersections",
        help="build selected organizer intersections from Excel, PNG and OSM evidence",
    )
    official_generate.add_argument(
        "--source-root",
        default=os.environ.get(
            "TRAFFIC_ORGANIZER_SOURCE_ROOT",
            "D:/程序项目/挑战杯/赛题资料/赛题资料",
        ),
    )
    official_generate.add_argument(
        "--demo-ids",
        nargs="+",
        type=int,
        default=list(range(1, 21)),
    )
    official_generate.add_argument(
        "--jobs",
        type=int,
        default=1,
        help="number of independent intersection builds/validations to run in parallel",
    )
    official_generate.add_argument(
        "--no-run",
        action="store_true",
        help="generate files without executing the SUMO validation runs",
    )
    official_generate.set_defaults(handler=_generate_official_intersections)
    official_audit = subcommands.add_parser(
        "audit-official-intersections",
        help="compare all generated projects with organizer workbooks and evidence",
    )
    official_audit.add_argument(
        "--source-root",
        default=os.environ.get(
            "TRAFFIC_ORGANIZER_SOURCE_ROOT",
            "D:/程序项目/挑战杯/赛题资料/赛题资料",
        ),
    )
    official_audit.add_argument(
        "--output",
        default="outputs/official_20_audit",
    )
    official_audit.set_defaults(handler=_audit_official_intersections)
    transfer = subcommands.add_parser(
        "transfer-parameters",
        help="transfer organizer-derived parameters to the connected OSM scenario",
    )
    transfer.add_argument(
        "--processed-root",
        default=os.environ.get(
            "TRAFFIC_ORGANIZER_PROCESSED_ROOT",
            "D:/程序项目/挑战杯/xiongan-traffic-brain/data/processed/intersections",
        ),
    )
    transfer.add_argument(
        "--net-file",
        default="scenarios/generated/xiongan_rongdong_20/rongdong.control.net.xml",
    )
    transfer.add_argument(
        "--selection-file",
        default=("scenarios/generated/xiongan_rongdong_20/controlled_intersections.json"),
    )
    transfer.add_argument(
        "--output",
        default="scenarios/generated/xiongan_rongdong_20/parameter_transfer.json",
    )
    transfer.set_defaults(handler=_transfer_parameters)
    serve = subcommands.add_parser("serve", help="run the FastAPI management service")
    serve.add_argument("--host", default=os.environ.get("TRAFFIC_API_HOST", "0.0.0.0"))
    serve.add_argument(
        "--port",
        default=int(os.environ.get("TRAFFIC_API_PORT", "8000")),
        type=int,
    )
    serve.set_defaults(handler=_serve)
    worker = subcommands.add_parser(
        "worker",
        help="run one independent MQTT/Redis service role",
    )
    worker.add_argument(
        "role",
        choices=[
            "cloud-service",
            "rsu-service",
            "edge-service",
            "vehicle-agent",
            "report-service",
            "sumo-runner",
        ],
    )
    worker.set_defaults(handler=_worker)
    demo = subcommands.add_parser("demo", help="run one actual end-to-end SUMO demo")
    demo.add_argument(
        "--algorithm",
        choices=[
            "fixed-time",
            "actuated-control",
            "max-pressure",
            "coordinated-max-pressure",
        ],
        default="coordinated-max-pressure",
    )
    demo.add_argument("--duration", type=float, default=30.0)
    demo.add_argument("--seed", type=int, default=42)
    demo.add_argument("--output", default="results/demo")
    demo.add_argument("--gui", action="store_true")
    demo.add_argument("--cloud-outage", action="store_true")
    demo.add_argument(
        "--accelerate-disturbances",
        action="store_true",
        help="compress the validated disturbance schedule to 1%% for demos",
    )
    demo.set_defaults(handler=_demo)
    benchmark = subcommands.add_parser(
        "benchmark",
        help="run a fair actual multi-algorithm benchmark matrix",
    )
    benchmark.add_argument(
        "--algorithms",
        nargs="+",
        default=[
            "fixed-time",
            "actuated-control",
            "max-pressure",
            "coordinated-max-pressure",
        ],
    )
    benchmark.add_argument("--seeds", nargs="+", type=int, default=[11, 23, 37, 41, 59])
    benchmark.add_argument("--duration", type=float, default=1800.0)
    benchmark.add_argument("--output", default="results/benchmark")
    benchmark.set_defaults(handler=_benchmark)
    report = subcommands.add_parser("report", help="regenerate report from result JSON")
    report.add_argument("--input", required=True)
    report.add_argument("--output", default="results/report")
    report.set_defaults(handler=_report)
    latest_report = subcommands.add_parser(
        "latest-report",
        help="regenerate a report from the newest actual experiment result",
    )
    latest_report.add_argument("--results-root", default="results")
    latest_report.add_argument("--output", default="results/report-latest")
    latest_report.set_defaults(handler=_latest_report)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Execute one CLI command and return a process-compatible status."""

    configure_logging(os.environ.get("LOG_LEVEL", "INFO"))
    args = build_parser().parse_args(argv)
    handler: Any = args.handler
    return int(handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
