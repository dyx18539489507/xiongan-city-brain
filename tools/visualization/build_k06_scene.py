"""Build the editable Blender master and web GLBs for the K06 hero intersection.

The geometry is anchored to the connected Rongdong SUMO network at junction
11122023451 (display id K06).  The scene is an engineering visualisation, not
field-survey reconstruction: buildings and landscape are authored context,
while the road topology and approach directions follow the scenario network.

Run with Blender 4.5 LTS:
    blender.exe --background --python tools/visualization/build_k06_scene.py
"""

from __future__ import annotations

import math
import random
from array import array
from collections.abc import Sequence
from itertools import pairwise
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "assets" / "3d" / "k06"
TEXTURE_DIR = SOURCE_DIR / "textures"
WEB_DIR = ROOT / "apps" / "web-dashboard" / "public" / "assets" / "k06"
BLEND_PATH = SOURCE_DIR / "k06-hero.blend"
SCENE_GLB_PATH = WEB_DIR / "k06-hero.glb"
VEHICLE_GLB_PATH = WEB_DIR / "k06-vehicle.glb"
PREVIEW_PATH = WEB_DIR / "k06-preview.png"

STATIC_NAME = "K06_STATIC"
VEHICLE_NAME = "K06_VEHICLE"
PRESENTATION_NAME = "K06_PRESENTATION"

MAIN_CENTERLINE = [
    (0.0, -155.0),
    (0.0, -98.0),
    (0.0, -48.0),
    (0.0, -18.0),
    (0.0, 10.0),
    (-1.0, 30.0),
    (-12.0, 60.0),
    (-27.0, 95.0),
    (-43.0, 130.0),
    (-57.0, 162.0),
]
EAST_CENTERLINE = [
    (3.0, 0.0),
    (34.0, -0.5),
    (78.0, -1.5),
    (118.0, -2.5),
    (164.0, -3.6),
]


def reset_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for datablocks in (
        bpy.data.meshes,
        bpy.data.curves,
        bpy.data.materials,
        bpy.data.cameras,
        bpy.data.lights,
    ):
        for datablock in list(datablocks):
            if datablock.users == 0:
                datablocks.remove(datablock)


def collection(name: str) -> bpy.types.Collection:
    result = bpy.data.collections.get(name)
    if result is None:
        result = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(result)
    return result


def move_to_collection(obj: bpy.types.Object, target: bpy.types.Collection) -> None:
    for source in list(obj.users_collection):
        source.objects.unlink(obj)
    target.objects.link(obj)


def material(
    name: str,
    color: tuple[float, float, float, float],
    *,
    roughness: float = 0.72,
    metallic: float = 0.0,
    image: bpy.types.Image | None = None,
    emission: tuple[float, float, float, float] | None = None,
    emission_strength: float = 0.0,
) -> bpy.types.Material:
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.diffuse_color = color
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    if emission is not None:
        emission_input = bsdf.inputs.get("Emission Color") or bsdf.inputs.get("Emission")
        if emission_input is not None:
            emission_input.default_value = emission
        strength_input = bsdf.inputs.get("Emission Strength")
        if strength_input is not None:
            strength_input.default_value = emission_strength
    if image is not None:
        texture = mat.node_tree.nodes.new("ShaderNodeTexImage")
        texture.image = image
        texture.interpolation = "Linear"
        mat.node_tree.links.new(texture.outputs["Color"], bsdf.inputs["Base Color"])
    return mat


def make_texture(
    name: str,
    size: int,
    pixel_fn,
) -> bpy.types.Image:
    path = TEXTURE_DIR / f"{name}.png"
    image = bpy.data.images.new(name, width=size, height=size, alpha=True)
    pixels = array("f")
    for y in range(size):
        for x in range(size):
            pixels.extend(pixel_fn(x, y, size))
    image.pixels.foreach_set(pixels)
    image.filepath_raw = str(path)
    image.file_format = "PNG"
    image.save()
    image.colorspace_settings.name = "sRGB"
    return image


def build_textures() -> dict[str, bpy.types.Image]:
    asphalt_rng = random.Random(2051)
    asphalt_noise = [asphalt_rng.random() for _ in range(256 * 256)]
    grass_rng = random.Random(2207)
    grass_noise = [grass_rng.random() for _ in range(256 * 256)]
    paving_rng = random.Random(2341)
    paving_noise = [paving_rng.random() for _ in range(256 * 256)]

    def asphalt(x: int, y: int, size: int):
        n = asphalt_noise[y * size + x]
        grain = 0.028 * (n - 0.5)
        aggregate = 0.035 if n > 0.986 else 0.0
        base = 0.105 + grain + aggregate
        return (base * 0.94, base * 0.99, base, 1.0)

    def grass(x: int, y: int, size: int):
        n = grass_noise[y * size + x]
        wave = 0.015 * math.sin(x * 0.31 + y * 0.19)
        return (
            0.16 + 0.055 * n + wave,
            0.285 + 0.085 * n + wave,
            0.17 + 0.045 * n,
            1.0,
        )

    def paving(x: int, y: int, size: int):
        n = paving_noise[y * size + x]
        grout = x % 48 < 2 or y % 48 < 2
        stagger = ((x + (24 if (y // 48) % 2 else 0)) % 48) < 2
        base = 0.36 if grout or stagger else 0.56 + (n - 0.5) * 0.055
        return (base * 1.02, base, base * 0.96, 1.0)

    return {
        "asphalt": make_texture("k06_asphalt", 256, asphalt),
        "grass": make_texture("k06_grass", 256, grass),
        "paving": make_texture("k06_paving", 256, paving),
    }


def box(
    name: str,
    dimensions: tuple[float, float, float],
    location: tuple[float, float, float],
    mat: bpy.types.Material,
    target: bpy.types.Collection,
    *,
    rotation_z: float = 0.0,
    bevel: float = 0.0,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(location=location, rotation=(0.0, 0.0, rotation_z))
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = dimensions
    move_to_collection(obj, target)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if bevel > 0.0:
        modifier = obj.modifiers.new("Edge softness", "BEVEL")
        modifier.width = bevel
        modifier.segments = 2
        modifier.limit_method = "ANGLE"
        bpy.ops.object.modifier_apply(modifier=modifier.name)
    obj.data.materials.append(mat)
    return obj


def cylinder(
    name: str,
    radius: float,
    depth: float,
    location: tuple[float, float, float],
    mat: bpy.types.Material,
    target: bpy.types.Collection,
    *,
    vertices: int = 16,
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=vertices,
        radius=radius,
        depth=depth,
        location=location,
        rotation=rotation,
    )
    obj = bpy.context.object
    obj.name = name
    move_to_collection(obj, target)
    obj.data.materials.append(mat)
    return obj


def cylinder_between(
    name: str,
    start: tuple[float, float, float],
    end: tuple[float, float, float],
    radius: float,
    mat: bpy.types.Material,
    target: bpy.types.Collection,
) -> bpy.types.Object:
    a = Vector(start)
    b = Vector(end)
    direction = b - a
    obj = cylinder(name, radius, direction.length, tuple((a + b) * 0.5), mat, target)
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = direction.to_track_quat("Z", "Y")
    return obj


def uv_sphere(
    name: str,
    radius: float,
    location: tuple[float, float, float],
    mat: bpy.types.Material,
    target: bpy.types.Collection,
    *,
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0),
    segments: int = 20,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=radius, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    move_to_collection(obj, target)
    obj.data.materials.append(mat)
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    return obj


def polyline_metrics(points: Sequence[tuple[float, float]]) -> tuple[list[float], float]:
    lengths = [0.0]
    for start, end in pairwise(points):
        lengths.append(lengths[-1] + math.dist(start, end))
    return lengths, lengths[-1]


def offset_polyline(
    points: Sequence[tuple[float, float]], offset: float
) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
    for index, point in enumerate(points):
        previous = Vector(points[max(0, index - 1)])
        following = Vector(points[min(len(points) - 1, index + 1)])
        tangent = (following - previous).normalized()
        normal = Vector((-tangent.y, tangent.x))
        result.append((point[0] + normal.x * offset, point[1] + normal.y * offset))
    return result


def strip_mesh(
    name: str,
    points: Sequence[tuple[float, float]],
    width: float,
    z: float,
    mat: bpy.types.Material,
    target: bpy.types.Collection,
    *,
    texture_scale: float = 8.0,
) -> bpy.types.Object:
    if len(points) < 2:
        raise ValueError("A strip needs at least two points")
    lengths, _ = polyline_metrics(points)
    vertices: list[tuple[float, float, float]] = []
    uvs: list[tuple[float, float]] = []
    for index, point in enumerate(points):
        previous = Vector(points[max(0, index - 1)])
        following = Vector(points[min(len(points) - 1, index + 1)])
        tangent = (following - previous).normalized()
        normal = Vector((-tangent.y, tangent.x))
        left = Vector(point) + normal * width * 0.5
        right = Vector(point) - normal * width * 0.5
        vertices.extend([(left.x, left.y, z), (right.x, right.y, z)])
        u = lengths[index] / texture_scale
        uvs.extend([(u, 0.0), (u, width / texture_scale)])
    faces = [(2 * i, 2 * i + 1, 2 * i + 3, 2 * i + 2) for i in range(len(points) - 1)]
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    uv_layer = mesh.uv_layers.new(name="UVMap")
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            vertex_index = mesh.loops[loop_index].vertex_index
            uv_layer.data[loop_index].uv = uvs[vertex_index]
    obj = bpy.data.objects.new(name, mesh)
    target.objects.link(obj)
    obj.data.materials.append(mat)
    return obj


def marking_segment(
    name: str,
    start: tuple[float, float],
    end: tuple[float, float],
    width: float,
    mat: bpy.types.Material,
    target: bpy.types.Collection,
    *,
    z: float = 0.205,
) -> bpy.types.Object:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.hypot(dx, dy)
    return box(
        name,
        (length, width, 0.028),
        ((start[0] + end[0]) * 0.5, (start[1] + end[1]) * 0.5, z),
        mat,
        target,
        rotation_z=math.atan2(dy, dx),
    )


def marking_polyline(
    name: str,
    points: Sequence[tuple[float, float]],
    width: float,
    mat: bpy.types.Material,
    target: bpy.types.Collection,
    *,
    dashed: bool = False,
) -> None:
    for index, (start, end) in enumerate(pairwise(points)):
        length = math.dist(start, end)
        if not dashed:
            marking_segment(f"{name}_{index:02d}", start, end, width, mat, target)
            continue
        dx = (end[0] - start[0]) / length
        dy = (end[1] - start[1]) / length
        cursor = 1.8
        dash = 4.2
        gap = 5.3
        while cursor < length:
            end_cursor = min(cursor + dash, length)
            a = (start[0] + dx * cursor, start[1] + dy * cursor)
            b = (start[0] + dx * end_cursor, start[1] + dy * end_cursor)
            marking_segment(f"{name}_{index:02d}_{cursor:.0f}", a, b, width, mat, target)
            cursor += dash + gap


def crosswalk(
    name: str,
    center: tuple[float, float],
    *,
    across_angle: float,
    span: float,
    depth: float,
    mat: bpy.types.Material,
    target: bpy.types.Collection,
) -> None:
    across = Vector((math.cos(across_angle), math.sin(across_angle)))
    travel = Vector((-across.y, across.x))
    stripe_length = 0.72
    stripe_gap = 0.72
    cursor = -span * 0.5 + stripe_length * 0.5
    index = 0
    while cursor <= span * 0.5:
        middle = Vector(center) + across * cursor
        start = middle - travel * depth * 0.5
        end = middle + travel * depth * 0.5
        marking_segment(f"{name}_{index:02d}", tuple(start), tuple(end), stripe_length, mat, target)
        cursor += stripe_length + stripe_gap
        index += 1


def arrow(
    name: str,
    location: tuple[float, float],
    rotation_z: float,
    mat: bpy.types.Material,
    target: bpy.types.Collection,
) -> None:
    stem = box(name + "_Stem", (3.8, 0.28, 0.03), (location[0], location[1], 0.21), mat, target)
    head = box(name + "_Head", (1.65, 0.34, 0.03), (location[0] + 1.7, location[1], 0.21), mat, target)
    stem.rotation_euler.z = rotation_z
    head.rotation_euler.z = rotation_z + math.radians(45)
    bpy.context.view_layer.objects.active = stem
    return None


def build_roads(static: bpy.types.Collection, mats: dict[str, bpy.types.Material]) -> None:
    box("Terrain", (410.0, 410.0, 0.45), (5.0, 5.0, -0.25), mats["grass"], static)

    strip_mesh("MainSidewalkBase", MAIN_CENTERLINE, 24.0, 0.015, mats["paving"], static, texture_scale=5.5)
    strip_mesh("EastSidewalkBase", EAST_CENTERLINE, 23.0, 0.02, mats["paving"], static, texture_scale=5.5)
    strip_mesh("MainAsphalt", MAIN_CENTERLINE, 15.2, 0.13, mats["asphalt"], static, texture_scale=7.5)
    strip_mesh("EastAsphalt", EAST_CENTERLINE, 14.8, 0.135, mats["asphalt"], static, texture_scale=7.5)
    box("JunctionAsphalt", (18.0, 25.0, 0.16), (5.0, 0.0, 0.08), mats["asphalt"], static, bevel=2.4)

    main_west_curb = offset_polyline(MAIN_CENTERLINE, 7.9)
    main_east_curb = offset_polyline(MAIN_CENTERLINE, -7.9)
    marking_polyline("MainWestCurb", main_west_curb, 0.46, mats["curb"], static)
    marking_polyline("MainEastCurbSouth", main_east_curb[:4], 0.46, mats["curb"], static)
    marking_polyline("MainEastCurbNorth", main_east_curb[4:], 0.46, mats["curb"], static)
    east_north_curb = offset_polyline(EAST_CENTERLINE, 7.7)
    east_south_curb = offset_polyline(EAST_CENTERLINE, -7.7)
    marking_polyline("EastNorthCurb", east_north_curb[1:], 0.46, mats["curb"], static)
    marking_polyline("EastSouthCurb", east_south_curb[1:], 0.46, mats["curb"], static)

    for offset in (-0.18, 0.18):
        marking_polyline("MainCenterYellow", offset_polyline(MAIN_CENTERLINE, offset), 0.13, mats["yellow"], static)
        marking_polyline("EastCenterYellow", offset_polyline(EAST_CENTERLINE, offset), 0.13, mats["yellow"], static)
    for offset in (-3.65, 3.65):
        marking_polyline("MainLaneDash", offset_polyline(MAIN_CENTERLINE, offset), 0.12, mats["white"], static, dashed=True)
        marking_polyline("EastLaneDash", offset_polyline(EAST_CENTERLINE, offset), 0.12, mats["white"], static, dashed=True)
    for offset in (-7.15, 7.15):
        marking_polyline("MainEdgeLine", offset_polyline(MAIN_CENTERLINE, offset), 0.12, mats["white"], static)
        marking_polyline("EastEdgeLine", offset_polyline(EAST_CENTERLINE, offset), 0.12, mats["white"], static)

    crosswalk("SouthCrosswalk", (0.0, -13.2), across_angle=0.0, span=14.0, depth=3.8, mat=mats["white"], target=static)
    crosswalk("NorthCrosswalk", (-0.3, 13.5), across_angle=0.0, span=14.0, depth=3.8, mat=mats["white"], target=static)
    crosswalk("EastCrosswalk", (16.4, 0.0), across_angle=math.pi / 2, span=13.4, depth=3.8, mat=mats["white"], target=static)
    marking_segment("SouthStopLine", (-7.0, -18.0), (7.0, -18.0), 0.38, mats["white"], static)
    marking_segment("NorthStopLine", (-7.2, 18.2), (7.0, 18.2), 0.38, mats["white"], static)
    marking_segment("EastStopLine", (21.0, -7.0), (21.0, 7.0), 0.38, mats["white"], static)

    for x, y, angle in [(-2.0, -43.0, math.pi / 2), (2.0, 48.0, -math.pi / 2), (45.0, -3.0, math.pi)]:
        arrow(f"LaneArrow_{x}_{y}", (x, y), angle, mats["white"], static)

    # Tactile paving and protected bicycle-lane accents make the section legible at street level.
    for x, y, sx, sy in [(-8.8, -13.0, 1.0, 5.2), (-8.8, 13.0, 1.0, 5.2), (16.5, 8.7, 5.2, 1.0)]:
        box(f"Tactile_{x}_{y}", (sx, sy, 0.055), (x, y, 0.25), mats["tactile"], static)
    marking_polyline("EastBikeNorth", offset_polyline(EAST_CENTERLINE[1:], 5.95), 1.65, mats["bike"], static)
    marking_polyline("EastBikeSouth", offset_polyline(EAST_CENTERLINE[1:], -5.95), 1.65, mats["bike"], static)


def building(
    index: int,
    position: tuple[float, float],
    size: tuple[float, float],
    floors: int,
    mats: dict[str, bpy.types.Material],
    target: bpy.types.Collection,
    *,
    rotation: float = 0.0,
) -> None:
    x, y = position
    width, depth = size
    floor_height = 3.15
    height = floors * floor_height
    body_mat = mats["stone_warm"] if index % 2 else mats["stone_light"]
    box(f"Building_{index:02d}_Podium", (width + 2.0, depth + 2.0, 2.2), (x, y, 1.1), mats["stone_dark"], target, rotation_z=rotation, bevel=0.35)
    box(f"Building_{index:02d}_Body", (width, depth, height), (x, y, 2.2 + height * 0.5), body_mat, target, rotation_z=rotation, bevel=0.42)

    cos_r = math.cos(rotation)
    sin_r = math.sin(rotation)

    def local_to_world(lx: float, ly: float) -> tuple[float, float]:
        return (x + lx * cos_r - ly * sin_r, y + lx * sin_r + ly * cos_r)

    for floor in range(floors):
        z = 3.8 + floor * floor_height
        for side in (-1.0, 1.0):
            px, py = local_to_world(0.0, side * (depth * 0.5 + 0.035))
            box(
                f"Building_{index:02d}_WindowY_{floor}_{side}",
                (width * 0.78, 0.085, 1.28),
                (px, py, z),
                mats["glass"],
                target,
                rotation_z=rotation,
            )
            px, py = local_to_world(side * (width * 0.5 + 0.035), 0.0)
            box(
                f"Building_{index:02d}_WindowX_{floor}_{side}",
                (depth * 0.78, 0.085, 1.28),
                (px, py, z),
                mats["glass"],
                target,
                rotation_z=rotation + math.pi * 0.5,
            )
    for side in (-1.0, 1.0):
        px, py = local_to_world(side * width * 0.43, 0.0)
        box(f"Building_{index:02d}_Fin_{side}", (0.32, depth + 0.18, height + 0.4), (px, py, 2.2 + height * 0.5), mats["stone_dark"], target, rotation_z=rotation)
    box(f"Building_{index:02d}_Roof", (width * 0.62, depth * 0.62, 0.65), (x, y, 2.5 + height), mats["roof"], target, rotation_z=rotation, bevel=0.18)
    if floors >= 8:
        for panel_index in range(-2, 3):
            px, py = local_to_world(panel_index * 2.2, 0.0)
            panel = box(f"Building_{index:02d}_Solar_{panel_index}", (1.8, 4.0, 0.12), (px, py, 3.0 + height), mats["solar"], target, rotation_z=rotation)
            panel.rotation_euler.x = math.radians(12)


def civic_building(
    index: int,
    position: tuple[float, float],
    mats: dict[str, bpy.types.Material],
    target: bpy.types.Collection,
) -> None:
    """A lower stepped public building breaks the repeated tower silhouette."""
    x, y = position
    box(f"Civic_{index:02d}_Plinth", (38.0, 24.0, 1.5), (x, y, 0.75), mats["stone_dark"], target, bevel=0.42)
    box(f"Civic_{index:02d}_Lower", (34.0, 19.0, 6.2), (x, y, 4.55), mats["stone_warm"], target, bevel=0.5)
    box(f"Civic_{index:02d}_Upper", (25.0, 17.0, 8.4), (x + 4.0, y, 11.8), mats["stone_light"], target, bevel=0.55)
    box(f"Civic_{index:02d}_GlassFront", (24.0, 0.12, 5.1), (x + 4.0, y - 8.56, 11.7), mats["glass"], target)
    box(f"Civic_{index:02d}_Entrance", (11.5, 0.16, 3.8), (x - 4.0, y - 9.57, 3.55), mats["glass"], target)
    box(f"Civic_{index:02d}_Canopy", (15.0, 4.2, 0.32), (x - 4.0, y - 10.7, 5.6), mats["stone_dark"], target, bevel=0.12)
    for fin_index in range(-5, 6):
        box(
            f"Civic_{index:02d}_Fin_{fin_index}",
            (0.2, 0.42, 5.7),
            (x + 4.0 + fin_index * 1.9, y - 8.72, 11.8),
            mats["stone_dark"],
            target,
        )
    for panel_index in range(-4, 5):
        panel = box(
            f"Civic_{index:02d}_Solar_{panel_index}",
            (1.65, 5.2, 0.12),
            (x + 4.0 + panel_index * 2.15, y, 16.15),
            mats["solar"],
            target,
        )
        panel.rotation_euler.x = math.radians(10)


def tree_instance(
    index: int,
    x: float,
    y: float,
    scale: float,
    mats: dict[str, bpy.types.Material],
    target: bpy.types.Collection,
) -> None:
    cylinder(f"Tree_{index:03d}_Trunk", 0.18 * scale, 2.2 * scale, (x, y, 1.1 * scale), mats["bark"], target, vertices=10)
    rng = random.Random(index * 1777 + 19)
    for crown_index, (dx, dy, dz, crown_scale) in enumerate(
        [
            (0.0, 0.0, 3.0, 1.0),
            (-0.65, 0.15, 3.1, 0.74),
            (0.58, -0.12, 3.2, 0.76),
        ]
    ):
        mat = mats["leaf_a"] if (index + crown_index) % 3 else mats["leaf_b"]
        uv_sphere(
            f"Tree_{index:03d}_Crown_{crown_index}",
            1.42 * scale * crown_scale,
            (x + dx * scale, y + dy * scale, dz * scale),
            mat,
            target,
            scale=(1.0 + rng.random() * 0.18, 0.88 + rng.random() * 0.12, 1.05 + rng.random() * 0.2),
        )


def streetlight(
    index: int,
    x: float,
    y: float,
    face: tuple[float, float],
    mats: dict[str, bpy.types.Material],
    target: bpy.types.Collection,
) -> None:
    cylinder(f"Streetlight_{index:02d}_Post", 0.105, 7.6, (x, y, 3.8), mats["pole"], target, vertices=14)
    arm_end = (x + face[0] * 1.55, y + face[1] * 1.55, 7.65)
    cylinder_between(f"Streetlight_{index:02d}_Arm", (x, y, 7.45), arm_end, 0.09, mats["pole"], target)
    box(f"Streetlight_{index:02d}_Lamp", (1.1, 0.32, 0.16), arm_end, mats["lamp"], target, rotation_z=math.atan2(face[1], face[0]))


def signal(
    name: str,
    base: tuple[float, float],
    head: tuple[float, float],
    phase: str,
    mats: dict[str, bpy.types.Material],
    target: bpy.types.Collection,
) -> None:
    cylinder(f"Signal_{name}_Post", 0.16, 6.6, (base[0], base[1], 3.3), mats["pole"], target, vertices=16)
    cylinder_between(f"Signal_{name}_Arm", (base[0], base[1], 6.3), (head[0], head[1], 6.3), 0.13, mats["pole"], target)
    angle = math.atan2(head[1] - base[1], head[0] - base[0])
    box(f"Signal_{name}_Housing", (0.82, 0.58, 2.55), (head[0], head[1], 5.45), mats["signal_housing"], target, rotation_z=angle, bevel=0.12)
    lens_offset = Vector((math.cos(angle), math.sin(angle))) * 0.32
    for lens_name, z in [("Red", 6.16), ("Amber", 5.45), ("Green", 4.74)]:
        uv_sphere(
            f"Signal_{name}_{lens_name}",
            0.245,
            (head[0] + lens_offset.x, head[1] + lens_offset.y, z),
            mats[f"signal_{phase.lower()}_{lens_name.lower()}"],
            target,
            scale=(0.45, 1.0, 1.0),
            segments=16,
        )


def build_context(static: bpy.types.Collection, mats: dict[str, bpy.types.Material]) -> None:
    building_specs = [
        (0, (-34.0, -52.0), (23.0, 17.0), 8, 0.04),
        (1, (-38.0, 12.0), (28.0, 19.0), 10, -0.04),
        (3, (82.0, 29.0), (31.0, 18.0), 11, -0.03),
        (4, (128.0, 25.0), (29.0, 19.0), 8, -0.02),
        (5, (53.0, -33.0), (30.0, 17.0), 9, -0.02),
        (6, (103.0, -35.0), (25.0, 20.0), 6, -0.02),
        (7, (-66.0, 85.0), (25.0, 17.0), 9, -0.38),
    ]
    for spec in building_specs:
        building(spec[0], spec[1], spec[2], spec[3], mats, static, rotation=spec[4])
    civic_building(2, (42.0, 33.0), mats, static)

    tree_positions: list[tuple[float, float]] = []
    for y in range(-138, 142, 15):
        if -21 < y < 24:
            continue
        tree_positions.extend([(-11.5, float(y)), (11.5, float(y))])
    for x in range(28, 158, 15):
        tree_positions.extend([(float(x), 11.8), (float(x), -13.0)])
    tree_positions.extend([(-18.0, 30.0), (-25.0, 45.0), (-34.0, 60.0), (-47.0, 78.0)])
    for index, (x, y) in enumerate(tree_positions):
        tree_instance(index, x, y, 0.82 + (index % 5) * 0.045, mats, static)

    shrub_positions = [
        (-12.5, -26.0), (-15.5, -28.5), (-18.5, -31.0),
        (-13.0, 25.0), (-16.0, 28.0), (-19.0, 31.0),
        (28.0, 13.2), (35.0, 13.0), (42.0, 12.8),
        (30.0, -14.0), (37.0, -14.2), (44.0, -14.4),
    ]
    for index, (x, y) in enumerate(shrub_positions):
        uv_sphere(
            f"Shrub_{index:02d}",
            0.72 + (index % 3) * 0.08,
            (x, y, 0.78),
            mats["leaf_b" if index % 2 else "leaf_a"],
            static,
            scale=(1.45, 0.86, 0.92),
        )

    light_positions = [
        (-10.3, -78.0, (1.0, 0.0)),
        (10.3, -45.0, (-1.0, 0.0)),
        (-10.3, 42.0, (1.0, 0.0)),
        (-17.0, 84.0, (1.0, -0.2)),
        (28.0, 10.2, (0.0, -1.0)),
        (62.0, -10.7, (0.0, 1.0)),
        (98.0, 10.0, (0.0, -1.0)),
        (136.0, -11.0, (0.0, 1.0)),
    ]
    for index, (x, y, face) in enumerate(light_positions):
        streetlight(index, x, y, face, mats, static)

    signal("South", (-9.0, -18.4), (-3.0, -18.4), "NS", mats, static)
    signal("North", (9.0, 18.5), (3.0, 18.5), "NS", mats, static)
    signal("East", (21.5, -8.6), (21.5, -3.0), "EW", mats, static)

    # Seating, bollards, drainage grates and a compact identity sign add close-range scale cues.
    for index, (x, y) in enumerate([(-9.2, -8.2), (-9.2, 7.8), (13.1, 8.4), (13.2, -8.4)]):
        for offset in (-1.15, 0.0, 1.15):
            cylinder(f"Bollard_{index}_{offset}", 0.09, 0.82, (x + offset if index < 2 else x, y if index < 2 else y + offset, 0.55), mats["pole"], static, vertices=12)
    for index, y in enumerate([-35.0, 36.0, 72.0]):
        box(f"Drain_{index}", (0.62, 1.25, 0.035), (7.35, y, 0.225), mats["drain"], static)
    box("K06_SignPanel", (4.7, 0.28, 1.5), (-13.2, -24.0, 2.15), mats["sign_blue"], static, bevel=0.12)
    cylinder("K06_SignPost_A", 0.085, 2.9, (-14.8, -24.0, 1.45), mats["pole"], static)
    cylinder("K06_SignPost_B", 0.085, 2.9, (-11.6, -24.0, 1.45), mats["pole"], static)


def create_anchor(name: str, location: tuple[float, float, float], target: bpy.types.Collection) -> None:
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_type = "ARROWS"
    obj.empty_display_size = 2.0
    obj.location = location
    target.objects.link(obj)


def build_vehicle(target: bpy.types.Collection, mats: dict[str, bpy.types.Material]) -> None:
    box("Vehicle_Chassis", (4.65, 1.88, 0.58), (0.0, 0.0, 0.67), mats["vehicle_paint"], target, bevel=0.24)
    box("Vehicle_Lower", (4.35, 1.82, 0.36), (0.02, 0.0, 0.38), mats["vehicle_dark"], target, bevel=0.16)
    box("Vehicle_Cabin", (2.55, 1.66, 0.72), (-0.18, 0.0, 1.19), mats["vehicle_glass"], target, bevel=0.32)
    box("Vehicle_Roof", (1.55, 1.54, 0.12), (-0.2, 0.0, 1.57), mats["vehicle_paint"], target, bevel=0.06)
    box("Vehicle_Hood", (1.15, 1.76, 0.12), (1.65, 0.0, 1.0), mats["vehicle_paint"], target, bevel=0.08)
    box("Vehicle_Trunk", (0.8, 1.75, 0.13), (-1.83, 0.0, 0.96), mats["vehicle_paint"], target, bevel=0.08)
    for x in (-1.45, 1.45):
        for y in (-0.96, 0.96):
            cylinder("Vehicle_Wheel", 0.39, 0.23, (x, y, 0.43), mats["tire"], target, vertices=24, rotation=(math.pi * 0.5, 0.0, 0.0))
            cylinder("Vehicle_Rim", 0.22, 0.245, (x, y, 0.43), mats["rim"], target, vertices=18, rotation=(math.pi * 0.5, 0.0, 0.0))
    for y in (-0.58, 0.58):
        box("Vehicle_Headlight", (0.12, 0.46, 0.16), (2.32, y, 0.82), mats["headlight"], target, bevel=0.05)
        box("Vehicle_Taillight", (0.11, 0.42, 0.16), (-2.32, y, 0.8), mats["taillight"], target, bevel=0.04)
    box("Vehicle_FrontGrille", (0.08, 0.72, 0.18), (2.34, 0.0, 0.52), mats["vehicle_dark"], target, bevel=0.04)
    for y in (-0.97, 0.97):
        box("Vehicle_Mirror", (0.32, 0.16, 0.13), (0.45, y, 1.2), mats["vehicle_paint"], target, bevel=0.05)


def join_material_groups(target: bpy.types.Collection, prefix: str) -> None:
    groups: dict[str, list[bpy.types.Object]] = {}
    for obj in list(target.objects):
        if obj.type != "MESH" or not obj.data.materials:
            continue
        key = obj.data.materials[0].name
        groups.setdefault(key, []).append(obj)
    for material_name, objects in groups.items():
        if len(objects) < 2:
            continue
        bpy.ops.object.select_all(action="DESELECT")
        for obj in objects:
            obj.select_set(True)
        active = objects[0]
        bpy.context.view_layer.objects.active = active
        bpy.ops.object.join()
        active.name = f"{prefix}_{material_name}"


def look_at(obj: bpy.types.Object, target: tuple[float, float, float]) -> None:
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def setup_presentation(target: bpy.types.Collection) -> None:
    world = bpy.data.worlds.new("K06_ClearSky") if bpy.context.scene.world is None else bpy.context.scene.world
    bpy.context.scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.40, 0.62, 0.83, 1.0)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.42

    sun_data = bpy.data.lights.new("K06_Sun", type="SUN")
    sun_data.energy = 3.1
    sun_data.angle = math.radians(5.0)
    sun = bpy.data.objects.new("K06_Sun", sun_data)
    sun.rotation_euler = (math.radians(31), math.radians(-18), math.radians(-36))
    target.objects.link(sun)

    area_data = bpy.data.lights.new("K06_SkyFill", type="AREA")
    area_data.energy = 780.0
    area_data.shape = "DISK"
    area_data.size = 80.0
    area = bpy.data.objects.new("K06_SkyFill", area_data)
    area.location = (-35.0, -45.0, 85.0)
    look_at(area, (15.0, 10.0, 0.0))
    target.objects.link(area)

    camera_data = bpy.data.cameras.new("K06_HeroCamera")
    camera_data.lens = 47.0
    camera_data.sensor_width = 36.0
    camera = bpy.data.objects.new("K06_HeroCamera", camera_data)
    camera.location = (105.0, -118.0, 96.0)
    look_at(camera, (18.0, 12.0, 2.0))
    target.objects.link(camera)
    bpy.context.scene.camera = camera

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = 1500
    scene.render.resolution_y = 960
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(PREVIEW_PATH)
    scene.render.film_transparent = False
    scene.render.image_settings.color_mode = "RGBA"
    scene.view_settings.look = "AgX - Medium High Contrast"


def export_collection(target: bpy.types.Collection, path: Path) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    for obj in target.objects:
        obj.select_set(True)
    bpy.ops.export_scene.gltf(
        filepath=str(path),
        export_format="GLB",
        use_selection=True,
        export_yup=True,
        export_apply=True,
        export_cameras=False,
        export_lights=False,
        export_texcoords=True,
        export_normals=True,
        export_tangents=False,
        export_materials="EXPORT",
    )


def main() -> None:
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    TEXTURE_DIR.mkdir(parents=True, exist_ok=True)
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    reset_scene()
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0

    textures = build_textures()
    mats: dict[str, bpy.types.Material] = {
        "asphalt": material("Road_Asphalt_PBR", (0.1, 0.11, 0.12, 1.0), roughness=0.91, image=textures["asphalt"]),
        "grass": material("Landscape_Grass_PBR", (0.18, 0.31, 0.18, 1.0), roughness=0.96, image=textures["grass"]),
        "paving": material("Sidewalk_Paving_PBR", (0.58, 0.56, 0.53, 1.0), roughness=0.9, image=textures["paving"]),
        "curb": material("Curb_Concrete", (0.58, 0.58, 0.55, 1.0), roughness=0.88),
        "white": material("Road_Marking_White", (0.92, 0.93, 0.9, 1.0), roughness=0.68),
        "yellow": material("Road_Marking_Yellow", (0.95, 0.66, 0.12, 1.0), roughness=0.65),
        "tactile": material("Tactile_Paving", (0.87, 0.63, 0.12, 1.0), roughness=0.82),
        "bike": material("Bike_Lane_Green", (0.16, 0.43, 0.32, 1.0), roughness=0.88),
        "stone_light": material("Architecture_Pearl", (0.71, 0.75, 0.74, 1.0), roughness=0.62),
        "stone_warm": material("Architecture_WarmStone", (0.66, 0.62, 0.54, 1.0), roughness=0.7),
        "stone_dark": material("Architecture_Charcoal", (0.23, 0.28, 0.29, 1.0), roughness=0.5, metallic=0.08),
        "glass": material("Architecture_LowEGlass", (0.12, 0.28, 0.34, 1.0), roughness=0.16, metallic=0.38),
        "roof": material("Architecture_Roof", (0.22, 0.25, 0.25, 1.0), roughness=0.76),
        "solar": material("Architecture_SolarPanel", (0.035, 0.12, 0.2, 1.0), roughness=0.24, metallic=0.48),
        "bark": material("Landscape_Bark", (0.26, 0.17, 0.09, 1.0), roughness=0.98),
        "leaf_a": material("Landscape_Leaf_A", (0.12, 0.36, 0.22, 1.0), roughness=0.88),
        "leaf_b": material("Landscape_Leaf_B", (0.22, 0.45, 0.24, 1.0), roughness=0.9),
        "pole": material("Street_Furniture_Metal", (0.08, 0.12, 0.13, 1.0), roughness=0.34, metallic=0.76),
        "lamp": material("Street_Lamp_Lens", (0.8, 0.92, 0.9, 1.0), roughness=0.22, emission=(0.75, 0.95, 0.9, 1.0), emission_strength=1.4),
        "signal_housing": material("Signal_Housing", (0.018, 0.028, 0.03, 1.0), roughness=0.48),
        "signal_ns_red": material("Signal_NS_Red", (0.18, 0.02, 0.01, 1.0), roughness=0.32, emission=(1.0, 0.03, 0.01, 1.0), emission_strength=2.8),
        "signal_ns_amber": material("Signal_NS_Amber", (0.2, 0.11, 0.01, 1.0), roughness=0.32, emission=(1.0, 0.35, 0.01, 1.0), emission_strength=0.06),
        "signal_ns_green": material("Signal_NS_Green", (0.01, 0.18, 0.08, 1.0), roughness=0.32, emission=(0.02, 1.0, 0.34, 1.0), emission_strength=0.06),
        "signal_ew_red": material("Signal_EW_Red", (0.18, 0.02, 0.01, 1.0), roughness=0.32, emission=(1.0, 0.03, 0.01, 1.0), emission_strength=0.05),
        "signal_ew_amber": material("Signal_EW_Amber", (0.2, 0.11, 0.01, 1.0), roughness=0.32, emission=(1.0, 0.35, 0.01, 1.0), emission_strength=0.06),
        "signal_ew_green": material("Signal_EW_Green", (0.01, 0.18, 0.08, 1.0), roughness=0.32, emission=(0.02, 1.0, 0.34, 1.0), emission_strength=2.8),
        "drain": material("Drainage_Grate", (0.08, 0.09, 0.09, 1.0), roughness=0.42, metallic=0.72),
        "sign_blue": material("Wayfinding_Blue", (0.03, 0.22, 0.43, 1.0), roughness=0.46, metallic=0.12),
        "vehicle_paint": material("VehiclePaint", (0.69, 0.77, 0.78, 1.0), roughness=0.26, metallic=0.52),
        "vehicle_dark": material("VehicleDark", (0.025, 0.035, 0.04, 1.0), roughness=0.38, metallic=0.34),
        "vehicle_glass": material("VehicleGlass", (0.045, 0.12, 0.16, 1.0), roughness=0.14, metallic=0.46),
        "tire": material("VehicleTire", (0.012, 0.014, 0.015, 1.0), roughness=0.88),
        "rim": material("VehicleRim", (0.3, 0.33, 0.34, 1.0), roughness=0.26, metallic=0.82),
        "headlight": material("VehicleHeadlight", (0.72, 0.88, 0.92, 1.0), roughness=0.2, emission=(0.8, 0.95, 1.0, 1.0), emission_strength=1.2),
        "taillight": material("VehicleTaillight", (0.38, 0.015, 0.008, 1.0), roughness=0.24, emission=(1.0, 0.02, 0.008, 1.0), emission_strength=1.0),
    }

    static = collection(STATIC_NAME)
    vehicle = collection(VEHICLE_NAME)
    presentation = collection(PRESENTATION_NAME)
    build_roads(static, mats)
    build_context(static, mats)
    create_anchor("Anchor_K06_Origin", (0.0, 0.0, 0.0), static)
    create_anchor("Anchor_Camera_Overview", (96.0, -108.0, 74.0), static)
    create_anchor("Anchor_Camera_Street", (30.0, -54.0, 6.5), static)
    build_vehicle(vehicle, mats)
    join_material_groups(static, "K06")
    join_material_groups(vehicle, "Vehicle")
    setup_presentation(presentation)

    for obj in static.objects:
        if obj.type == "MESH":
            obj.select_set(True)
    bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH), compress=True)
    export_collection(static, SCENE_GLB_PATH)
    export_collection(vehicle, VEHICLE_GLB_PATH)
    bpy.context.scene.render.filepath = str(PREVIEW_PATH)
    bpy.ops.render.render(write_still=True)
    print(f"K06_BLEND={BLEND_PATH}")
    print(f"K06_SCENE_GLB={SCENE_GLB_PATH}")
    print(f"K06_VEHICLE_GLB={VEHICLE_GLB_PATH}")
    print(f"K06_PREVIEW={PREVIEW_PATH}")


if __name__ == "__main__":
    main()
