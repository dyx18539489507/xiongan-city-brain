"""Generate lightweight, project-authored GLB traffic vehicle variants.

The output is standard glTF 2.0 and can be imported into Blender for further
editing.  It intentionally uses only PBR materials and compact mesh geometry so
the same assets remain practical on the MX250 target.  These are engineering
visualisations, not replicas of a particular manufacturer or field fleet.
"""

from __future__ import annotations

import argparse
import json
import math
import struct
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "apps" / "web-dashboard" / "public" / "assets" / "3d" / "vehicles"


@dataclass(frozen=True, slots=True)
class MaterialSpec:
    name: str
    color: tuple[float, float, float, float]
    metallic: float
    roughness: float
    emissive: tuple[float, float, float] = (0.0, 0.0, 0.0)


@dataclass(frozen=True, slots=True)
class PartSpec:
    name: str
    dimensions: tuple[float, float, float]
    center: tuple[float, float, float]
    material: str
    bevel: float = 0.04


@dataclass(slots=True)
class MeshData:
    positions: list[float]
    normals: list[float]
    indices: list[int]


MATERIALS = [
    MaterialSpec("VehiclePaint", (0.58, 0.67, 0.70, 1.0), 0.34, 0.30),
    MaterialSpec("VehicleDark", (0.025, 0.045, 0.055, 1.0), 0.12, 0.18),
    MaterialSpec("VehicleTrim", (0.07, 0.085, 0.09, 1.0), 0.38, 0.52),
    MaterialSpec(
        "VehicleHeadlight",
        (0.96, 0.91, 0.72, 1.0),
        0.04,
        0.20,
        (0.72, 0.62, 0.38),
    ),
    MaterialSpec(
        "VehicleTaillight",
        (0.62, 0.018, 0.012, 1.0),
        0.02,
        0.24,
        (0.52, 0.008, 0.004),
    ),
    MaterialSpec("VehicleAccent", (0.035, 0.35, 0.45, 1.0), 0.22, 0.36),
]


def _normal(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    c: tuple[float, float, float],
) -> tuple[float, float, float]:
    ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    ac = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    value = (
        ab[1] * ac[2] - ab[2] * ac[1],
        ab[2] * ac[0] - ab[0] * ac[2],
        ab[0] * ac[1] - ab[1] * ac[0],
    )
    length = math.sqrt(sum(component * component for component in value))
    return tuple(component / max(length, 1e-9) for component in value)  # type: ignore[return-value]


def rounded_prism(part: PartSpec) -> MeshData:
    """Build a compact chamfered rectangular prism with flat face normals."""

    length, height, width = part.dimensions
    cx, cy, cz = part.center
    bevel = min(part.bevel, length * 0.18, height * 0.28, width * 0.22)
    x0, x1 = cx - length / 2, cx + length / 2
    y0, y1 = cy - height / 2, cy + height / 2
    half_width = width / 2
    cross_section = [
        (-half_width + bevel, y0),
        (half_width - bevel, y0),
        (half_width, y0 + bevel),
        (half_width, y1 - bevel),
        (half_width - bevel, y1),
        (-half_width + bevel, y1),
        (-half_width, y1 - bevel),
        (-half_width, y0 + bevel),
    ]
    ring_x = [x0, x0 + bevel, x1 - bevel, x1]
    ring_scale = [0.94, 1.0, 1.0, 0.94]
    rings: list[list[tuple[float, float, float]]] = []
    for x, scale in zip(ring_x, ring_scale, strict=True):
        rings.append(
            [
                (x, cy + (y - cy) * scale, cz + z * scale)
                for z, y in cross_section
            ]
        )

    positions: list[float] = []
    normals: list[float] = []
    indices: list[int] = []

    def polygon(points: list[tuple[float, float, float]]) -> None:
        face_center = tuple(sum(point[i] for point in points) / len(points) for i in range(3))
        normal = _normal(points[0], points[1], points[2])
        outward = (face_center[0] - cx, face_center[1] - cy, face_center[2] - cz)
        if sum(normal[i] * outward[i] for i in range(3)) < 0:
            points = list(reversed(points))
            normal = _normal(points[0], points[1], points[2])
        start = len(positions) // 3
        for point in points:
            positions.extend(point)
            normals.extend(normal)
        for index in range(1, len(points) - 1):
            indices.extend((start, start + index, start + index + 1))

    for first, second in pairwise(rings):
        for index in range(len(first)):
            following = (index + 1) % len(first)
            polygon([first[index], second[index], second[following], first[following]])
    polygon(rings[0])
    polygon(rings[-1])
    return MeshData(positions, normals, indices)


def bus_parts() -> list[PartSpec]:
    return [
        PartSpec("Bus_VehiclePaint_Body", (11.8, 2.72, 2.48), (0.0, 1.72, 0.0), "VehiclePaint", 0.22),
        PartSpec("Bus_VehicleTrim_Skirt", (11.36, 0.38, 2.50), (-0.05, 0.50, 0.0), "VehicleTrim", 0.08),
        PartSpec("Bus_VehicleDark_WindowLeft", (8.9, 0.86, 0.035), (-0.30, 2.35, -1.247), "VehicleDark", 0.02),
        PartSpec("Bus_VehicleDark_WindowRight", (8.9, 0.86, 0.035), (-0.30, 2.35, 1.247), "VehicleDark", 0.02),
        PartSpec("Bus_VehicleDark_Windshield", (0.035, 0.92, 2.08), (5.89, 2.28, 0.0), "VehicleDark", 0.02),
        PartSpec("Bus_VehicleAccent_Left", (9.8, 0.14, 0.025), (-0.32, 1.46, -1.264), "VehicleAccent", 0.01),
        PartSpec("Bus_VehicleAccent_Right", (9.8, 0.14, 0.025), (-0.32, 1.46, 1.264), "VehicleAccent", 0.01),
        PartSpec("Bus_VehicleHeadlight_Left", (0.045, 0.22, 0.42), (5.91, 0.91, -0.75), "VehicleHeadlight", 0.01),
        PartSpec("Bus_VehicleHeadlight_Right", (0.045, 0.22, 0.42), (5.91, 0.91, 0.75), "VehicleHeadlight", 0.01),
        PartSpec("Bus_VehicleTaillight_Left", (0.045, 0.42, 0.20), (-5.91, 1.08, -0.93), "VehicleTaillight", 0.01),
        PartSpec("Bus_VehicleTaillight_Right", (0.045, 0.42, 0.20), (-5.91, 1.08, 0.93), "VehicleTaillight", 0.01),
    ]


def truck_parts() -> list[PartSpec]:
    return [
        PartSpec("Truck_VehicleTrim_Chassis", (8.25, 0.34, 2.28), (-0.10, 0.56, 0.0), "VehicleTrim", 0.06),
        PartSpec("Truck_VehiclePaint_Cab", (2.72, 2.45, 2.34), (2.64, 1.72, 0.0), "VehiclePaint", 0.19),
        PartSpec("Truck_VehiclePaint_Cargo", (5.25, 2.78, 2.45), (-1.45, 2.00, 0.0), "VehiclePaint", 0.12),
        PartSpec("Truck_VehicleDark_Windshield", (0.035, 0.78, 1.88), (4.01, 2.13, 0.0), "VehicleDark", 0.02),
        PartSpec("Truck_VehicleDark_WindowLeft", (1.10, 0.70, 0.035), (2.72, 2.12, -1.175), "VehicleDark", 0.02),
        PartSpec("Truck_VehicleDark_WindowRight", (1.10, 0.70, 0.035), (2.72, 2.12, 1.175), "VehicleDark", 0.02),
        PartSpec("Truck_VehicleAccent_CargoLeft", (4.70, 0.16, 0.025), (-1.45, 1.18, -1.237), "VehicleAccent", 0.01),
        PartSpec("Truck_VehicleAccent_CargoRight", (4.70, 0.16, 0.025), (-1.45, 1.18, 1.237), "VehicleAccent", 0.01),
        PartSpec("Truck_VehicleHeadlight_Left", (0.045, 0.20, 0.38), (4.02, 0.90, -0.73), "VehicleHeadlight", 0.01),
        PartSpec("Truck_VehicleHeadlight_Right", (0.045, 0.20, 0.38), (4.02, 0.90, 0.73), "VehicleHeadlight", 0.01),
        PartSpec("Truck_VehicleTaillight_Left", (0.045, 0.34, 0.20), (-4.10, 0.82, -0.88), "VehicleTaillight", 0.01),
        PartSpec("Truck_VehicleTaillight_Right", (0.045, 0.34, 0.20), (-4.10, 0.82, 0.88), "VehicleTaillight", 0.01),
    ]


def van_parts() -> list[PartSpec]:
    return [
        PartSpec("Van_VehiclePaint_Body", (4.62, 2.14, 2.08), (-0.36, 1.47, 0.0), "VehiclePaint", 0.16),
        PartSpec("Van_VehiclePaint_Nose", (1.30, 1.05, 2.02), (2.25, 1.02, 0.0), "VehiclePaint", 0.18),
        PartSpec("Van_VehicleTrim_Bumper", (0.24, 0.28, 2.03), (2.90, 0.63, 0.0), "VehicleTrim", 0.05),
        PartSpec("Van_VehicleDark_Windshield", (0.035, 0.75, 1.72), (1.96, 1.75, 0.0), "VehicleDark", 0.02),
        PartSpec("Van_VehicleDark_WindowLeft", (1.02, 0.66, 0.035), (1.25, 1.76, -1.045), "VehicleDark", 0.02),
        PartSpec("Van_VehicleDark_WindowRight", (1.02, 0.66, 0.035), (1.25, 1.76, 1.045), "VehicleDark", 0.02),
        PartSpec("Van_VehicleAccent_Left", (3.65, 0.14, 0.025), (-0.52, 1.12, -1.055), "VehicleAccent", 0.01),
        PartSpec("Van_VehicleAccent_Right", (3.65, 0.14, 0.025), (-0.52, 1.12, 1.055), "VehicleAccent", 0.01),
        PartSpec("Van_VehicleHeadlight_Left", (0.045, 0.18, 0.34), (2.91, 0.88, -0.68), "VehicleHeadlight", 0.01),
        PartSpec("Van_VehicleHeadlight_Right", (0.045, 0.18, 0.34), (2.91, 0.88, 0.68), "VehicleHeadlight", 0.01),
        PartSpec("Van_VehicleTaillight_Left", (0.045, 0.38, 0.18), (-2.68, 1.02, -0.82), "VehicleTaillight", 0.01),
        PartSpec("Van_VehicleTaillight_Right", (0.045, 0.38, 0.18), (-2.68, 1.02, 0.82), "VehicleTaillight", 0.01),
    ]


def _align(blob: bytearray) -> None:
    blob.extend(b"\x00" * ((-len(blob)) % 4))


def build_glb(parts: list[PartSpec], output: Path, asset_name: str) -> None:
    material_lookup = {material.name: index for index, material in enumerate(MATERIALS)}
    blob = bytearray()
    buffer_views: list[dict[str, int]] = []
    accessors: list[dict[str, object]] = []
    meshes: list[dict[str, object]] = []
    nodes: list[dict[str, object]] = []

    def add_view(data: bytes, target: int) -> int:
        _align(blob)
        offset = len(blob)
        blob.extend(data)
        buffer_views.append(
            {"buffer": 0, "byteOffset": offset, "byteLength": len(data), "target": target}
        )
        return len(buffer_views) - 1

    for part in parts:
        mesh = rounded_prism(part)
        position_bytes = struct.pack(f"<{len(mesh.positions)}f", *mesh.positions)
        normal_bytes = struct.pack(f"<{len(mesh.normals)}f", *mesh.normals)
        index_bytes = struct.pack(f"<{len(mesh.indices)}H", *mesh.indices)
        position_view = add_view(position_bytes, 34962)
        normal_view = add_view(normal_bytes, 34962)
        index_view = add_view(index_bytes, 34963)
        points = list(zip(mesh.positions[0::3], mesh.positions[1::3], mesh.positions[2::3], strict=True))
        position_accessor = len(accessors)
        accessors.append(
            {
                "bufferView": position_view,
                "componentType": 5126,
                "count": len(points),
                "type": "VEC3",
                "min": [min(point[i] for point in points) for i in range(3)],
                "max": [max(point[i] for point in points) for i in range(3)],
            }
        )
        normal_accessor = len(accessors)
        accessors.append(
            {
                "bufferView": normal_view,
                "componentType": 5126,
                "count": len(points),
                "type": "VEC3",
            }
        )
        index_accessor = len(accessors)
        accessors.append(
            {
                "bufferView": index_view,
                "componentType": 5123,
                "count": len(mesh.indices),
                "type": "SCALAR",
                "min": [min(mesh.indices)],
                "max": [max(mesh.indices)],
            }
        )
        meshes.append(
            {
                "name": part.name,
                "primitives": [
                    {
                        "attributes": {"POSITION": position_accessor, "NORMAL": normal_accessor},
                        "indices": index_accessor,
                        "material": material_lookup[part.material],
                    }
                ],
            }
        )
        nodes.append({"name": part.name, "mesh": len(meshes) - 1})

    document = {
        "asset": {
            "version": "2.0",
            "generator": "xiongan-traffic-brain build_vehicle_variants.py",
            "copyright": "Project-authored engineering asset",
        },
        "scene": 0,
        "scenes": [{"name": asset_name, "nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": [
            {
                "name": material.name,
                "pbrMetallicRoughness": {
                    "baseColorFactor": list(material.color),
                    "metallicFactor": material.metallic,
                    "roughnessFactor": material.roughness,
                },
                "emissiveFactor": list(material.emissive),
            }
            for material in MATERIALS
        ],
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": buffer_views,
        "accessors": accessors,
        "extras": {
            "provenance": "project-authored procedural geometry",
            "fieldMeasured": False,
            "blenderCompatible": True,
        },
    }
    json_chunk = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    json_chunk += b" " * ((-len(json_chunk)) % 4)
    _align(blob)
    total_length = 12 + 8 + len(json_chunk) + 8 + len(blob)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(
        struct.pack("<4sII", b"glTF", 2, total_length)
        + struct.pack("<II", len(json_chunk), 0x4E4F534A)
        + json_chunk
        + struct.pack("<II", len(blob), 0x004E4942)
        + blob
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()
    outputs = {
        "urban-bus.glb": bus_parts(),
        "urban-truck.glb": truck_parts(),
        "delivery-van.glb": van_parts(),
    }
    for filename, parts in outputs.items():
        target = arguments.output_root.resolve() / filename
        build_glb(parts, target, Path(filename).stem)
        print(target)


if __name__ == "__main__":
    main()
