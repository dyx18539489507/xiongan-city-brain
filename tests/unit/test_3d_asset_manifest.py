"""Structural checks for actual GLB assets and browser compression decoders."""

import json
from pathlib import Path

from tools.asset_pipeline.build_manifest import (
    build_texture_item,
    glb_document,
    triangle_count,
)


def test_vehicle_glb_and_generated_manifest_match() -> None:
    root = Path.cwd()
    public_assets = root / "apps" / "web-dashboard" / "public" / "assets"
    vehicle = public_assets / "k06" / "k06-vehicle.glb"
    document = glb_document(vehicle)
    assert triangle_count(document) == 2044
    manifest = json.loads((public_assets / "manifest.json").read_text(encoding="utf-8"))
    item = next(entry for entry in manifest["assets"] if entry["asset"].endswith("k06-vehicle.glb"))
    assert item["triangles"] == 2044
    assert item["draco"] is False
    assert item["ktx2"] is False


def test_runtime_draco_and_basis_decoders_are_packaged() -> None:
    decoder_root = (
        Path.cwd() / "apps" / "web-dashboard" / "public" / "assets" / "decoders"
    )
    for relative in (
        "draco/draco_decoder.wasm",
        "draco/draco_wasm_wrapper.js",
        "basis/basis_transcoder.wasm",
        "basis/basis_transcoder.js",
    ):
        assert (decoder_root / relative).stat().st_size > 0


def test_actual_project_authored_ktx2_texture_is_valid_and_manifested() -> None:
    public_assets = Path.cwd() / "apps" / "web-dashboard" / "public" / "assets"
    texture = public_assets / "3d" / "textures" / "k06_asphalt.ktx2"
    item = build_texture_item(texture, public_assets)
    assert item["format"] == "KTX2"
    assert item["width"] == 256
    assert item["height"] == 256
    assert int(item["levels"]) > 1
    assert int(item["supercompressionScheme"]) > 0
    manifest = json.loads((public_assets / "manifest.json").read_text(encoding="utf-8"))
    recorded = next(entry for entry in manifest["textures"] if entry["asset"] == item["asset"])
    assert recorded["sha256"] == item["sha256"]


def test_project_authored_vehicle_variants_are_distinct_valid_glbs() -> None:
    public_assets = Path.cwd() / "apps" / "web-dashboard" / "public" / "assets"
    manifest = json.loads((public_assets / "manifest.json").read_text(encoding="utf-8"))
    items = {
        Path(entry["asset"]).name: entry
        for entry in manifest["assets"]
        if "/3d/vehicles/" in entry["asset"]
    }
    source_names = {"delivery-van.glb", "urban-bus.glb", "urban-truck.glb"}
    optimized_names = {name.replace(".glb", ".optimized.glb") for name in source_names}
    assert set(items) == source_names | optimized_names
    for name in source_names:
        item = items[name]
        document = glb_document(public_assets / "3d" / "vehicles" / name)
        assert document["asset"]["version"] == "2.0"
        assert document["extras"]["blenderCompatible"] is True
        assert 400 <= triangle_count(document) <= 2_000
        assert item["source"] == "tools/asset_pipeline/build_vehicle_variants.py"
        assert item["draco"] is False
        assert item["ktx2"] is False
        optimized_name = name.replace(".glb", ".optimized.glb")
        optimized = items[optimized_name]
        optimized_document = glb_document(
            public_assets / "3d" / "vehicles" / optimized_name
        )
        assert "KHR_draco_mesh_compression" in optimized_document["extensionsRequired"]
        assert optimized["optimized"] is True
        assert optimized["draco"] is True
        assert optimized["bytes"] < item["bytes"]
        assert optimized["source"] == "tools/asset_pipeline/build_vehicle_variants.py"
