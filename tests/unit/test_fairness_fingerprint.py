from pathlib import Path

from traffic_platform.comparison_service import (
    build_fairness_manifest,
    fairness_fingerprint,
)


def _write_sumo_fixture(root: Path) -> Path:
    config = root / "test.sumocfg"
    network = root / "test.net.xml"
    route = root / "test.rou.xml"
    additional = root / "signals.add.xml"
    network.write_text("<net/>", encoding="utf-8")
    route.write_text("<routes/>", encoding="utf-8")
    additional.write_text("<additional/>", encoding="utf-8")
    config.write_text(
        """<configuration><input>
        <net-file value="test.net.xml"/>
        <route-files value="test.rou.xml"/>
        <additional-files value="signals.add.xml"/>
        </input></configuration>""",
        encoding="utf-8",
    )
    return config


def test_fairness_fingerprint_covers_real_sumo_inputs_and_is_stable(tmp_path: Path) -> None:
    config = _write_sumo_fixture(tmp_path)
    manifest = build_fairness_manifest(
        sumo_config=config,
        scenario_id="xiongan_rongdong_20",
        scenario_profile="B0",
        seed=42,
        duration_s=900,
    )

    assert [item["role"] for item in manifest["files"]] == [
        "sumo-config",
        "net-file",
        "route-files",
        "additional-files",
    ]
    assert all(len(item["sha256"]) == 64 for item in manifest["files"])
    assert fairness_fingerprint(manifest) == fairness_fingerprint(dict(manifest))


def test_fairness_fingerprint_changes_when_route_truth_changes(tmp_path: Path) -> None:
    config = _write_sumo_fixture(tmp_path)
    before = build_fairness_manifest(
        sumo_config=config,
        scenario_id="scene",
        scenario_profile="B1",
        seed=7,
        duration_s=600,
    )
    (tmp_path / "test.rou.xml").write_text("<routes><vehicle id='v1'/></routes>", encoding="utf-8")
    after = build_fairness_manifest(
        sumo_config=config,
        scenario_id="scene",
        scenario_profile="B1",
        seed=7,
        duration_s=600,
    )

    assert fairness_fingerprint(before) != fairness_fingerprint(after)
