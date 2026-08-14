"""Mathematical parameter-transfer invariants."""

import json
import os
from pathlib import Path

from traffic_platform.scenario_engine.parameter_transfer import transfer_parameters


def test_transfer_preserves_total_flow_and_provenance() -> None:
    processed = Path(
        os.environ.get(
            "TRAFFIC_ORGANIZER_PROCESSED_ROOT",
            "D:/程序项目/挑战杯/xiongan-traffic-brain/data/processed/intersections",
        )
    )
    if os.environ.get("SUMO_HOME") and processed.is_dir():
        result = transfer_parameters(
            processed,
            Path("scenarios/generated/xiongan_rongdong_20/rongdong.control.net.xml"),
            Path(
                "scenarios/generated/xiongan_rongdong_20/controlled_intersections.json"
            ),
        )
    else:
        result = json.loads(
            Path(
                "scenarios/generated/xiongan_rongdong_20/parameter_transfer.json"
            ).read_text(encoding="utf-8")
        )
    assert len(result["intersections"]) == 20
    assert abs(
        result["total_raw_peak_flow_veh_h"]
        - result["total_balanced_peak_flow_veh_h"]
    ) <= 0.02
    modeled = [
        item
        for item in result["intersections"].values()
        if item["parameter_provenance"] == "modeled_from_organizer_data"
    ]
    organizer_assigned = [
        item
        for item in result["intersections"].values()
        if item["parameter_provenance"]
        == "organizer_supplied_assigned_to_registered_location"
    ]
    assert len(organizer_assigned) == 6
    assert len(modeled) == 14
    assert result["method"]["modeled_donor_pool"] == [
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
        11,
        12,
        13,
        16,
    ]
    assert all(len(item["donors"]) == 3 for item in modeled)
    assert all(
        donor["donor_intersection"]
        in result["method"]["modeled_donor_pool"]
        for item in modeled
        for donor in item["donors"]
    )
    assert all(
        abs(sum(item["turn_ratios"].values()) - 1.0) <= 2e-6
        for item in result["intersections"].values()
    )
