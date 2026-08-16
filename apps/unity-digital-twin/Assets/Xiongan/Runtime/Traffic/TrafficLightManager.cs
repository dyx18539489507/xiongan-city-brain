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

        private readonly Dictionary<string, List<Head>> controllers = new();
        [SerializeField] private List<Controller> bakedControllers = new();
        private MaterialLibrary materials = null!;

        public void Build(SceneBuilder scene)
        {
            materials = scene.Materials;
            controllers.Clear();
            bakedControllers.Clear();
            foreach (var controller in scene.Document.TrafficLights)
            {
                var heads = new List<Head>();
                var candidates = new List<(int LinkIndex, LaneRecord Lane, Vector3 Position, Vector3 Forward, int Approach)>();
                foreach (var link in controller.Links
                             .GroupBy(item => item.FromLaneId)
                             .Select(group => group.OrderBy(item => item.LinkIndex).First()))
                {
                    if (!scene.Lanes.TryGetValue(link.FromLaneId, out var lane) || lane.Shape.Count < 2) continue;
                    var position = scene.Coordinates.ToWorld(lane.Shape[^1]);
                    var previous = scene.Coordinates.ToWorld(lane.Shape[^2]);
                    var forward = position - previous;
                    forward.y = 0f;
                    if (forward.sqrMagnitude < 0.001f) forward = Vector3.forward;
                    forward.Normalize();
                    var side = Vector3.Cross(Vector3.up, forward).normalized;
                    position += side * (lane.WidthM * 0.45f + 0.65f);
                    var heading = Mathf.Repeat(Mathf.Atan2(forward.x, forward.z) * Mathf.Rad2Deg, 360f);
                    var approach = Mathf.RoundToInt(heading / 90f) % 4;
                    candidates.Add((link.LinkIndex, lane, position, forward, approach));
                }
                foreach (var approach in candidates.GroupBy(item => item.Approach))
                {
                    var group = approach.ToList();
                    if (group.Count == 0) continue;
                    var forward = group.Aggregate(Vector3.zero, (sum, item) => sum + item.Forward).normalized;
                    if (forward.sqrMagnitude < 0.5f) forward = group[0].Forward;
                    // CoordinateService mirrors SUMO Y into Unity Z. Use SUMO traffic handedness
                    // here so "right side of the approach" remains the actual outer kerb.
                    var trafficRight = Vector3.Cross(forward, Vector3.up).normalized;
                    var localRight = Vector3.Cross(Vector3.up, forward).normalized;
                    var laneCenter = group.Aggregate(Vector3.zero, (sum, item) => sum + item.Position) / group.Count;
                    var rightEdge = group.Max(item =>
                        Vector3.Dot(item.Position - laneCenter, trafficRight) + item.Lane.WidthM * 0.5f);
                    var nominalHalfWidth = group.Sum(item => Mathf.Max(2.2f, item.Lane.WidthM)) * 0.5f + 0.8f;
                    rightEdge = Mathf.Clamp(rightEdge, 1.1f, Mathf.Min(9.5f, nominalHalfWidth));

                    // The support belongs on the outer footway, never in a traffic lane. The mast arm
                    // then reaches back over the centre of the controlled approach.
                    var polePosition = laneCenter + trafficRight * (rightEdge + 1.65f) - forward * 0.35f;
                    var headOffset = Vector3.Dot(laneCenter - polePosition, localRight);
                    var representative = group.OrderBy(item =>
                            Mathf.Abs(Vector3.Dot(item.Position - laneCenter, trafficRight)))
                        .First();
                    heads.Add(CreateHead(
                        controller.SumoTlsId,
                        representative.LinkIndex,
                        polePosition,
                        forward,
                        headOffset));
                }
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
                    SetLamp(head.Red, signal is 'r' or 'R', materials.SignalRed);
                    SetLamp(head.Yellow, signal is 'y' or 'Y', materials.SignalYellow);
                    SetLamp(head.Green, signal is 'g' or 'G', materials.SignalGreen);
                }
            }
        }

        private Head CreateHead(string tlsId, int linkIndex, Vector3 position, Vector3 forward, float headOffset)
        {
            var root = new GameObject($"信号灯-{tlsId}-{linkIndex}");
            root.transform.SetParent(transform, false);
            root.transform.position = position;
            root.transform.rotation = Quaternion.LookRotation(forward, Vector3.up);
            if (Mathf.Abs(headOffset) < 1.8f) headOffset = headOffset < 0f ? -1.8f : 1.8f;
            headOffset = Mathf.Clamp(headOffset, -10.5f, 10.5f);
            var armLength = Mathf.Abs(headOffset) + 0.55f;
            var armCenter = headOffset * 0.5f;
            CreatePrimitive(PrimitiveType.Cylinder, "信号灯立杆", root.transform, new Vector3(0f, 3.05f, 0f), new Vector3(0.11f, 3.05f, 0.11f), materials.Metal);
            CreatePrimitive(PrimitiveType.Cube, "悬臂", root.transform, new Vector3(armCenter, 6.05f, 0f), new Vector3(armLength, 0.13f, 0.13f), materials.Metal);
            CreatePrimitive(PrimitiveType.Cube, "信号灯背板", root.transform, new Vector3(headOffset, 5.45f, 0f), new Vector3(0.92f, 1.92f, 0.18f), materials.SignalDark, false);
            CreatePrimitive(PrimitiveType.Cube, "灯箱", root.transform, new Vector3(headOffset, 5.45f, -0.13f), new Vector3(0.66f, 1.66f, 0.34f), materials.SignalDark, false);
            var head = new Head { LinkIndex = linkIndex };
            head.Red = CreateLamp("红灯", root.transform, new Vector3(headOffset, 5.94f, -0.34f));
            head.Yellow = CreateLamp("黄灯", root.transform, new Vector3(headOffset, 5.45f, -0.34f));
            head.Green = CreateLamp("绿灯", root.transform, new Vector3(headOffset, 4.96f, -0.34f));
            SetLamp(head.Red, true, materials.SignalRed);
            return head;
        }

        private Renderer CreateLamp(string name, Transform parent, Vector3 position)
        {
            var bezel = CreatePrimitive(PrimitiveType.Cylinder, $"{name}金属遮光圈", parent,
                position + new Vector3(0f, 0f, 0.035f), new Vector3(0.35f, 0.13f, 0.35f), materials.SignalDark, false);
            bezel.transform.localRotation = Quaternion.Euler(90f, 0f, 0f);
            var visor = CreatePrimitive(PrimitiveType.Cube, $"{name}上遮光檐", parent,
                position + new Vector3(0f, 0.25f, -0.18f), new Vector3(0.62f, 0.075f, 0.46f), materials.SignalDark, false);
            visor.transform.localRotation = Quaternion.Euler(-8f, 0f, 0f);
            var lamp = CreatePrimitive(PrimitiveType.Cylinder, name, parent,
                position + new Vector3(0f, 0f, -0.12f), new Vector3(0.255f, 0.09f, 0.255f), materials.SignalDark, false);
            lamp.transform.localRotation = Quaternion.Euler(90f, 0f, 0f);
            return lamp.GetComponent<Renderer>();
        }

        private void SetLamp(Renderer renderer, bool active, Material activeMaterial)
        {
            renderer.sharedMaterial = active ? activeMaterial : materials.SignalDark;
        }

        private static GameObject CreatePrimitive(
            PrimitiveType primitive, string name, Transform parent, Vector3 localPosition,
            Vector3 localScale, Material material, bool castShadows = true)
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
