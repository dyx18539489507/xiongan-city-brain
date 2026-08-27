from pathlib import Path

from traffic_platform.scenario_engine.draft_builder import (
    _selected_signal_layout,
    _viewsettings_xml,
)


def _joined_net(tmp_path: Path, *, control_internal_exit: bool = False) -> Path:
    internal_tls = ' tl="joinedS_-2_-6" linkIndex="2"' if control_internal_exit else ""
    network = tmp_path / "joined.net.xml"
    network.write_text(
        f'''<?xml version="1.0" encoding="UTF-8"?>
<net>
  <edge id="west" from="west" to="-2"/>
  <edge id="bridge" from="-2" to="-6"/>
  <edge id="east" from="-6" to="east"/>
  <edge id="north" from="north" to="-6"/>
  <edge id="south" from="-6" to="south"/>
  <tlLogic id="joinedS_-2_-6" type="actuated" programID="0" offset="0">
    <phase duration="30" state="GG"/>
  </tlLogic>
  <connection from="west" to="bridge" tl="joinedS_-2_-6" linkIndex="0"/>
  <connection from="north" to="south" tl="joinedS_-2_-6" linkIndex="1"/>
  <connection from="bridge" to="east"{internal_tls}/>
</net>
''',
        encoding="utf-8",
    )
    return network


def test_joined_tls_maps_members_to_one_physical_controller(tmp_path: Path) -> None:
    layout = _selected_signal_layout(_joined_net(tmp_path), ["-2", "-6"])

    assert layout["selected_to_controller"] == {
        "-2": "joinedS_-2_-6",
        "-6": "joinedS_-2_-6",
    }
    assert layout["controllers"] == {"joinedS_-2_-6": ["-2", "-6"]}
    assert layout["internal_connector_edges"] == {"joinedS_-2_-6": ["bridge"]}
    assert layout["controlled_internal_connections"] == []


def test_joined_tls_rejects_controlled_internal_connector_exit(tmp_path: Path) -> None:
    layout = _selected_signal_layout(
        _joined_net(tmp_path, control_internal_exit=True), ["-2", "-6"]
    )

    assert layout["controlled_internal_connections"] == ["bridge->east@joinedS_-2_-6"]


def test_original_light_theme_preserves_vehicle_visualization() -> None:
    view_settings = _viewsettings_xml({"zoom": 800.0, "x": 100.0, "y": 50.0})

    vehicle_settings = 'vehicle_minSize="1.50" vehicle_exaggeration="1.25" vehicle_constantSize="0"'
    assert vehicle_settings in view_settings
    assert 'name="custom_1"' in view_settings
    assert 'backgroundColor="white"' in view_settings
    assert '<entry color="black" name="road"/>' in view_settings
    assert '<entry color="yellow"/>' in view_settings
    assert 'showLinkDecals="0"' in view_settings
    assert 'showLinkRules="1"' in view_settings
    assert 'showDirection="0"' in view_settings
    assert 'drawCrossingsAndWalkingareas="0"' in view_settings
    assert 'angle="0.00"' in view_settings
    assert '<delay value="300.00"/>' in view_settings
