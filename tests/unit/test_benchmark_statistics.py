from traffic_platform.experiment_service.benchmark import (
    _aggregate_confidence_intervals,
)


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
