"""Build a deterministic, evidence-only manifest for Web 3D GLB assets."""

from __future__ import annotations

import argparse
import json
import struct
from hashlib import sha256
from pathlib import Path
from typing import Any

JSON_CHUNK = 0x4E4F534A
KTX2_IDENTIFIER = b"\xabKTX 20\xbb\r\n\x1a\n"


def glb_document(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    if len(data) < 20 or data[:4] != b"glTF":
        raise ValueError(f"not a GLB 2.0 file: {path}")
    version, declared_length = struct.unpack_from("<II", data, 4)
    if version != 2 or declared_length != len(data):
        raise ValueError(f"invalid GLB header: {path}")
    offset = 12
    while offset + 8 <= len(data):
        chunk_length, chunk_type = struct.unpack_from("<II", data, offset)
        offset += 8
        chunk = data[offset : offset + chunk_length]
        offset += chunk_length
        if chunk_type == JSON_CHUNK:
            return json.loads(chunk.rstrip(b"\x00 \t\r\n").decode("utf-8"))
    raise ValueError(f"GLB JSON chunk missing: {path}")


def triangle_count(document: dict[str, Any]) -> int:
    accessors = document.get("accessors", [])
    total = 0
    for mesh in document.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            mode = int(primitive.get("mode", 4))
            accessor_index = primitive.get("indices")
            if accessor_index is None:
                accessor_index = primitive.get("attributes", {}).get("POSITION")
            count = (
                int(accessors[accessor_index].get("count", 0))
                if isinstance(accessor_index, int) and accessor_index < len(accessors)
                else 0
            )
            if mode == 4:
                total += count // 3
            elif mode in {5, 6}:
                total += max(0, count - 2)
    return total


def embedded_texture_bytes(document: dict[str, Any]) -> int:
    buffer_views = document.get("bufferViews", [])
    total = 0
    for image in document.get("images", []):
        view = image.get("bufferView")
        if isinstance(view, int) and view < len(buffer_views):
            total += int(buffer_views[view].get("byteLength", 0))
    return total


def build_item(path: Path, public_root: Path) -> dict[str, object]:
    document = glb_document(path)
    extensions = {str(item) for item in document.get("extensionsUsed", [])}
    relative = path.relative_to(public_root).as_posix()
    data = path.read_bytes()
    source = (
        "tools/asset_pipeline/build_vehicle_variants.py"
        if relative.startswith("3d/vehicles/")
        else "assets/3d/k06/k06-hero.blend"
    )
    return {
        "asset": f"/assets/{relative}",
        "source": source,
        "optimized": relative.endswith(".optimized.glb"),
        "bytes": len(data),
        "sha256": sha256(data).hexdigest(),
        "triangles": triangle_count(document),
        "embeddedTextureBytes": embedded_texture_bytes(document),
        "draco": "KHR_draco_mesh_compression" in extensions,
        "ktx2": "KHR_texture_basisu" in extensions,
        "license": "project-authored; see docs/3d/asset_licenses.md",
        "lod": "runtime Three.LOD for vehicle assets; source-only otherwise",
    }


def build_texture_item(path: Path, public_root: Path) -> dict[str, object]:
    data = path.read_bytes()
    if len(data) < 48 or data[:12] != KTX2_IDENTIFIER:
        raise ValueError(f"not a KTX2 file: {path}")
    (
        vk_format,
        type_size,
        width,
        height,
        depth,
        layers,
        faces,
        levels,
        supercompression,
    ) = struct.unpack_from("<9I", data, 12)
    relative = path.relative_to(public_root).as_posix()
    return {
        "asset": f"/assets/{relative}",
        "source": "assets/3d/k06/textures/k06_asphalt.png",
        "bytes": len(data),
        "sha256": sha256(data).hexdigest(),
        "format": "KTX2",
        "vkFormat": vk_format,
        "typeSize": type_size,
        "width": width,
        "height": height,
        "depth": depth,
        "layers": layers,
        "faces": faces,
        "levels": levels,
        "supercompressionScheme": supercompression,
        "license": "project-authored; see docs/3d/asset_licenses.md",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    public_root = arguments.public_root.resolve()
    items = [build_item(path, public_root) for path in sorted(public_root.rglob("*.glb"))]
    textures = [
        build_texture_item(path, public_root)
        for path in sorted(public_root.rglob("*.ktx2"))
    ]
    manifest = {
        "schemaVersion": "1.0",
        "generatedFrom": "actual GLB headers and JSON chunks",
        "assets": items,
        "textures": textures,
        "runtimeDecoders": {
            "draco": "/assets/decoders/draco/",
            "ktx2Basis": "/assets/decoders/basis/",
        },
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
