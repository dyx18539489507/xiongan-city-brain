using System.Collections.Generic;
using UnityEngine;
using Xiongan.DigitalTwin.Core;
using Xiongan.DigitalTwin.Data;
using Xiongan.DigitalTwin.Interaction;

namespace Xiongan.DigitalTwin.Entities
{
    public sealed class EntityActor : MonoBehaviour
    {
        public string Identifier { get; private set; } = string.Empty;
        public string Category { get; private set; } = string.Empty;
        public float Speed { get; private set; }

        private Vector3 fromPosition;
        private Vector3 targetPosition;
        private Quaternion fromRotation;
        private Quaternion targetRotation;
        private float elapsed;
        private float duration = 1f;
        private readonly List<Transform> wheels = new();
        private Renderer? brakeLeft;
        private Renderer? brakeRight;
        private Material? brakeOn;
        private Material? brakeOff;
        private Transform? mobilityModel;
        private Transform? leftHip;
        private Transform? rightHip;
        private Transform? leftKnee;
        private Transform? rightKnee;
        private Transform? leftShoulder;
        private Transform? rightShoulder;
        private Transform? bicycleCrank;
        private Quaternion leftHipBase;
        private Quaternion rightHipBase;
        private Quaternion leftKneeBase;
        private Quaternion rightKneeBase;
        private Quaternion leftShoulderBase;
        private Quaternion rightShoulderBase;
        private Vector3 mobilityBasePosition;
        private float animationClock;
        private float animationPhase;

        public void Initialise(string identifier, string category, MaterialLibrary materials, Color color)
        {
            Category = category;
            var selectable = gameObject.AddComponent<SelectableObject>();
            selectable.Kind = category;
            selectable.Provenance = "SUMO/TraCI realtime entity";
            Rebind(identifier);
            if (category == "pedestrian") BuildPedestrian(materials, color);
            else if (category == "bicycle") BuildBicycle(materials, color);
            else BuildVehicle(materials, color, StableHash(identifier) % 3);
        }

        public void Rebind(string identifier)
        {
            Identifier = identifier;
            animationPhase = StableHash(identifier) % 1024 / 1024f * Mathf.PI * 2f;
            name = $"{Category}-{identifier}";
            var selectable = GetComponent<SelectableObject>();
            if (selectable != null) selectable.Identifier = identifier;
        }

        public void SetTarget(float x, float y, float angle, float speed, float tickHz, CoordinateService coordinates, bool immediate = false)
        {
            Speed = speed;
            fromPosition = transform.position;
            fromRotation = transform.rotation;
            targetPosition = coordinates.ToWorld(x, y, Category == "pedestrian" ? 0.03f : Category == "bicycle" ? 0.02f : 0.04f);
            targetRotation = coordinates.ToWorldRotation(angle);
            duration = Mathf.Clamp(1f / Mathf.Max(0.1f, tickHz), 0.08f, 1.5f);
            elapsed = 0f;
            if (immediate)
            {
                transform.SetPositionAndRotation(targetPosition, targetRotation);
                fromPosition = targetPosition;
                fromRotation = targetRotation;
                elapsed = duration;
            }
        }

        public void SetBrake(bool brake)
        {
            if (brakeLeft != null) brakeLeft.sharedMaterial = brake ? brakeOn : brakeOff;
            if (brakeRight != null) brakeRight.sharedMaterial = brake ? brakeOn : brakeOff;
        }

        private void Update()
        {
            elapsed = Mathf.Min(duration, elapsed + Time.deltaTime);
            var progress = duration <= 0f ? 1f : Mathf.SmoothStep(0f, 1f, elapsed / duration);
            transform.SetPositionAndRotation(Vector3.LerpUnclamped(fromPosition, targetPosition, progress), Quaternion.Slerp(fromRotation, targetRotation, progress));
            var rotation = Speed * Time.deltaTime * 115f;
            foreach (var wheel in wheels) wheel.Rotate(rotation, 0f, 0f, Space.Self);
            if (bicycleCrank != null) bicycleCrank.Rotate(rotation * 1.82f, 0f, 0f, Space.Self);
            animationClock += Time.deltaTime * Mathf.Lerp(2.2f, 8.4f, Mathf.Clamp01(Speed / 2.2f));
            if (Category == "pedestrian") AnimatePedestrian();
            else if (Category == "bicycle") AnimateBicycleRider();
        }

        private void BuildVehicle(MaterialLibrary materials, Color color, int variant)
        {
            var paint = materials.Create(color, 0.82f, 0.34f);
            if (BuildLicensedVehicleMesh(materials, paint, variant))
            {
                var licensedCollider = gameObject.AddComponent<BoxCollider>();
                licensedCollider.center = new Vector3(0f, 0.83f, 0f);
                licensedCollider.size = new Vector3(1.92f, 1.68f, 4.72f);
                return;
            }
            var body = new GameObject("流线型车身");
            body.transform.SetParent(transform, false);
            var filter = body.AddComponent<MeshFilter>();
            filter.sharedMesh = CreateCarBodyMesh(variant);
            body.AddComponent<MeshRenderer>().sharedMaterial = paint;

            var cabinHeight = variant == 1 ? 1.08f : 0.88f;
            var cabinZ = variant == 2 ? -0.14f : -0.24f;
            CreateCabinMesh(materials, paint, variant, cabinHeight, cabinZ);
            CreatePrimitive(PrimitiveType.Cube, "前格栅", transform, new Vector3(0f, 0.57f, 2.19f), new Vector3(1.24f, 0.22f, 0.055f), materials.SignalDark);
            CreatePrimitive(PrimitiveType.Cube, "前保险杠镀铬饰条", transform, new Vector3(0f, 0.38f, 2.2f), new Vector3(1.45f, 0.07f, 0.06f), materials.Chrome);
            CreatePrimitive(PrimitiveType.Cube, "左前灯", transform, new Vector3(-0.61f, 0.73f, 2.12f), new Vector3(0.46f, 0.16f, 0.075f), materials.Headlight);
            CreatePrimitive(PrimitiveType.Cube, "右前灯", transform, new Vector3(0.61f, 0.73f, 2.12f), new Vector3(0.46f, 0.16f, 0.075f), materials.Headlight);
            CreatePrimitive(PrimitiveType.Cube, "左后视镜", transform, new Vector3(-1.01f, 1.13f, 0.62f), new Vector3(0.18f, 0.12f, 0.34f), paint);
            CreatePrimitive(PrimitiveType.Cube, "右后视镜", transform, new Vector3(1.01f, 1.13f, 0.62f), new Vector3(0.18f, 0.12f, 0.34f), paint);
            foreach (var x in new[] { -0.91f, 0.91f })
            foreach (var z in new[] { -1.38f, 1.38f })
            {
                var wheel = CreatePrimitive(PrimitiveType.Cylinder, "轮胎", transform, new Vector3(x, 0.38f, z), new Vector3(0.39f, 0.17f, 0.39f), materials.Rubber);
                wheel.transform.localRotation = Quaternion.Euler(0f, 0f, 90f);
                wheels.Add(wheel.transform);
                var rim = CreatePrimitive(PrimitiveType.Cylinder, "合金轮毂", wheel.transform, Vector3.zero, new Vector3(0.58f, 1.04f, 0.58f), materials.Chrome);
                rim.transform.localRotation = Quaternion.identity;
            }
            brakeOff = materials.Create(new Color(0.18f, 0.008f, 0.004f), 0.48f, 0f);
            brakeOn = materials.SignalRed;
            brakeLeft = CreatePrimitive(PrimitiveType.Cube, "左尾灯", transform, new Vector3(-0.59f, 0.71f, -2.13f), new Vector3(0.42f, 0.17f, 0.075f), brakeOff).GetComponent<Renderer>();
            brakeRight = CreatePrimitive(PrimitiveType.Cube, "右尾灯", transform, new Vector3(0.59f, 0.71f, -2.13f), new Vector3(0.42f, 0.17f, 0.075f), brakeOff).GetComponent<Renderer>();
            var collider = gameObject.AddComponent<BoxCollider>();
            collider.center = new Vector3(0f, 0.82f, 0f);
            collider.size = new Vector3(1.9f, 1.72f, 4.42f);
        }

        private bool BuildLicensedVehicleMesh(MaterialLibrary materials, Material paint, int variant)
        {
            var resource = "Art/Models/cc0_car/car_byzmod3d_high_cc0";
            var source = Resources.Load<GameObject>(resource);
            if (source == null) return false;
            var model = Object.Instantiate(source, transform, false);
            model.name = "CC0现代轿车实体网格";
            var renderers = model.GetComponentsInChildren<Renderer>(true);
            if (renderers.Length == 0)
            {
                Object.Destroy(model);
                return false;
            }
            var bounds = renderers[0].bounds;
            for (var index = 1; index < renderers.Length; index++) bounds.Encapsulate(renderers[index].bounds);
            var targetLength = variant == 1 ? 4.36f : variant == 2 ? 4.78f : 4.62f;
            var scale = targetLength / Mathf.Max(0.01f, bounds.size.z);
            model.transform.localScale = Vector3.one * scale;
            model.transform.localPosition = new Vector3(0f, -bounds.min.y * scale + 0.035f, -bounds.center.z * scale);
            foreach (var renderer in renderers)
            {
                var assigned = renderer.sharedMaterials;
                for (var index = 0; index < assigned.Length; index++)
                {
                    var key = $"{renderer.name} {assigned[index]?.name}".ToLowerInvariant();
                    if (key.Contains("roda") || key.Contains("wheel") || key.Contains("tire") || key.Contains("pneu"))
                        assigned[index] = materials.Rubber;
                    else if (key.Contains("cor2"))
                        assigned[index] = materials.BuildingGlass;
                    else if (key.Contains("cor3"))
                        assigned[index] = materials.Chrome;
                    else if (key.Contains("glass") || key.Contains("window") || key.Contains("vidro"))
                        assigned[index] = materials.BuildingGlass;
                    else if (key.Contains("chrome") || key.Contains("metal") || key.Contains("rim") || key.Contains("aro"))
                        assigned[index] = materials.Chrome;
                    else if (key.Contains("light") || key.Contains("lamp") || key.Contains("farol"))
                        assigned[index] = materials.Headlight;
                    else assigned[index] = paint;
                }
                renderer.sharedMaterials = assigned;
            }
            CreatePrimitive(PrimitiveType.Cube, "实体车前挡风玻璃", transform,
                new Vector3(0f, 1.29f, 0.63f), new Vector3(1.48f, 0.62f, 0.055f), materials.BuildingGlass)
                .transform.localRotation = Quaternion.Euler(62f, 0f, 0f);
            CreatePrimitive(PrimitiveType.Cube, "实体车后挡风玻璃", transform,
                new Vector3(0f, 1.25f, -0.72f), new Vector3(1.42f, 0.52f, 0.05f), materials.BuildingGlass)
                .transform.localRotation = Quaternion.Euler(-62f, 0f, 0f);
            brakeOff = materials.Create(new Color(0.18f, 0.008f, 0.004f), 0.48f, 0f);
            brakeOn = materials.SignalRed;
            brakeLeft = CreatePrimitive(PrimitiveType.Cube, "实体车左尾灯", transform,
                new Vector3(-0.56f, 0.73f, -2.31f), new Vector3(0.4f, 0.16f, 0.07f), brakeOff).GetComponent<Renderer>();
            brakeRight = CreatePrimitive(PrimitiveType.Cube, "实体车右尾灯", transform,
                new Vector3(0.56f, 0.73f, -2.31f), new Vector3(0.4f, 0.16f, 0.07f), brakeOff).GetComponent<Renderer>();
            return true;
        }

        private void CreateCabinMesh(MaterialLibrary materials, Material paint, int variant, float cabinHeight, float cabinZ)
        {
            var mesh = new Mesh { name = "sloped-glass-cabin" };
            var bottomY = 0.88f;
            var topY = 1.58f + cabinHeight * 0.16f;
            var bottomFront = 0.98f + cabinZ;
            var bottomRear = -1.18f + cabinZ;
            var topFront = 0.46f + cabinZ;
            var topRear = -0.74f + cabinZ;
            var bw = variant == 1 ? 0.77f : 0.72f;
            var tw = bw * 0.83f;
            mesh.vertices = new[]
            {
                new Vector3(-bw,bottomY,bottomFront), new Vector3(bw,bottomY,bottomFront),
                new Vector3(-bw,bottomY,bottomRear), new Vector3(bw,bottomY,bottomRear),
                new Vector3(-tw,topY,topFront), new Vector3(tw,topY,topFront),
                new Vector3(-tw,topY,topRear), new Vector3(tw,topY,topRear),
            };
            mesh.triangles = new[]
            {
                0,1,5, 0,5,4, 1,3,7, 1,7,5, 3,2,6, 3,6,7,
                2,0,4, 2,4,6, 4,5,7, 4,7,6,
            };
            mesh.RecalculateNormals();
            mesh.RecalculateBounds();
            var cabin = new GameObject("四面斜切玻璃座舱");
            cabin.transform.SetParent(transform, false);
            cabin.AddComponent<MeshFilter>().sharedMesh = mesh;
            cabin.AddComponent<MeshRenderer>().sharedMaterial = materials.BuildingGlass;
            CreatePrimitive(PrimitiveType.Cube, "车顶金属框", transform,
                new Vector3(0f, topY + 0.045f, (topFront + topRear) * 0.5f),
                new Vector3(tw * 2f + 0.1f, 0.09f, topFront - topRear + 0.08f), paint);
        }

        private static Mesh CreateCarBodyMesh(int variant)
        {
            var halfWidth = variant == 1 ? 0.96f : 0.92f;
            var lower = 0.28f;
            var profiles = new[]
            {
                new Vector3(0.72f, 0.52f, 2.25f), new Vector3(halfWidth, 0.82f, 1.55f),
                new Vector3(halfWidth, variant == 1 ? 1.12f : 0.96f, 0.65f), new Vector3(halfWidth, 1.04f, -1.05f),
                new Vector3(0.78f, 0.7f, -2.22f),
            };
            var vertices = new List<Vector3>();
            foreach (var profile in profiles)
            {
                vertices.Add(new Vector3(-profile.x, lower, profile.z));
                vertices.Add(new Vector3(profile.x, lower, profile.z));
                vertices.Add(new Vector3(-profile.x, profile.y, profile.z));
                vertices.Add(new Vector3(profile.x, profile.y, profile.z));
            }
            var triangles = new List<int>();
            for (var i = 0; i < profiles.Length - 1; i++)
            {
                var a = i * 4;
                var b = (i + 1) * 4;
                AddFace(triangles, a, b, b + 2, a + 2);
                AddFace(triangles, a + 1, a + 3, b + 3, b + 1);
                AddFace(triangles, a + 2, b + 2, b + 3, a + 3);
                AddFace(triangles, a, a + 1, b + 1, b);
            }
            AddFace(triangles, 0, 2, 3, 1);
            var last = (profiles.Length - 1) * 4;
            AddFace(triangles, last, last + 1, last + 3, last + 2);
            var mesh = new Mesh { name = "procedural-photoreal-car-body" };
            mesh.SetVertices(vertices);
            mesh.SetTriangles(triangles, 0);
            mesh.RecalculateNormals();
            mesh.RecalculateBounds();
            return mesh;
        }

        private static void AddFace(List<int> triangles, int a, int b, int c, int d)
        {
            triangles.Add(a); triangles.Add(b); triangles.Add(c);
            triangles.Add(a); triangles.Add(c); triangles.Add(d);
        }

        private void BuildBicycle(MaterialLibrary materials, Color color)
        {
            const string resource = "Art/Models/generated_mobility/bicycle_rider_hq";
            var source = Resources.Load<GameObject>(resource);
            if (source == null)
            {
                Debug.LogError($"Required three-dimensional bicycle asset is missing: Resources/{resource}");
                return;
            }

            mobilityModel = Object.Instantiate(source, transform, false).transform;
            mobilityModel.name = "高精度三维自行车与骑行者";
            ApplyMobilityMaterials(mobilityModel, materials, color, true);
            FitMobilityModel(mobilityModel, 2.14f, 0.012f);
            mobilityBasePosition = mobilityModel.localPosition;

            var frontWheel = FindDescendant(mobilityModel, "Wheel_Front");
            var rearWheel = FindDescendant(mobilityModel, "Wheel_Rear");
            if (frontWheel != null) wheels.Add(frontWheel);
            if (rearWheel != null) wheels.Add(rearWheel);
            bicycleCrank = FindDescendant(mobilityModel, "Crank");
            BindMobilityJoints(mobilityModel, "Rider_");

            var collider = gameObject.AddComponent<CapsuleCollider>();
            collider.center = new Vector3(0f, 1.07f, 0f);
            collider.height = 2.14f;
            collider.radius = 0.43f;
        }

        private void BuildPedestrian(MaterialLibrary materials, Color color)
        {
            const string resource = "Art/Models/generated_mobility/pedestrian_hq";
            var source = Resources.Load<GameObject>(resource);
            if (source == null)
            {
                Debug.LogError($"Required three-dimensional pedestrian asset is missing: Resources/{resource}");
                return;
            }

            mobilityModel = Object.Instantiate(source, transform, false).transform;
            mobilityModel.name = "高精度三维行人";
            ApplyMobilityMaterials(mobilityModel, materials, color, false);
            FitMobilityModel(mobilityModel, 1.84f, 0.012f);
            mobilityBasePosition = mobilityModel.localPosition;
            BindMobilityJoints(mobilityModel, string.Empty);

            var collider = gameObject.AddComponent<CapsuleCollider>();
            collider.center = new Vector3(0f, 0.92f, 0f);
            collider.height = 1.84f;
            collider.radius = 0.28f;
        }

        private void AnimatePedestrian()
        {
            if (mobilityModel == null) return;
            var amount = Mathf.Clamp01(Speed / 1.55f);
            var cycle = animationClock + animationPhase;
            var stride = Mathf.Sin(cycle) * 29f * amount;
            SetJointRotation(leftHip, leftHipBase, stride);
            SetJointRotation(rightHip, rightHipBase, -stride);
            SetJointRotation(leftKnee, leftKneeBase, Mathf.Max(0f, -stride) * 0.72f);
            SetJointRotation(rightKnee, rightKneeBase, Mathf.Max(0f, stride) * 0.72f);
            SetJointRotation(leftShoulder, leftShoulderBase, -stride * 0.72f);
            SetJointRotation(rightShoulder, rightShoulderBase, stride * 0.72f);
            mobilityModel.localPosition = mobilityBasePosition + Vector3.up * (Mathf.Abs(Mathf.Sin(cycle)) * 0.024f * amount);
        }

        private void AnimateBicycleRider()
        {
            if (mobilityModel == null) return;
            var amount = Mathf.Clamp01(Speed / 4.5f);
            var cycle = animationClock + animationPhase;
            var pedal = Mathf.Sin(cycle) * 12f * amount;
            SetJointRotation(leftHip, leftHipBase, pedal);
            SetJointRotation(rightHip, rightHipBase, -pedal);
            SetJointRotation(leftKnee, leftKneeBase, -Mathf.Cos(cycle) * 10f * amount);
            SetJointRotation(rightKnee, rightKneeBase, Mathf.Cos(cycle) * 10f * amount);
            SetJointRotation(leftShoulder, leftShoulderBase, Mathf.Sin(cycle * 0.5f) * 1.4f * amount);
            SetJointRotation(rightShoulder, rightShoulderBase, -Mathf.Sin(cycle * 0.5f) * 1.4f * amount);
            mobilityModel.localPosition = mobilityBasePosition + Vector3.up * (Mathf.Abs(Mathf.Sin(cycle)) * 0.008f * amount);
        }

        private void BindMobilityJoints(Transform root, string prefix)
        {
            leftHip = FindDescendant(root, prefix + "Hip_L");
            rightHip = FindDescendant(root, prefix + "Hip_R");
            leftKnee = FindDescendant(root, prefix + "Knee_L");
            rightKnee = FindDescendant(root, prefix + "Knee_R");
            leftShoulder = FindDescendant(root, prefix + "Shoulder_L");
            rightShoulder = FindDescendant(root, prefix + "Shoulder_R");
            leftHipBase = GetLocalRotation(leftHip);
            rightHipBase = GetLocalRotation(rightHip);
            leftKneeBase = GetLocalRotation(leftKnee);
            rightKneeBase = GetLocalRotation(rightKnee);
            leftShoulderBase = GetLocalRotation(leftShoulder);
            rightShoulderBase = GetLocalRotation(rightShoulder);
        }

        private static void ApplyMobilityMaterials(Transform root, MaterialLibrary materials, Color accent, bool bicycle)
        {
            var clothing = materials.Create(Color.Lerp(accent, Color.white, 0.08f), 0.32f, 0f);
            var trousers = materials.Create(new Color(0.075f, 0.095f, 0.125f), 0.2f, 0f);
            var skin = materials.Create(new Color(0.75f, 0.54f, 0.4f), 0.3f, 0f);
            var hair = materials.Create(new Color(0.045f, 0.032f, 0.025f), 0.12f, 0f);
            var shoes = materials.Create(new Color(0.035f, 0.042f, 0.05f), 0.18f, 0f);
            var frame = materials.Create(Color.Lerp(accent, new Color(0.1f, 0.32f, 0.58f), 0.28f), 0.7f, 0.62f);
            foreach (var renderer in root.GetComponentsInChildren<Renderer>(true))
            {
                var lower = renderer.name.ToLowerInvariant();
                if (lower.Contains("tyre") || lower.Contains("rubber")) renderer.sharedMaterial = materials.Rubber;
                else if (lower.Contains("frame")) renderer.sharedMaterial = frame;
                else if (lower.Contains("rim") || lower.Contains("spoke") || lower.Contains("hub") ||
                         lower.Contains("fork") || lower.Contains("handlebar") || lower.Contains("chainring") ||
                         lower.Contains("crank") || lower.Contains("pedalarm")) renderer.sharedMaterial = materials.Chrome;
                else if (lower.Contains("saddle") || lower.Contains("pedal") || lower.Contains("shoes")) renderer.sharedMaterial = shoes;
                else if (lower.Contains("trousers")) renderer.sharedMaterial = trousers;
                else if (lower.Contains("skin")) renderer.sharedMaterial = skin;
                else if (lower.Contains("hair")) renderer.sharedMaterial = hair;
                else if (lower.Contains("clothing")) renderer.sharedMaterial = clothing;
                else renderer.sharedMaterial = bicycle ? frame : clothing;
                renderer.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.On;
                renderer.receiveShadows = true;
            }
        }

        private void FitMobilityModel(Transform model, float targetHeight, float groundOffset)
        {
            if (!TryGetLocalBounds(model, out var bounds)) return;
            var scale = targetHeight / Mathf.Max(0.01f, bounds.size.y);
            model.localScale *= scale;
            if (!TryGetLocalBounds(model, out bounds)) return;
            model.localPosition += new Vector3(-bounds.center.x, groundOffset - bounds.min.y, -bounds.center.z);
        }

        private bool TryGetLocalBounds(Transform model, out Bounds bounds)
        {
            bounds = default;
            var hasBounds = false;
            foreach (var renderer in model.GetComponentsInChildren<Renderer>(true))
            {
                var world = renderer.bounds;
                for (var x = -1; x <= 1; x += 2)
                for (var y = -1; y <= 1; y += 2)
                for (var z = -1; z <= 1; z += 2)
                {
                    var point = world.center + Vector3.Scale(world.extents, new Vector3(x, y, z));
                    point = transform.InverseTransformPoint(point);
                    if (!hasBounds)
                    {
                        bounds = new Bounds(point, Vector3.zero);
                        hasBounds = true;
                    }
                    else bounds.Encapsulate(point);
                }
            }
            return hasBounds;
        }

        private static Transform? FindDescendant(Transform parent, string childName)
        {
            foreach (var child in parent.GetComponentsInChildren<Transform>(true))
                if (child.name == childName) return child;
            return null;
        }

        private static Quaternion GetLocalRotation(Transform? target) => target == null ? Quaternion.identity : target.localRotation;

        private static void SetJointRotation(Transform? target, Quaternion basis, float xDegrees)
        {
            if (target != null) target.localRotation = basis * Quaternion.Euler(xDegrees, 0f, 0f);
        }

        private static GameObject CreateRod(string name, Transform parent, Vector3 from, Vector3 to, float radius, Material material)
        {
            var midpoint = (from + to) * 0.5f;
            var direction = to - from;
            var rod = CreatePrimitive(PrimitiveType.Cylinder, name, parent, midpoint, new Vector3(radius, direction.magnitude * 0.5f, radius), material);
            rod.transform.localRotation = Quaternion.FromToRotation(Vector3.up, direction.normalized);
            return rod;
        }

        private static GameObject CreatePrimitive(PrimitiveType primitive, string objectName, Transform parent, Vector3 localPosition, Vector3 localScale, Material material)
        {
            var gameObject = GameObject.CreatePrimitive(primitive);
            gameObject.name = objectName;
            gameObject.transform.SetParent(parent, false);
            gameObject.transform.localPosition = localPosition;
            gameObject.transform.localScale = localScale;
            gameObject.GetComponent<Renderer>().sharedMaterial = material;
            var collider = gameObject.GetComponent<Collider>();
            if (collider != null) Object.Destroy(collider);
            return gameObject;
        }

        private static int StableHash(string value)
        {
            unchecked
            {
                var hash = 17;
                foreach (var character in value) hash = hash * 31 + character;
                return Mathf.Abs(hash);
            }
        }
    }
}
