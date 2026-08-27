from traffic_platform.experiment_service.benchmark import (
    _aggregate_confidence_intervals,
    _b3_verdict,
    _benchmark_input_facts,
    _fairness_controls,
    _paired_b3_comparisons,
    _rank_algorithms,
)

FAIRNESS_CONTROLS = {
    "same_network": True,
    "same_od_and_departures_within_seed": True,
    "same_vehicle_types": True,
    "same_duration": True,
    "same_disturbances": True,
    "only_algorithm_changes": True,
}


def test_five_seed_aggregate_reports_student_t_confidence_interval() -> None:
    rows = [
        {"algorithm": "fixed-time", "seed": seed, "mean_speed": value}
        for seed, value in zip(
            [11, 23, 37, 41, 59],
            [8.0, 9.0, 10.0, 11.0, 12.0],
            strict=True,
        )
    ]
    aggregate = _aggregate_confidence_intervals(rows, ["fixed-time"])
    interval = aggregate["fixed-time"]["mean_speed"]
    assert interval["n"] == 5
    assert interval["mean"] == 10.0
    assert interval["ci95_low"] < 10.0 < interval["ci95_high"]


def test_aggregate_ignores_non_numeric_observation_markers() -> None:
    rows = [
        {"algorithm": "fixed-time", "seed": 11, "recovery_time": 12.0},
        {
            "algorithm": "fixed-time",
            "seed": 23,
            "recovery_time": "not_observed_within_run",
        },
    ]

    aggregate = _aggregate_confidence_intervals(rows, ["fixed-time"])

    assert aggregate["fixed-time"]["recovery_time"] == {
        "n": 1,
        "mean": 12.0,
        "standard_deviation": 0.0,
        "ci95_low": 12.0,
        "ci95_high": 12.0,
    }


def test_b3_pairwise_reports_improvement_against_every_baseline() -> None:
    algorithms = [
        "fixed-time",
        "actuated-control",
        "max-pressure",
        "coordinated-max-pressure",
    ]
    rows = []
    for seed in (11, 23, 37, 41, 59):
        for index, algorithm in enumerate(algorithms):
            rows.append(
                {
                    "algorithm": algorithm,
                    "seed": seed,
                    "mean_queue_vehicles": 12.0 - index * 2.0,
                    "mean_speed": 6.0 + index,
                }
            )

    pairwise = _paired_b3_comparisons(rows, algorithms)
    aggregate = _aggregate_confidence_intervals(rows, algorithms)
    rankings = _rank_algorithms(aggregate, algorithms)
    verdict = _b3_verdict(
        pairwise,
        rows,
        algorithms,
        fairness_controls=FAIRNESS_CONTROLS,
    )

    assert set(pairwise) == set(algorithms[:3])
    assert all(
        metrics["mean_queue_vehicles"]["improvement_percent"] > 0
        for metrics in pairwise.values()
    )
    assert rankings["mean_speed"][0]["algorithm"] == "coordinated-max-pressure"
    assert verdict["status"] == "best"


def test_b3_verdict_requires_multiple_seeds_and_all_algorithms() -> None:
    rows = [
        {"algorithm": "fixed-time", "seed": 11, "mean_queue_vehicles": 10.0},
        {
            "algorithm": "coordinated-max-pressure",
            "seed": 11,
            "mean_queue_vehicles": 8.0,
        },
    ]
    algorithms = ["fixed-time", "coordinated-max-pressure"]

    verdict = _b3_verdict(
        _paired_b3_comparisons(rows, algorithms),
        rows,
        algorithms,
        fairness_controls=FAIRNESS_CONTROLS,
    )

    assert verdict["status"] == "insufficient_evidence"


def test_b3_verdict_rejects_unfair_inputs() -> None:
    algorithms = [
        "fixed-time",
        "actuated-control",
        "max-pressure",
        "coordinated-max-pressure",
    ]
    rows = [
        {
            "algorithm": algorithm,
            "seed": seed,
            "mean_queue_vehicles": 12.0 - index * 2.0,
            "mean_speed": 6.0 + index,
        }
        for seed in (11, 23, 37)
        for index, algorithm in enumerate(algorithms)
    ]
    unfair = {**FAIRNESS_CONTROLS, "only_algorithm_changes": False}

    verdict = _b3_verdict(
        _paired_b3_comparisons(rows, algorithms),
        rows,
        algorithms,
        fairness_controls=unfair,
    )

    assert verdict["status"] == "not_proven"


def test_b3_verdict_rejects_algorithm_timeout() -> None:
    algorithms = [
        "fixed-time",
        "actuated-control",
        "max-pressure",
        "coordinated-max-pressure",
    ]
    rows = [
        {
            "algorithm": algorithm,
            "seed": seed,
            "mean_queue_vehicles": 12.0 - index * 2.0,
            "mean_speed": 6.0 + index,
            "algorithm_timeout_count": int(
                algorithm == "coordinated-max-pressure" and seed == 23
            ),
        }
        for seed in (11, 23, 37)
        for index, algorithm in enumerate(algorithms)
    ]

    verdict = _b3_verdict(
        _paired_b3_comparisons(rows, algorithms),
        rows,
        algorithms,
        fairness_controls=FAIRNESS_CONTROLS,
    )

    assert verdict["status"] == "not_proven"


def _result_for_fairness(algorithm: str, route_hash: str = "route-v1") -> dict:
    return {
        "algorithm": algorithm,
        "scenario_id": "fairness-smoke",
        "scenario_profile": "smoke",
        "seed": 11,
        "runner_options": {"step_length_s": 1.0},
        "manifest": {
            "scenario_hash": "scenario-v1",
            "files": [
                {"role": "network", "sha256": "network-v1"},
                {"role": "routes", "sha256": route_hash},
            ],
            "provenance": {"duration_s": 120.0},
        },
    }


def test_fairness_controls_accept_algorithm_as_only_difference() -> None:
    algorithms = [
        "fixed-time",
        "actuated-control",
        "max-pressure",
        "coordinated-max-pressure",
    ]
    facts = [_benchmark_input_facts(_result_for_fairness(name)) for name in algorithms]

    controls = _fairness_controls(
        facts,
        algorithms=algorithms,
        seeds=[11],
        duration_s=120.0,
    )

    assert all(controls.values())


def test_fairness_controls_reject_changed_route_hash() -> None:
    algorithms = ["fixed-time", "coordinated-max-pressure"]
    facts = [
        _benchmark_input_facts(_result_for_fairness("fixed-time")),
        _benchmark_input_facts(
            _result_for_fairness("coordinated-max-pressure", route_hash="route-v2")
        ),
    ]

    controls = _fairness_controls(
        facts,
        algorithms=algorithms,
        seeds=[11],
        duration_s=120.0,
    )

    assert controls["same_network"] is False
    assert controls["only_algorithm_changes"] is False
