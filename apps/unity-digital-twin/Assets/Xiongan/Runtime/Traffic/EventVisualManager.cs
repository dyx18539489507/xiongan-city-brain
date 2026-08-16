using System.Collections.Generic;
using System.Linq;
using Newtonsoft.Json.Linq;
using UnityEngine;
using Xiongan.DigitalTwin.Data;
using Xiongan.DigitalTwin.Entities;
using Xiongan.DigitalTwin.Scene;

namespace Xiongan.DigitalTwin.Traffic
{
    public sealed class EventVisualManager : MonoBehaviour
    {
        private readonly Dictionary<string, GameObject> roadworks = new();
        private readonly Dictionary<string, GameObject> incidents = new();
        private readonly Dictionary<string, GameObject> activities = new();
        private readonly HashSet<string> processed = new();
        private SceneBuilder scene = null!;
        private EntityManager entities = null!;
        private Material coneMaterial = null!;
        private Material barrierMaterial = null!;
        private Material activityMaterial = null!;

        public void Initialise(SceneBuilder sceneBuilder, EntityManager entityManager)
        {
            scene = sceneBuilder;
            entities = entityManager;
            coneMaterial = scene.Materials.Create(new Color(1f, 0.26f, 0.035f), 0.48f, 0.05f);
            barrierMaterial = scene.Materials.Create(new Color(0.94f, 0.86f, 0.68f), 0.28f, 0f);
            activityMaterial = scene.Materials.Create(new Color(1f, 0.61f, 0.06f), 0.62f, 0.04f);
        }

        public void Apply(IEnumerable<RealtimeEvent> incoming)
        {
            foreach (var trafficEvent in incoming)
            {
                if (!processed.Add(trafficEvent.EventId)) continue;
                var key = Key(trafficEvent);
                switch (trafficEvent.Event)
                {
                    case "ROADWORK_LANE_CLOSED":
                        if (!string.IsNullOrWhiteSpace(trafficEvent.Detail)) CreateRoadwork(key, trafficEvent.Detail!);
                        break;
                    case "ROADWORK_LANE_REOPENED":
                        Remove(roadworks, key);
                        break;
                    case "INCIDENT_VEHICLE_STOPPED":
                        if (!string.IsNullOrWhiteSpace(trafficEvent.Detail)) CreateIncident(key, trafficEvent.Detail!);
                        break;
                    case "INCIDENT_CLEARED":
                    case "INCIDENT_STOP_CANCELLED":
                    case "INCIDENT_ALREADY_RELEASED":
                        Remove(incidents, key);
                        break;
                    case "EVENT_DISPERSAL_STARTED":
                        CreateActivity(key, trafficEvent.Detail);
                        break;
                    case "EVENT_DISPERSAL_ENDED":
                        Remove(activities, key);
                        break;
                }
            }
        }

        public void Reset()
        {
            foreach (var item in roadworks.Values) Destroy(item);
            foreach (var item in incidents.Values) Destroy(item);
            foreach (var item in activities.Values) Destroy(item);
            roadworks.Clear();
            incidents.Clear();
            activities.Clear();
            processed.Clear();
        }

        private void CreateRoadwork(string key, string laneId)
        {
            Remove(roadworks, key);
            if (!scene.Lanes.TryGetValue(laneId, out var lane) || lane.Shape.Count < 2) return;
            var root = new GameObject($"施工占道-{laneId}");
            root.transform.SetParent(transform, false);
            var points = lane.Shape.Select(point => scene.Coordinates.ToWorld(point, 0.16f)).ToList();
            var count = Mathf.Clamp(Mathf.CeilToInt(PathLength(points) / 6f), 3, 18);
            for (var index = 0; index < count; index++)
            {
                var position = Sample(points, count == 1 ? 0.5f : index / (float)(count - 1));
                CreatePrimitive(PrimitiveType.Cylinder, "反光锥", root.transform, position, new Vector3(0.26f, 0.65f, 0.26f), coneMaterial);
            }
            var end = points[^1];
            var previous = points[^2];
            var barrier = CreatePrimitive(PrimitiveType.Cube, "施工围挡", root.transform, Vector3.Lerp(previous, end, 0.62f) + Vector3.up * 0.48f, new Vector3(lane.WidthM, 0.85f, 0.22f), barrierMaterial);
            barrier.transform.rotation = Quaternion.LookRotation((end - previous).normalized, Vector3.up) * Quaternion.Euler(0f, 90f, 0f);
            roadworks[key] = root;
        }

        private void CreateIncident(string key, string entityId)
        {
            Remove(incidents, key);
            var target = entities.Find(entityId);
            if (target == null) return;
            var marker = CreatePrimitive(PrimitiveType.Sphere, $"事故-{entityId}", transform, target.transform.position + Vector3.up * 2.8f, Vector3.one * 1.25f, scene.Materials.Alert);
            marker.AddComponent<PulseMarker>().BaseScale = Vector3.one * 1.25f;
            marker.AddComponent<EventMarkerFollower>().Target = target.transform;
            incidents[key] = marker;
        }

        private void CreateActivity(string key, string? detail)
        {
            Remove(activities, key);
            var area = scene.Document.Zones.FirstOrDefault(item => !string.IsNullOrWhiteSpace(detail) && (item.SceneId == detail || detail!.Contains(item.SceneId)))
                       ?? scene.Document.Zones.FirstOrDefault();
            Vector3 center;
            if (area != null && area.Shape.Count > 0)
            {
                center = area.Shape.Select(point => scene.Coordinates.ToWorld(point, 0.08f)).Aggregate(Vector3.zero, (sum, point) => sum + point) / area.Shape.Count;
            }
            else
            {
                var junction = scene.Document.Junctions.FirstOrDefault(item => item.Controlled);
                if (junction == null) return;
                center = scene.Coordinates.ToWorld(junction.Position, 0.08f);
            }
            var root = new GameObject($"大型活动-{key}");
            root.transform.SetParent(transform, false);
            for (var index = 0; index < 24; index++)
            {
                var radians = index / 24f * Mathf.PI * 2f;
                var position = center + new Vector3(Mathf.Cos(radians), 0f, Mathf.Sin(radians)) * 9f;
                CreatePrimitive(PrimitiveType.Cube, "活动边界", root.transform, position, new Vector3(0.7f, 0.18f, 0.18f), activityMaterial).transform.rotation = Quaternion.Euler(0f, -radians * Mathf.Rad2Deg, 0f);
            }
            activities[key] = root;
        }

        private static string Key(RealtimeEvent trafficEvent)
        {
            return trafficEvent.Payload.Value<string>("disturbance_id") ?? trafficEvent.EventId;
        }

        private static void Remove(Dictionary<string, GameObject> source, string key)
        {
            if (!source.Remove(key, out var item)) return;
            Destroy(item);
        }

        private static float PathLength(IReadOnlyList<Vector3> points)
        {
            var length = 0f;
            for (var index = 1; index < points.Count; index++) length += Vector3.Distance(points[index - 1], points[index]);
            return length;
        }

        private static Vector3 Sample(IReadOnlyList<Vector3> points, float ratio)
        {
            var target = PathLength(points) * Mathf.Clamp01(ratio);
            for (var index = 1; index < points.Count; index++)
            {
                var segment = Vector3.Distance(points[index - 1], points[index]);
                if (target <= segment) return Vector3.Lerp(points[index - 1], points[index], target / Mathf.Max(0.001f, segment));
                target -= segment;
            }
            return points[^1];
        }

        private static GameObject CreatePrimitive(PrimitiveType kind, string objectName, Transform parent, Vector3 position, Vector3 scale, Material material)
        {
            var item = GameObject.CreatePrimitive(kind);
            item.name = objectName;
            item.transform.SetParent(parent, true);
            item.transform.position = position;
            item.transform.localScale = scale;
            item.GetComponent<Renderer>().sharedMaterial = material;
            Destroy(item.GetComponent<Collider>());
            return item;
        }
    }
}
