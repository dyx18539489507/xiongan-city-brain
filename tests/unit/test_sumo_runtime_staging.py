"""Windows-safe SUMO runtime staging tests."""

import xml.etree.ElementTree as ET
from pathlib import Path

from traffic_platform.sumo_adapter.adapter import _is_ascii_path, _stage_sumo_config


def test_ascii_path_detection() -> None:
    assert _is_ascii_path(Path("C:/xiongan/runtime"))
    assert not _is_ascii_path(Path("D:/程序项目/场景.sumocfg"))


def test_staged_config_copies_inputs_and_redirects_outputs(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "runtime"
    source.mkdir()
    (source / "network.net.xml").write_text("<net />", encoding="utf-8")
    (source / "routes.rou.xml").write_text("<routes />", encoding="utf-8")
    config = source / "scenario.sumocfg"
    config.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <input>
    <net-file value="network.net.xml" />
    <route-files value="routes.rou.xml" />
  </input>
  <output><summary-output value="summary.xml" /></output>
</configuration>
""",
        encoding="utf-8",
    )

    staged = _stage_sumo_config(config, destination)
    root = ET.parse(staged).getroot()
    output = Path(root.find("./output/summary-output").get("value"))  # type: ignore[union-attr]

    assert (destination / "network.net.xml").read_text(encoding="utf-8") == "<net />"
    assert (destination / "routes.rou.xml").read_text(encoding="utf-8") == "<routes />"
    assert output.is_absolute()
    assert output.parent == destination / "config-outputs"
