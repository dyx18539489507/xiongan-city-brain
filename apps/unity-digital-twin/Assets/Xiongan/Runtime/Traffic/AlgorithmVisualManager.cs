using System.Collections.Generic;
using System.Linq;
using Newtonsoft.Json.Linq;
using UnityEngine;
using Xiongan.DigitalTwin.Data;
using Xiongan.DigitalTwin.Scene;

namespace Xiongan.DigitalTwin.Traffic
{
    /// <summary>World-space evidence for measured speed, queue extent and demand pressure.</summary>
    public sealed class AlgorithmVisualManager : MonoBehaviour
    {
        private sealed class LaneVisual
        {
            public LineRenderer Speed = null!;
            public LineRenderer Queue = null!;
            public Transform Pressure = null!;
            public Material SpeedMaterial = null!;
            public Material QueueMaterial = null!;
            public Material PressureMaterial = null!;
        }

        private readonly Dictionary<string, LaneVisual> visuals = new();
        private SceneBuilder scene = null!;

        public void Initialise(SceneBuilder sceneBuilder)
        {
            scene = sceneBuilder;
        }

        public void SetVisible(bool visible)
        {
            gameObject.SetActive(visible);
        }

        public void Apply(JArray intersectionMetrics)
        {
            var active = new HashSet<string>();
            foreach (var intersection in intersectionMetrics.OfType<JObject>())
            {
                var approaches = intersection["approaches"] as JArray
                    ?? intersection["lane_states"] as JArray;
                if (approaches == null) continue;
                foreach (var approach in approaches.OfType<JObject>())
                {
                    var laneId = approach.Value<string>("lane_id");
                    if (string.IsNullOrWhiteSpace(laneId)
                        || !scene.Lanes.TryGetValue(laneId, out var lane)
                        || lane.Shape.Count < 2)
                        continue;
                    active.Add(laneId);
                    var visual = EnsureVisual(lane);
                    UpdateVisual(visual, lane, approach);
                }
            }
            foreach (var item in visuals)
                SetActive(item.Value, active.Contains(item.Key));
        }

        private LaneVisual EnsureVisual(LaneRecord lane)
        {
            if (visuals.TryGetValue(lane.SumoLaneId, out var existing)) return existing;
            var root = new GameObject($"算法证据-{lane.SumoLaneId}");
            root.transform.SetParent(transform, false);
            var speedMaterial = CreateMaterial(new Color(0.18f, 0.82f, 0.58f, 1f));
            var queueMaterial = CreateMaterial(new Color(1f, 0.67f, 0.12f, 1f));
            var pressureMaterial = CreateMaterial(new Color(1f, 0.24f, 0.12f, 1f));
            var visual = new LaneVisual
            {
                Speed = CreateLine("实时速度", root.transform, speedMaterial, 0.2f),
                Queue = CreateLine("排队范围", root.transform, queueMaterial, Mathf.Max(0.8f, lane.WidthM * 0.7f)),
                Pressure = CreatePressure(root.transform, pressureMaterial),
                SpeedMaterial = speedMaterial,
                QueueMaterial = queueMaterial,
                PressureMaterial = pressureMaterial,
            };
            var points = lane.Shape.Select(point => scene.Coordinates.ToWorld(point, 0.105f)).ToArray();
            SetPoints(visual.Speed, points);
            visuals[lane.SumoLaneId] = visual;
            return visual;
        }

        private void UpdateVisual(LaneVisual visual, LaneRecord lane, JObject approach)
        {
            var speed = Mathf.Max(0f, approach.Value<float?>("mean_speed_m_s") ?? 0f);
            var queueVehicles = Mathf.Max(0f,
                approach.Value<float?>("queue_vehicles")
                ?? approach.Value<float?>("queue_vehicle_count")
                ?? 0f);
            var queueLength = Mathf.Max(0f,
                approach.Value<float?>("queue_length_m") ?? queueVehicles * 7.5f);
            var downstream = Mathf.Clamp01(approach.Value<float?>("downstream_occupancy") ?? 0f);
            var pressure = queueVehicles * Mathf.Max(0.08f, 1f - downstream);

            SetColor(visual.SpeedMaterial, SpeedColor(speed));
            SetColor(visual.QueueMaterial, QueueColor(queueVehicles));
            SetColor(visual.PressureMaterial, PressureColor(pressure));
            var points = lane.Shape.Select(point => scene.Coordinates.ToWorld(point, 0.13f)).ToList();
            SetPoints(visual.Queue, Tail(points, queueLength));
            visual.Queue.enabled = queueLength > 0.25f;

            var height = Mathf.Clamp(pressure * 0.22f, 0.18f, 6f);
            var endpoint = points[^1];
            visual.Pressure.position = endpoint + Vector3.up * (0.14f + height * 0.5f);
            visual.Pressure.localScale = new Vector3(0.34f, height, 0.34f);
            visual.Pressure.gameObject.SetActive(pressure > 0.05f);
        }

        private static LineRenderer CreateLine(string objectName, Transform parent, Material material, float width)
        {
            var child = new GameObject(objectName);
            child.transform.SetParent(parent, false);
            var line = child.AddComponent<LineRenderer>();
            line.useWorldSpace = true;
            line.sharedMaterial = material;
            line.startWidth = width;
            line.endWidth = width;
            line.numCapVertices = 2;
            line.numCornerVertices = 2;
            line.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            line.receiveShadows = false;
            return line;
        }

        private static Transform CreatePressure(Transform parent, Material material)
        {
            var pillar = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
            pillar.name = "进口压力";
            pillar.transform.SetParent(parent, false);
            pillar.GetComponent<Renderer>().sharedMaterial = material;
            Destroy(pillar.GetComponent<Collider>());
            return pillar.transform;
        }

        private static Material CreateMaterial(Color color)
        {
            var shader = Shader.Find("Universal Render Pipeline/Unlit")
                ?? Shader.Find("Sprites/Default")
                ?? Shader.Find("Standard");
            var material = new Material(shader) { enableInstancing = true };
            SetColor(material, color);
            return material;
        }

        private static void SetColor(Material material, Color color)
        {
            if (material.HasProperty("_BaseColor")) material.SetColor("_BaseColor", color);
            if (material.HasProperty("_Color")) material.SetColor("_Color", color);
        }

        private static Color SpeedColor(float speed)
        {
            var ratio = Mathf.Clamp01(speed / 13.9f);
            return ratio < 0.5f
                ? Color.Lerp(new Color(0.92f, 0.18f, 0.12f), new Color(1f, 0.72f, 0.12f), ratio * 2f)
                : Color.Lerp(new Color(1f, 0.72f, 0.12f), new Color(0.12f, 0.85f, 0.56f), (ratio - 0.5f) * 2f);
        }

        private static Color QueueColor(float queueVehicles)
        {
            return Color.Lerp(new Color(1f, 0.76f, 0.16f), new Color(0.96f, 0.2f, 0.1f), Mathf.Clamp01(queueVehicles / 14f));
        }

        private static Color PressureColor(float pressure)
        {
            return Color.Lerp(new Color(0.95f, 0.62f, 0.12f), new Color(1f, 0.08f, 0.04f), Mathf.Clamp01(pressure / 12f));
        }

        private static IReadOnlyList<Vector3> Tail(IReadOnlyList<Vector3> points, float length)
        {
            if (points.Count < 2 || length <= 0f) return new List<Vector3>();
            var output = new List<Vector3> { points[^1] };
            var remaining = length;
            for (var index = points.Count - 1; index > 0 && remaining > 0f; index--)
            {
                var from = points[index];
                var to = points[index - 1];
                var segment = Vector3.Distance(from, to);
                if (segment <= remaining)
                {
                    output.Add(to);
                    remaining -= segment;
                }
                else
                {
                    output.Add(Vector3.Lerp(from, to, remaining / Mathf.Max(0.001f, segment)));
                    remaining = 0f;
                }
            }
            output.Reverse();
            return output;
        }

        private static void SetPoints(LineRenderer line, IReadOnlyList<Vector3> points)
        {
            line.positionCount = points.Count;
            for (var index = 0; index < points.Count; index++) line.SetPosition(index, points[index]);
        }

        private static void SetActive(LaneVisual visual, bool active)
        {
            visual.Speed.gameObject.SetActive(active);
            visual.Queue.gameObject.SetActive(active && visual.Queue.positionCount > 0);
            if (!active) visual.Pressure.gameObject.SetActive(false);
        }

        private void OnDestroy()
        {
            foreach (var visual in visuals.Values)
            {
                Destroy(visual.SpeedMaterial);
                Destroy(visual.QueueMaterial);
                Destroy(visual.PressureMaterial);
            }
        }
    }
}
