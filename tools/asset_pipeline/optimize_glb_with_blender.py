"""Create deterministic Draco-compressed GLBs with Blender's bundled encoder.

Run only inside Blender, for example:
blender.exe --background --factory-startup --python optimize_glb_with_blender.py -- in.glb out.optimized.glb
"""

from __future__ import annotations

import sys
from pathlib import Path

import bpy


def optimize(source: Path, target: Path) -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    result = bpy.ops.import_scene.gltf(filepath=str(source))
    if "FINISHED" not in result:
        raise RuntimeError(f"failed to import {source}")
    bpy.ops.object.select_all(action="SELECT")
    target.parent.mkdir(parents=True, exist_ok=True)
    result = bpy.ops.export_scene.gltf(
        filepath=str(target),
        export_format="GLB",
        use_selection=True,
        export_yup=True,
        export_apply=True,
        export_cameras=False,
        export_lights=False,
        export_texcoords=True,
        export_normals=True,
        export_materials="EXPORT",
        export_draco_mesh_compression_enable=True,
        export_draco_mesh_compression_level=6,
        export_draco_position_quantization=14,
        export_draco_normal_quantization=10,
        export_draco_texcoord_quantization=12,
    )
    if "FINISHED" not in result or not target.is_file():
        raise RuntimeError(f"failed to export {target}")
    print(f"DRACO_OPTIMIZED={target} SOURCE_BYTES={source.stat().st_size} OUTPUT_BYTES={target.stat().st_size}")


def main() -> None:
    arguments = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    if not arguments or len(arguments) % 2:
        raise SystemExit("pass one or more INPUT.glb OUTPUT.optimized.glb pairs after --")
    for index in range(0, len(arguments), 2):
        optimize(Path(arguments[index]).resolve(), Path(arguments[index + 1]).resolve())


if __name__ == "__main__":
    main()
