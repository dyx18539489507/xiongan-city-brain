using System.Collections.Generic;
using System.Linq;
using UnityEngine;
using Xiongan.DigitalTwin.Core;
using Xiongan.DigitalTwin.Data;
using Xiongan.DigitalTwin.Scene;

namespace Xiongan.DigitalTwin.Traffic
{
    public sealed class TrafficLightManager : MonoBehaviour
    {
        [System.Serializable]
        private sealed class Head
        {
            public int LinkIndex;
            public bool Pedestrian;
            public Renderer Red = null!;
            public Renderer Yellow = null!;
            public Renderer Green = null!;
        }

        [System.Serializable]
        private sealed class Controller
        {
            public string Id = string.Empty;
            public List<Head> Heads = new();
        }

        private sealed class ClearanceRibbon
        {
            public IReadOnlyList<Vector3> Points = null!;
            public float HalfWidth;
        }

        private readonly Dictionary<string, List<Head>> controllers = new();
        [SerializeField] private List<Controller> bakedControllers = new();
        private MaterialLibrary materials = null!;

        public void Build(SceneBuilder scene)
        {
            materials = scene.Materials;
            controllers.Clear();
            bakedControllers.Clear();
            var clearanceRibbons = scene.Document.Lanes
                .Where(lane => lane.Shape.Count >= 2 &&
                               lane.LaneKind is "motor" or "mixed" or "bicycle")
                .Select(lane => new ClearanceRibbon
                {
                    Points = lane.Shape.Select(point => scene.Coordinates.ToWorld(point)).ToArray(),
                    HalfWidth = Mathf.Max(1.1f, lane.WidthM * 0.5f) + 0.48f,
                })
                .ToArray();
            foreach (var controller in scene.Document.TrafficLights)
            {
                var heads = new List<Head>();
                var showcase = controller.SumoTlsId == ReferenceShowcaseLayout.JunctionId;
                var showcaseFrame = showcase ? ReferenceShowcaseLayout.Resolve(scene) : default;
                var candidates = new List<(string EdgeId, SignalApproachLane Lane)>();
                foreach (var link in controller.Links
                             .GroupBy(item => item.FromLaneId)
                             .Select(group => group.OrderBy(item => item.LinkIndex).First()))
                {
                    if (!scene.Lanes.TryGetValue(link.FromLaneId, out var lane) ||
                        lane.Shape.Count < 2 ||
                        lane.EdgeFunction == "internal" ||
                        lane.LaneKind is not "motor" and not "mixed")
                        continue;
                    var position = scene.Coordinates.ToWorld(lane.Shape[^1]);
                    var previous = scene.Coordinates.ToWorld(lane.Shape[^2]);
                    var forward = position - previous;
                    forward.y = 0f;
                    if (forward.sqrMagnitude < 0.001f) forward = Vector3.forward;
                    forward.Normalize();
                    candidates.Add((
                        string.IsNullOrWhiteSpace(lane.SumoEdgeId) ? lane.SumoLaneId : lane.SumoEdgeId,
                        new SignalApproachLane(
                        lane.SumoLaneId,
                        link.LinkIndex,
                        position,
                        forward,
                        lane.WidthM)));
                }

                var junctionShape = scene.Junctions.TryGetValue(controller.ControlledJunctionId, out var junction)
                    ? junction.Shape.Select(point => scene.Coordinates.ToWorld(point)).ToArray()
                    : System.Array.Empty<Vector3>();
                var crossingRibbons = scene.Document.Crossings
                    .Where(crossing => crossing.JunctionId == controller.ControlledJunctionId && crossing.Shape.Count >= 2)
                    .Select(crossing => new ClearanceRibbon
                    {
                        Points = crossing.Shape.Select(point => scene.Coordinates.ToWorld(point)).ToArray(),
                        HalfWidth = crossing.WidthM * 0.5f + 0.55f,
                    })
                    .ToArray();

                if (showcase)
                {
                    foreach (var approach in candidates.GroupBy(item => item.EdgeId))
                    {
                        var group = approach.Select(item => item.Lane).ToList();
                        if (group.Count == 0) continue;
                        heads.AddRange(CreateApproach(
                            controller.SumoTlsId,
                            group,
                            TrafficLightPlacementRules.ResolveShowcase(showcaseFrame, group),
                            false,
                            true));
                    }
                }
                else
                {
                    foreach (var approach in candidates.GroupBy(item => item.EdgeId))
                    {
                        var group = approach.Select(item => item.Lane).ToList();
                        if (group.Count == 0) continue;
                        var placement = TrafficLightPlacementRules.Resolve(
                            group,
                            candidate => IsPlacementBlocked(
                                candidate,
                                clearanceRibbons,
                                crossingRibbons,
                                junctionShape));
                        heads.AddRange(CreateApproach(
                            controller.SumoTlsId,
                            group,
                            placement,
                            false,
                            false));
                    }
                }
                if (showcase && heads.Count != 12)
                    Debug.LogError(
                        $"B01 visual signal audit failed: expected four vehicle and eight pedestrian heads, built {heads.Count}.");
                controllers[controller.SumoTlsId] = heads;
                bakedControllers.Add(new Controller { Id = controller.SumoTlsId, Heads = heads });
            }
        }

        public void RestoreBaked(SceneBuilder scene)
        {
            materials = scene.Materials;
            controllers.Clear();
            foreach (var controller in bakedControllers) controllers[controller.Id] = controller.Heads;
        }

        public void Apply(IEnumerable<TrafficLightEntity> states)
        {
            foreach (var state in states)
            {
                if (!controllers.TryGetValue(state.Id, out var heads)) continue;
                foreach (var head in heads)
                {
                    var signal = head.LinkIndex >= 0 && head.LinkIndex < state.State.Length ? state.State[head.LinkIndex] : 'o';
                    if (head.Pedestrian)
                    {
                        var walk = signal is 'g' or 'G';
                        SetLamp(head.Red, !walk, materials.SignalRed);
                        SetLamp(head.Green, walk, materials.SignalGreen);
                        continue;
                    }
                    SetLamp(head.Red, signal is 'r' or 'R', materials.SignalRed);
                    SetLamp(head.Yellow, signal is 'y' or 'Y', materials.SignalYellow);
                    SetLamp(head.Green, signal is 'g' or 'G', materials.SignalGreen);
                }
            }
        }

        private List<Head> CreateApproach(
            string tlsId,
            IReadOnlyList<SignalApproachLane> lanes,
            SignalApproachPlacement placement,
            bool compactRoadside,
            bool showcase)
        {
            var rootName = showcase ? "B01四角信号悬臂" : "路侧信号悬臂";
            var root = new GameObject($"{rootName}-{tlsId}-{lanes[0].LaneId}");
            root.transform.SetParent(transform, false);
            root.transform.position = placement.PolePosition;
            root.transform.rotation = Quaternion.LookRotation(placement.Forward, Vector3.up);
            var laneCenter = lanes.Aggregate(Vector3.zero, (sum, lane) => sum + lane.StopPoint) / lanes.Count;
            var representative = lanes
                .OrderBy(lane => Vector3.Distance(lane.StopPoint, laneCenter))
                .First();
            var heads = new List<Head>(showcase ? 2 : 1);
            if (compactRoadside)
            {
                CreateCompactRoadsideMast(root.transform);
                heads.Add(CreateHeadOnMast(
                    root.transform,
                    representative.LinkIndex,
                    0f,
                    true));
                return heads;
            }

            var headOffset = showcase
                ? TrafficLightPlacementRules.ResolveHeadOffset(
                    lanes, placement.PolePosition, placement.Forward, 6.2f, 9.6f)
                : TrafficLightPlacementRules.ResolveHeadOffset(
                    lanes, placement.PolePosition, placement.Forward, 4.6f, 17.2f);
            if (showcase)
                CreateShowcaseCornerCantilever(root.transform, headOffset);
            else
                CreateSingleHeadCantilever(root.transform, headOffset);
            heads.Add(CreateHeadOnMast(
                root.transform,
                representative.LinkIndex,
                headOffset,
                false,
                showcase));
            if (showcase)
                heads.AddRange(CreatePedestrianHeadsOnPole(
                    root.transform,
                    representative.LinkIndex,
                    TrafficLightPlacementRules.ResolvePedestrianFaceDirections(placement)));
            return heads;
        }

        private void CreateCompactRoadsideMast(Transform root)
        {
            CreatePrimitive(PrimitiveType.Cylinder, "路侧信号杆基座", root,
                new Vector3(0f, 0.18f, 0f), new Vector3(0.3f, 0.18f, 0.3f), materials.Metal);
            CreatePrimitive(PrimitiveType.Cylinder, "路侧信号杆压环", root,
                new Vector3(0f, 0.46f, 0f), new Vector3(0.2f, 0.075f, 0.2f), materials.Chrome);
            CreatePrimitive(PrimitiveType.Cylinder, "信号灯立杆", root,
                new Vector3(0f, 2.72f, 0f), new Vector3(0.13f, 2.72f, 0.13f), materials.Metal);
            CreateCylinderBetween("路侧灯箱短支架", root,
                new Vector3(0f, 4.78f, 0.02f), new Vector3(0f, 4.78f, -0.24f),
                0.085f, materials.Chrome);
            CreatePrimitive(PrimitiveType.Cylinder, "路侧信号杆端帽", root,
                new Vector3(0f, 5.47f, 0f), new Vector3(0.16f, 0.055f, 0.16f),
                materials.Chrome, false);
        }

        private void CreateSingleHeadCantilever(Transform root, float headOffset)
        {
            var direction = headOffset < 0f ? -1f : 1f;
            var armEnd = headOffset + direction * 0.9f;
            CreatePrimitive(PrimitiveType.Cylinder, "信号杆基座", root,
                new Vector3(0f, 0.2f, 0f), new Vector3(0.34f, 0.2f, 0.34f), materials.Metal);
            CreatePrimitive(PrimitiveType.Cylinder, "信号杆基座压环", root,
                new Vector3(0f, 0.52f, 0f), new Vector3(0.22f, 0.09f, 0.22f), materials.Chrome);
            CreatePrimitive(PrimitiveType.Cylinder, "信号灯立杆", root,
                new Vector3(0f, 2.95f, 0f), new Vector3(0.16f, 2.95f, 0.16f), materials.Metal);
            CreateCylinderBetween("悬臂弯头", root,
                new Vector3(0f, 5.72f, 0f), new Vector3(direction * 0.62f, 6.16f, 0f), 0.16f, materials.Metal);
            CreateCylinderBetween("悬臂", root,
                new Vector3(direction * 0.55f, 6.16f, 0f), new Vector3(armEnd, 6.16f, 0f), 0.16f, materials.Metal);
            CreateCylinderBetween("悬臂斜撑", root,
                new Vector3(0f, 5.18f, 0f), new Vector3(direction * 1.12f, 6.16f, 0f), 0.075f, materials.Chrome);
            CreatePrimitive(PrimitiveType.Cylinder, "悬臂端帽", root,
                new Vector3(armEnd + direction * 0.03f, 6.16f, 0f), new Vector3(0.2f, 0.045f, 0.2f), materials.Chrome, false)
                .transform.localRotation = Quaternion.Euler(0f, 0f, 90f);
        }

        private void CreateShowcaseCornerCantilever(Transform root, float headOffset)
        {
            var direction = headOffset < 0f ? -1f : 1f;
            var armEnd = headOffset + direction * 1.15f;
            CreatePrimitive(PrimitiveType.Cylinder, "B01信号杆石材基座", root,
                new Vector3(0f, 0.24f, 0f), new Vector3(0.52f, 0.24f, 0.52f), materials.Curb);
            CreatePrimitive(PrimitiveType.Cylinder, "B01信号杆金属底座", root,
                new Vector3(0f, 0.58f, 0f), new Vector3(0.34f, 0.16f, 0.34f), materials.Chrome);
            CreatePrimitive(PrimitiveType.Cylinder, "信号灯立杆", root,
                new Vector3(0f, 3.7f, 0f), new Vector3(0.23f, 3.12f, 0.23f), materials.Metal);
            CreateCylinderBetween("B01悬臂弯头", root,
                new Vector3(0f, 6.78f, 0f), new Vector3(direction * 0.82f, 7.42f, 0f), 0.23f, materials.Metal);
            CreateCylinderBetween("B01加粗悬臂", root,
                new Vector3(direction * 0.72f, 7.42f, 0f), new Vector3(armEnd, 7.42f, 0f), 0.23f, materials.Metal);
            CreateCylinderBetween("B01悬臂主斜撑", root,
                new Vector3(0f, 5.85f, 0f), new Vector3(direction * 1.62f, 7.42f, 0f), 0.11f, materials.Chrome);
            CreateCylinderBetween("B01悬臂灯箱吊杆", root,
                new Vector3(headOffset, 7.42f, 0f),
                new Vector3(headOffset, 7.08f, 0f), 0.095f, materials.Chrome);
            CreatePrimitive(PrimitiveType.Cylinder, "B01悬臂端帽", root,
                new Vector3(armEnd + direction * 0.04f, 7.42f, 0f), new Vector3(0.28f, 0.055f, 0.28f),
                materials.Chrome, false).transform.localRotation = Quaternion.Euler(0f, 0f, 90f);
        }

        private Head CreateHeadOnMast(
            Transform root, int linkIndex, float headOffset, bool compact = false, bool showcase = false)
        {
            var centerHeight = compact ? 4.78f : showcase ? 6.28f : 5.45f;
            var backSize = compact
                ? new Vector3(0.68f, 1.48f, 0.16f)
                : showcase
                    ? new Vector3(1.18f, 2.58f, 0.24f)
                    : new Vector3(0.92f, 1.92f, 0.18f);
            var boxSize = compact
                ? new Vector3(0.56f, 1.34f, 0.3f)
                : showcase
                    ? new Vector3(0.88f, 2.2f, 0.44f)
                    : new Vector3(0.66f, 1.66f, 0.34f);
            CreatePrimitive(PrimitiveType.Cube, "信号灯背板", root,
                new Vector3(headOffset, centerHeight, 0f), backSize,
                materials.SignalDark, false);
            CreatePrimitive(PrimitiveType.Cube, "灯箱", root,
                new Vector3(headOffset, centerHeight, -0.13f), boxSize, materials.SignalDark, false);
            var head = new Head { LinkIndex = linkIndex };
            var lampSpacing = compact ? 0.39f : showcase ? 0.68f : 0.49f;
            var lampScale = showcase ? 1.2f : 1f;
            head.Red = CreateLamp("红灯", root, new Vector3(headOffset, centerHeight + lampSpacing, -0.34f), compact, lampScale);
            head.Yellow = CreateLamp("黄灯", root, new Vector3(headOffset, centerHeight, -0.34f), compact, lampScale);
            head.Green = CreateLamp("绿灯", root, new Vector3(headOffset, centerHeight - lampSpacing, -0.34f), compact, lampScale);
            SetLamp(head.Red, true, materials.SignalRed);
            return head;
        }

        private IEnumerable<Head> CreatePedestrianHeadsOnPole(
            Transform root,
            int linkIndex,
            PedestrianFaceDirections directions)
        {
            yield return CreatePedestrianHead(
                root, linkIndex, "横向斑马线", directions.AcrossCrossing);
            yield return CreatePedestrianHead(
                root, linkIndex, "纵向斑马线", directions.AlongCrossing);
        }

        private Head CreatePedestrianHead(
            Transform root, int linkIndex, string crossingName, Vector3 faceDirection)
        {
            const float centerHeight = 3.08f;
            var mount = new GameObject($"B01{crossingName}行人信号侧装");
            mount.transform.SetParent(root, false);
            faceDirection = Vector3.ProjectOnPlane(faceDirection, Vector3.up).normalized;
            if (faceDirection.sqrMagnitude < 0.5f) faceDirection = -root.forward;
            // The emissive lenses are authored on the local -Z side.
            mount.transform.rotation = Quaternion.LookRotation(-faceDirection, Vector3.up);
            CreateCylinderBetween($"{crossingName}行人灯短支架", mount.transform,
                new Vector3(0f, centerHeight, 0f), new Vector3(0f, centerHeight, -0.22f),
                0.055f, materials.Chrome);
            CreatePrimitive(PrimitiveType.Cube, "行人信号灯背板", mount.transform,
                new Vector3(0f, centerHeight, -0.18f), new Vector3(0.72f, 1.2f, 0.16f),
                materials.SignalDark, false);
            CreatePrimitive(PrimitiveType.Cube, "行人灯箱", mount.transform,
                new Vector3(0f, centerHeight, -0.3f), new Vector3(0.58f, 1.02f, 0.3f),
                materials.SignalDark, false);
            var head = new Head { LinkIndex = linkIndex, Pedestrian = true };
            head.Red = CreateLamp($"{crossingName}行人红灯", mount.transform,
                new Vector3(0f, centerHeight + 0.25f, -0.5f), true, 0.76f);
            head.Green = CreateLamp($"{crossingName}行人绿灯", mount.transform,
                new Vector3(0f, centerHeight - 0.25f, -0.5f), true, 0.76f);
            SetLamp(head.Red, true, materials.SignalRed);
            return head;
        }

        private GameObject CreateCylinderBetween(
            string name, Transform parent, Vector3 from, Vector3 to, float radius, Material material)
        {
            var delta = to - from;
            var cylinder = CreatePrimitive(
                PrimitiveType.Cylinder,
                name,
                parent,
                (from + to) * 0.5f,
                new Vector3(radius, delta.magnitude * 0.5f, radius),
                material);
            cylinder.transform.localRotation = Quaternion.FromToRotation(Vector3.up, delta.normalized);
            return cylinder;
        }

        private static bool IsPlacementBlocked(
            Vector3 candidate,
            IReadOnlyList<ClearanceRibbon> roadRibbons,
            IReadOnlyList<ClearanceRibbon> crossingRibbons,
            IReadOnlyList<Vector3> junctionShape)
        {
            if (TrafficLightPlacementRules.PointInPolygonXZ(candidate, junctionShape)) return true;
            foreach (var ribbon in roadRibbons)
            {
                for (var segment = 0; segment < ribbon.Points.Count - 1; segment++)
                {
                    if (TrafficLightPlacementRules.DistanceToSegmentXZ(
                            candidate,
                            ribbon.Points[segment],
                            ribbon.Points[segment + 1]) <= ribbon.HalfWidth)
                        return true;
                }
            }
            foreach (var ribbon in crossingRibbons)
            {
                for (var segment = 0; segment < ribbon.Points.Count - 1; segment++)
                {
                    if (TrafficLightPlacementRules.DistanceToSegmentXZ(
                            candidate,
                            ribbon.Points[segment],
                            ribbon.Points[segment + 1]) <= ribbon.HalfWidth)
                        return true;
                }
            }
            return false;
        }

        private Renderer CreateLamp(
            string name, Transform parent, Vector3 position, bool compact = false, float scale = 1f)
        {
            var bezelRadius = (compact ? 0.27f : 0.35f) * scale;
            var visorSize = (compact ? new Vector3(0.48f, 0.065f, 0.38f) : new Vector3(0.62f, 0.075f, 0.46f)) * scale;
            var lampRadius = (compact ? 0.2f : 0.255f) * scale;
            var bezel = CreatePrimitive(PrimitiveType.Cylinder, $"{name}金属遮光圈", parent,
                position + new Vector3(0f, 0f, 0.035f * scale), new Vector3(bezelRadius, 0.13f * scale, bezelRadius), materials.SignalDark, false);
            bezel.transform.localRotation = Quaternion.Euler(90f, 0f, 0f);
            var visor = CreatePrimitive(PrimitiveType.Cube, $"{name}上遮光檐", parent,
                position + new Vector3(0f, (compact ? 0.2f : 0.25f) * scale, -0.18f * scale), visorSize, materials.SignalDark, false);
            visor.transform.localRotation = Quaternion.Euler(-8f, 0f, 0f);
            var lamp = CreatePrimitive(PrimitiveType.Cylinder, name, parent,
                position + new Vector3(0f, 0f, -0.12f * scale), new Vector3(lampRadius, 0.09f * scale, lampRadius), materials.SignalDark, false);
            lamp.transform.localRotation = Quaternion.Euler(90f, 0f, 0f);
            return lamp.GetComponent<Renderer>();
        }

        private void SetLamp(Renderer renderer, bool active, Material activeMaterial)
        {
            renderer.sharedMaterial = active ? activeMaterial : materials.SignalDark;
        }

        private static GameObject CreatePrimitive(
            PrimitiveType primitive, string name, Transform parent, Vector3 localPosition,
            Vector3 localScale, Material material, bool castShadows = false)
        {
            var gameObject = GameObject.CreatePrimitive(primitive);
            gameObject.name = name;
            gameObject.transform.SetParent(parent, false);
            gameObject.transform.localPosition = localPosition;
            gameObject.transform.localScale = localScale;
            var renderer = gameObject.GetComponent<Renderer>();
            renderer.sharedMaterial = material;
            renderer.shadowCastingMode = castShadows
                ? UnityEngine.Rendering.ShadowCastingMode.On
                : UnityEngine.Rendering.ShadowCastingMode.Off;
            var collider = gameObject.GetComponent<Collider>();
            if (collider != null) DestroyImmediate(collider);
            return gameObject;
        }
    }
}
