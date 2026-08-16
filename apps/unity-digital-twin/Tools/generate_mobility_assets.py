import math
import os
import sys

import bpy
from mathutils import Vector


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for block in bpy.data.meshes:
        if block.users == 0:
            bpy.data.meshes.remove(block)


def material(name, color, metallic=0.0, roughness=0.45):
    value = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    value.diffuse_color = (*color, 1.0)
    value.metallic = metallic
    value.roughness = roughness
    return value


def finish_mesh(obj, mat, smooth=True):
    obj.data.materials.append(mat)
    if smooth:
        for polygon in obj.data.polygons:
            polygon.use_smooth = True
    return obj


def empty(name, parent=None, location=(0.0, 0.0, 0.0)):
    obj = bpy.data.objects.new(name, None)
    bpy.context.collection.objects.link(obj)
    obj.parent = parent
    obj.location = location
    return obj


def sphere(name, parent, location, scale, mat, segments=24, rings=16):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=segments, ring_count=rings)
    obj = bpy.context.object
    obj.name = name
    obj.parent = parent
    obj.location = location
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return finish_mesh(obj, mat)


def beveled_box(name, parent, location, dimensions, mat, bevel=0.04, rotation=(0.0, 0.0, 0.0)):
    bpy.ops.mesh.primitive_cube_add()
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = dimensions
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if bevel > 0.0:
        modifier = obj.modifiers.new("Tailored edge roll", "BEVEL")
        modifier.width = bevel
        modifier.segments = 3
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.modifier_apply(modifier=modifier.name)
    obj.parent = parent
    obj.location = location
    obj.rotation_euler = rotation
    return finish_mesh(obj, mat)


def tapered_body(name, parent, location, height, profiles, mat, rotation=(0.0, 0.0, 0.0), segments=20):
    vertices = []
    faces = []
    for ring, (fraction, radius_x, radius_y) in enumerate(profiles):
        z = (fraction - 0.5) * height
        for segment in range(segments):
            angle = segment * math.tau / segments
            vertices.append((math.cos(angle) * radius_x, math.sin(angle) * radius_y, z))
        if ring > 0:
            previous = (ring - 1) * segments
            current = ring * segments
            for segment in range(segments):
                next_segment = (segment + 1) % segments
                faces.append((previous + segment, previous + next_segment, current + next_segment, current + segment))
    faces.append(tuple(range(segments - 1, -1, -1)))
    top_start = (len(profiles) - 1) * segments
    faces.append(tuple(top_start + index for index in range(segments)))
    mesh = bpy.data.meshes.new(name + "Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.parent = parent
    obj.location = location
    obj.rotation_euler = rotation
    return finish_mesh(obj, mat)


def limb(name, parent, length, upper_radius, lower_radius, mat, offset=(0.0, 0.0, 0.0)):
    bpy.ops.mesh.primitive_cone_add(vertices=20, radius1=lower_radius, radius2=upper_radius, depth=length)
    obj = bpy.context.object
    obj.name = name
    obj.parent = parent
    obj.location = (offset[0], offset[1], offset[2] - length * 0.5)
    return finish_mesh(obj, mat)


def rod_between(name, parent, start, end, radius, mat, vertices=16):
    start_value = Vector(start)
    end_value = Vector(end)
    direction = end_value - start_value
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=direction.length)
    obj = bpy.context.object
    obj.name = name
    obj.parent = parent
    obj.location = (start_value + end_value) * 0.5
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = direction.to_track_quat("Z", "Y")
    return finish_mesh(obj, mat)


def torus(name, parent, location, major_radius, minor_radius, mat, rotation=(0.0, 0.0, 0.0)):
    bpy.ops.mesh.primitive_torus_add(
        major_radius=major_radius,
        minor_radius=minor_radius,
        major_segments=40,
        minor_segments=10,
    )
    obj = bpy.context.object
    obj.name = name
    obj.parent = parent
    obj.location = location
    obj.rotation_euler = rotation
    return finish_mesh(obj, mat)


def build_pedestrian():
    clothing = material("Clothing", (0.12, 0.34, 0.68), roughness=0.62)
    trousers = material("Trousers", (0.055, 0.075, 0.105), roughness=0.72)
    skin = material("Skin", (0.66, 0.43, 0.29), roughness=0.58)
    hair = material("Hair", (0.035, 0.022, 0.018), roughness=0.84)
    shoes = material("Shoes", (0.025, 0.03, 0.036), roughness=0.66)

    root = empty("Pedestrian_HQ_Root")
    tapered_body(
        "Body_Clothing", root, (0.0, 0.0, 1.25), 0.72,
        [(0.0, 0.24, 0.15), (0.18, 0.26, 0.16), (0.46, 0.215, 0.14),
         (0.76, 0.34, 0.18), (0.92, 0.355, 0.18), (1.0, 0.17, 0.13)],
        clothing,
    )
    beveled_box("Waist_Trousers", root, (0.0, 0.0, 0.91), (0.44, 0.28, 0.22), trousers, 0.07)
    sphere("Head_Skin", root, (0.0, -0.01, 1.74), (0.225, 0.205, 0.265), skin)
    sphere("Hair_Cap", root, (0.0, 0.015, 1.89), (0.23, 0.21, 0.145), hair)
    sphere("Ear_L_Skin", root, (-0.222, -0.008, 1.74), (0.038, 0.027, 0.065), skin, 16, 10)
    sphere("Ear_R_Skin", root, (0.222, -0.008, 1.74), (0.038, 0.027, 0.065), skin, 16, 10)
    sphere("Nose_Skin", root, (0.0, -0.205, 1.75), (0.035, 0.05, 0.055), skin, 16, 10)

    for side, sign in (("L", -1.0), ("R", 1.0)):
        hip = empty(f"Hip_{side}", root, (0.13 * sign, 0.0, 0.89))
        limb(f"UpperLeg_{side}_Trousers", hip, 0.43, 0.12, 0.095, trousers)
        knee = empty(f"Knee_{side}", hip, (0.0, 0.0, -0.43))
        sphere(f"KneeCap_{side}_Trousers", knee, (0.0, -0.018, 0.0), (0.105, 0.1, 0.11), trousers, 16, 10)
        limb(f"LowerLeg_{side}_Trousers", knee, 0.42, 0.095, 0.072, trousers)
        ankle = empty(f"Ankle_{side}", knee, (0.0, 0.0, -0.42))
        beveled_box(f"Foot_{side}_Shoes", ankle, (0.0, -0.075, -0.025), (0.19, 0.34, 0.12), shoes, 0.045)

        shoulder = empty(f"Shoulder_{side}", root, (0.32 * sign, 0.0, 1.5))
        sphere(f"ShoulderCap_{side}_Clothing", shoulder, (0.0, 0.0, 0.0), (0.115, 0.105, 0.12), clothing, 16, 10)
        limb(f"UpperArm_{side}_Clothing", shoulder, 0.34, 0.09, 0.07, clothing)
        elbow = empty(f"Elbow_{side}", shoulder, (0.0, 0.0, -0.34))
        sphere(f"ElbowCap_{side}_Skin", elbow, (0.0, 0.0, 0.0), (0.074, 0.07, 0.078), skin, 16, 10)
        limb(f"Forearm_{side}_Skin", elbow, 0.31, 0.073, 0.055, skin)
        sphere(f"Hand_{side}_Skin", elbow, (0.0, -0.012, -0.335), (0.067, 0.05, 0.095), skin, 16, 10)
    return root


def build_wheel(root, name, center, rubber, metal):
    wheel_root = empty(name, root, center)
    torus(name + "_Tyre", wheel_root, (0.0, 0.0, 0.0), 0.435, 0.038, rubber, (0.0, math.pi * 0.5, 0.0))
    torus(name + "_Rim", wheel_root, (0.0, 0.0, 0.0), 0.375, 0.012, metal, (0.0, math.pi * 0.5, 0.0))
    rod_between(name + "_Hub", wheel_root, (-0.08, 0.0, 0.0), (0.08, 0.0, 0.0), 0.024, metal)
    for index in range(12):
        angle = index * math.tau / 12.0
        target = (0.0, math.cos(angle) * 0.365, math.sin(angle) * 0.365)
        rod_between(f"{name}_Spoke_{index:02d}", wheel_root, (0.0, 0.0, 0.0), target, 0.004, metal, 8)
    return wheel_root


def build_bicycle_rider():
    frame = material("Bike_Frame", (0.08, 0.32, 0.62), metallic=0.55, roughness=0.28)
    metal = material("Bike_Metal", (0.44, 0.48, 0.52), metallic=0.9, roughness=0.22)
    rubber = material("Bike_Rubber", (0.012, 0.016, 0.02), roughness=0.82)
    saddle = material("Bike_Saddle", (0.025, 0.03, 0.035), roughness=0.72)
    clothing = material("Rider_Clothing", (0.14, 0.42, 0.68), roughness=0.58)
    trousers = material("Rider_Trousers", (0.055, 0.075, 0.1), roughness=0.7)
    skin = material("Rider_Skin", (0.66, 0.43, 0.29), roughness=0.58)
    hair = material("Rider_Hair", (0.035, 0.022, 0.018), roughness=0.84)
    shoes = material("Rider_Shoes", (0.025, 0.03, 0.036), roughness=0.66)

    root = empty("Bicycle_Rider_HQ_Root")
    build_wheel(root, "Wheel_Rear", (0.0, -0.73, 0.47), rubber, metal)
    build_wheel(root, "Wheel_Front", (0.0, 0.73, 0.47), rubber, metal)

    frame_points = {
        "rear": (0.0, -0.72, 0.47), "crank": (0.0, -0.04, 0.66),
        "seat": (0.0, -0.18, 0.98), "head_low": (0.0, 0.51, 0.72),
        "head_high": (0.0, 0.47, 1.08), "front": (0.0, 0.72, 0.47),
    }
    for x in (-0.028, 0.028):
        def point(key):
            value = frame_points[key]
            return (x, value[1], value[2])
        rod_between(f"Frame_Chainstay_{x}", root, point("rear"), point("crank"), 0.025, frame)
        rod_between(f"Frame_Seatstay_{x}", root, point("rear"), point("seat"), 0.022, frame)
        rod_between(f"Frame_Seattube_{x}", root, point("crank"), point("seat"), 0.027, frame)
        rod_between(f"Frame_Downtube_{x}", root, point("crank"), point("head_low"), 0.032, frame)
        rod_between(f"Frame_Toptube_{x}", root, point("seat"), point("head_high"), 0.027, frame)
        rod_between(f"Fork_{x}", root, point("front"), point("head_high"), 0.022, metal)
    rod_between("Handlebar_Stem", root, frame_points["head_high"], (0.0, 0.52, 1.18), 0.025, metal)
    rod_between("Handlebar", root, (-0.31, 0.52, 1.18), (0.31, 0.52, 1.18), 0.02, metal)
    beveled_box("Bike_Saddle", root, (0.0, -0.22, 1.03), (0.22, 0.34, 0.075), saddle, 0.035)

    crank = empty("Crank", root, frame_points["crank"])
    torus("Chainring", crank, (0.0, 0.0, 0.0), 0.14, 0.012, metal, (0.0, math.pi * 0.5, 0.0))
    rod_between("Crank_Axle", crank, (-0.12, 0.0, 0.0), (0.12, 0.0, 0.0), 0.018, metal)
    rod_between("PedalArm_L", crank, (-0.095, 0.0, 0.0), (-0.095, 0.0, -0.18), 0.014, metal)
    rod_between("PedalArm_R", crank, (0.095, 0.0, 0.0), (0.095, 0.0, 0.18), 0.014, metal)
    beveled_box("Pedal_L", crank, (-0.095, 0.0, -0.2), (0.18, 0.09, 0.035), saddle, 0.012)
    beveled_box("Pedal_R", crank, (0.095, 0.0, 0.2), (0.18, 0.09, 0.035), saddle, 0.012)

    tapered_body(
        "Rider_Body_Clothing", root, (0.0, 0.1, 1.55), 0.66,
        [(0.0, 0.22, 0.145), (0.45, 0.205, 0.135), (0.82, 0.315, 0.17), (1.0, 0.16, 0.12)],
        clothing, rotation=(-math.radians(31.0), 0.0, 0.0),
    )
    beveled_box("Rider_Waist_Trousers", root, (0.0, -0.14, 1.24), (0.4, 0.28, 0.2), trousers, 0.06)
    sphere("Rider_Head_Skin", root, (0.0, 0.31, 1.95), (0.215, 0.2, 0.255), skin)
    sphere("Rider_Hair_Cap", root, (0.0, 0.33, 2.09), (0.22, 0.205, 0.14), hair)
    sphere("Rider_Nose_Skin", root, (0.0, 0.515, 1.95), (0.032, 0.05, 0.05), skin, 16, 10)

    for side, sign in (("L", -1.0), ("R", 1.0)):
        shoulder = (0.28 * sign, 0.24, 1.68)
        elbow = (0.34 * sign, 0.41, 1.47)
        hand = (0.29 * sign, 0.515, 1.2)
        shoulder_root = empty(f"Rider_Shoulder_{side}", root, shoulder)
        rod_between(
            f"Rider_UpperArm_{side}_Clothing", shoulder_root,
            (0.0, 0.0, 0.0), tuple(elbow[index] - shoulder[index] for index in range(3)),
            0.074, clothing,
        )
        elbow_offset = tuple(elbow[index] - shoulder[index] for index in range(3))
        elbow_root = empty(f"Rider_Elbow_{side}", shoulder_root, elbow_offset)
        sphere(f"Rider_ElbowCap_{side}_Skin", elbow_root, (0.0, 0.0, 0.0), (0.075, 0.075, 0.075), skin, 16, 10)
        hand_offset = tuple(hand[index] - elbow[index] for index in range(3))
        rod_between(f"Rider_Forearm_{side}_Skin", elbow_root, (0.0, 0.0, 0.0), hand_offset, 0.058, skin)
        sphere(f"Rider_Hand_{side}_Skin", elbow_root, hand_offset, (0.064, 0.052, 0.075), skin, 16, 10)

        hip = (0.135 * sign, -0.13, 1.24)
        knee = (0.145 * sign, 0.18 if sign < 0 else -0.28, 0.91)
        pedal = (0.095 * sign, -0.04, 0.48 if sign < 0 else 0.84)
        hip_root = empty(f"Rider_Hip_{side}", root, hip)
        knee_offset = tuple(knee[index] - hip[index] for index in range(3))
        rod_between(f"Rider_UpperLeg_{side}_Trousers", hip_root, (0.0, 0.0, 0.0), knee_offset, 0.105, trousers)
        knee_root = empty(f"Rider_Knee_{side}", hip_root, knee_offset)
        sphere(f"Rider_KneeCap_{side}_Trousers", knee_root, (0.0, 0.0, 0.0), (0.102, 0.102, 0.105), trousers, 16, 10)
        pedal_offset = tuple(pedal[index] - knee[index] for index in range(3))
        rod_between(f"Rider_LowerLeg_{side}_Skin", knee_root, (0.0, 0.0, 0.0), pedal_offset, 0.074, skin)
        beveled_box(f"Rider_Foot_{side}_Shoes", knee_root, pedal_offset, (0.18, 0.28, 0.09), shoes, 0.03)
    return root


def export_root(root, path):
    bpy.ops.object.select_all(action="DESELECT")
    root.select_set(True)
    for child in root.children_recursive:
        child.select_set(True)
    bpy.context.view_layer.objects.active = root
    bpy.ops.export_scene.fbx(
        filepath=path,
        use_selection=True,
        object_types={"EMPTY", "MESH"},
        apply_unit_scale=True,
        apply_scale_options="FBX_SCALE_UNITS",
        axis_forward="-Z",
        axis_up="Y",
        add_leaf_bones=False,
        bake_anim=False,
        mesh_smooth_type="FACE",
        path_mode="AUTO",
    )


def main():
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(args) != 1:
        raise RuntimeError("Expected one output directory argument")
    output = os.path.abspath(args[0])
    os.makedirs(output, exist_ok=True)
    bpy.context.scene.unit_settings.system = "METRIC"
    bpy.context.scene.unit_settings.scale_length = 1.0

    clear_scene()
    pedestrian = build_pedestrian()
    export_root(pedestrian, os.path.join(output, "pedestrian_hq.fbx"))

    clear_scene()
    bicycle = build_bicycle_rider()
    export_root(bicycle, os.path.join(output, "bicycle_rider_hq.fbx"))
    print("Generated mobility FBX assets in", output)


if __name__ == "__main__":
    main()
