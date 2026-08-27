using System;
using System.Collections.Generic;
using UnityEngine;
using Xiongan.DigitalTwin.Core;
using Xiongan.DigitalTwin.Data;
using Xiongan.DigitalTwin.Interaction;
using Xiongan.DigitalTwin.Scene;

namespace Xiongan.DigitalTwin.Entities
{
    public sealed class EntityManager : MonoBehaviour
    {
        private readonly Dictionary<string, EntityActor> vehicles = new();
        private readonly Dictionary<string, EntityActor> bicycles = new();
        private readonly Dictionary<string, EntityActor> pedestrians = new();
        private readonly Stack<EntityActor> vehiclePool = new();
        private readonly Stack<EntityActor> bicyclePool = new();
        private readonly Stack<EntityActor> pedestrianPool = new();
        private readonly List<VehicleClusterMarker> vehicleLocatorMarkers = new();
        private CoordinateService coordinates = null!;
        private MaterialLibrary materials = null!;
        private EntityRoadProjector? roadProjector;
        private UnityEngine.Camera? viewCamera;
        private float tickHz = 1f;
        private bool vehicleLocatorsVisible;
        private int nextVehicleLocatorFrame;

        public int VehicleCount => vehicles.Count;
        public int BicycleCount => bicycles.Count;
        public int PedestrianCount => pedestrians.Count;

        public void Initialise(CoordinateService coordinateService, MaterialLibrary materialLibrary)
        {
            coordinates = coordinateService;
            materials = materialLibrary;
            roadProjector = null;
        }

        public void Initialise(SceneBuilder scene)
        {
            coordinates = scene.Coordinates;
            materials = scene.Materials;
            roadProjector = new EntityRoadProjector(scene);
        }

        private void Update()
        {
            if (viewCamera == null) viewCamera = UnityEngine.Camera.main;
            var hasCamera = viewCamera != null;
            var cameraPosition = hasCamera ? viewCamera!.transform.position : Vector3.zero;
            var deltaTime = Time.deltaTime;
            var frameCount = Time.frameCount;
            TickActors(vehicles, deltaTime, frameCount, cameraPosition, hasCamera);
            TickActors(bicycles, deltaTime, frameCount, cameraPosition, hasCamera);
            TickActors(pedestrians, deltaTime, frameCount, cameraPosition, hasCamera);
            if (vehicleLocatorsVisible && hasCamera && frameCount >= nextVehicleLocatorFrame)
            {
                UpdateVehicleLocatorMarkers(viewCamera!, cameraPosition);
                nextVehicleLocatorFrame = frameCount + 12;
            }
        }

        private static void TickActors(
            Dictionary<string, EntityActor> actors,
            float deltaTime,
            int frameCount,
            Vector3 cameraPosition,
            bool hasCamera)
        {
            foreach (var actor in actors.Values)
                actor.Tick(deltaTime, frameCount, cameraPosition, hasCamera);
        }

        public void ApplyInit(DigitalTwinInit message)
        {
            ClearAll();
            tickHz = message.TickHz;
            foreach (var item in message.Entities.Vehicles) SpawnVehicle(item, "vehicle", true);
            foreach (var item in message.Entities.Bicycles) SpawnVehicle(item, "bicycle", true);
            foreach (var item in message.Entities.Pedestrians) SpawnPedestrian(item, true);
        }

        public void ApplyDelta(DigitalTwinDelta message)
        {
            foreach (var id in message.Remove.Vehicles) Recycle(vehicles, vehiclePool, id);
            foreach (var id in message.Remove.Bicycles) Recycle(bicycles, bicyclePool, id);
            foreach (var id in message.Remove.Pedestrians) Recycle(pedestrians, pedestrianPool, id);
            foreach (var item in message.Spawn.Vehicles) SpawnVehicle(item, "vehicle", true);
            foreach (var item in message.Spawn.Bicycles) SpawnVehicle(item, "bicycle", true);
            foreach (var item in message.Spawn.Pedestrians) SpawnPedestrian(item, true);
            foreach (var item in message.Update.Vehicles) UpdateVehicle(item, vehicles);
            foreach (var item in message.Update.Bicycles) UpdateVehicle(item, bicycles);
            foreach (var item in message.Update.Pedestrians) UpdatePedestrian(item);
        }

        public void ApplySnapshot(BrowserSnapshot snapshot)
        {
            tickHz = snapshot.TickHz;
            SyncSnapshot(snapshot.Entities.Vehicles, vehicles, vehiclePool, "vehicle");
            SyncSnapshot(snapshot.Entities.Bicycles, bicycles, bicyclePool, "bicycle");
            var pedestrianIds = new HashSet<string>();
            foreach (var item in snapshot.Entities.Pedestrians)
            {
                pedestrianIds.Add(item.Id);
                if (!pedestrians.ContainsKey(item.Id)) SpawnPedestrian(item, true);
                else UpdatePedestrian(item);
            }
            foreach (var id in new List<string>(pedestrians.Keys)) if (!pedestrianIds.Contains(id)) Recycle(pedestrians, pedestrianPool, id);
        }

        public EntityActor? Find(string identifier)
        {
            if (vehicles.TryGetValue(identifier, out var vehicle)) return vehicle;
            if (bicycles.TryGetValue(identifier, out var bicycle)) return bicycle;
            return pedestrians.TryGetValue(identifier, out var pedestrian) ? pedestrian : null;
        }

        public bool TryGetVehicleClusterCenter(out Vector3 center)
        {
            return TryGetVehicleClusterCenter(out center, out _, out _);
        }

        public bool TryGetVehicleClusterCenter(
            out Vector3 center,
            out int vehicleCount,
            out string representativeId)
        {
            center = Vector3.zero;
            vehicleCount = 0;
            representativeId = string.Empty;
            if (vehicles.Count == 0) return false;
            const float clusterRadius = 78f;
            var radiusSquared = clusterRadius * clusterRadius;
            var bestCount = 0;
            foreach (var candidate in vehicles.Values)
            {
                var sum = Vector3.zero;
                var count = 0;
                foreach (var actor in vehicles.Values)
                {
                    var delta = actor.transform.position - candidate.transform.position;
                    delta.y = 0f;
                    if (delta.sqrMagnitude > radiusSquared) continue;
                    sum += actor.transform.position;
                    count++;
                }
                if (count <= bestCount) continue;
                bestCount = count;
                center = sum / count;
                representativeId = candidate.Identifier;
            }
            vehicleCount = bestCount;
            return vehicleCount > 0;
        }

        public bool TryGetNearestVehicle(Vector3 point, out EntityActor actor)
        {
            actor = null!;
            var bestDistanceSquared = float.MaxValue;
            foreach (var candidate in vehicles.Values)
            {
                var offset = Vector3.ProjectOnPlane(candidate.transform.position - point, Vector3.up);
                if (offset.sqrMagnitude >= bestDistanceSquared) continue;
                bestDistanceSquared = offset.sqrMagnitude;
                actor = candidate;
            }
            return actor != null;
        }

        public bool TryGetVehicleByOffset(string currentId, int offset, out EntityActor actor)
        {
            actor = null!;
            if (vehicles.Count == 0) return false;
            var ids = new List<string>(vehicles.Keys);
            ids.Sort(StringComparer.Ordinal);
            var currentIndex = ids.IndexOf(currentId);
            if (currentIndex < 0) currentIndex = offset < 0 ? 0 : -1;
            var nextIndex = (currentIndex + offset) % ids.Count;
            if (nextIndex < 0) nextIndex += ids.Count;
            actor = vehicles[ids[nextIndex]];
            return true;
        }

        public void SetVehicleLocatorsVisible(bool visible)
        {
            vehicleLocatorsVisible = visible;
            nextVehicleLocatorFrame = 0;
            if (visible) return;
            foreach (var marker in vehicleLocatorMarkers) marker.Root.SetActive(false);
        }

        public void ResetRuntime()
        {
            vehicleLocatorsVisible = false;
            nextVehicleLocatorFrame = 0;
            ClearAll();
        }

        private void SyncSnapshot(IEnumerable<VehicleEntity> source, Dictionary<string, EntityActor> target, Stack<EntityActor> pool, string category)
        {
            var ids = new HashSet<string>();
            foreach (var item in source)
            {
                ids.Add(item.Id);
                if (!target.ContainsKey(item.Id)) SpawnVehicle(item, category, true);
                else UpdateVehicle(item, target);
            }
            foreach (var id in new List<string>(target.Keys)) if (!ids.Contains(id)) Recycle(target, pool, id);
        }

        private void SpawnVehicle(VehicleEntity item, string category, bool immediate)
        {
            var target = category == "bicycle" ? bicycles : vehicles;
            var pool = category == "bicycle" ? bicyclePool : vehiclePool;
            if (target.TryGetValue(item.Id, out var existing))
            {
                SetVehicleTarget(existing, item, category, immediate);
                existing.SetBrake(item.Brake);
                return;
            }
            var actor = pool.Count > 0 ? pool.Pop() : CreateActor(item.Id, category, ResolveColor(item), materials);
            actor.Rebind(item.Id);
            actor.gameObject.SetActive(true);
            SetVehicleTarget(actor, item, category, immediate);
            actor.SetBrake(item.Brake);
            target[item.Id] = actor;
        }

        private void SpawnPedestrian(PedestrianEntity item, bool immediate)
        {
            if (pedestrians.TryGetValue(item.Id, out var existing))
            {
                SetPedestrianTarget(existing, item, immediate);
                return;
            }
            var actor = pedestrianPool.Count > 0 ? pedestrianPool.Pop() : CreateActor(item.Id, "pedestrian", DeterministicColor(item.Id), materials);
            actor.Rebind(item.Id);
            actor.gameObject.SetActive(true);
            SetPedestrianTarget(actor, item, immediate);
            pedestrians[item.Id] = actor;
        }

        private void UpdateVehicle(VehicleEntity item, Dictionary<string, EntityActor> target)
        {
            if (!target.TryGetValue(item.Id, out var actor))
            {
                SpawnVehicle(item, ReferenceEquals(target, bicycles) ? "bicycle" : "vehicle", true);
                return;
            }
            SetVehicleTarget(actor, item, ReferenceEquals(target, bicycles) ? "bicycle" : "vehicle", false);
            actor.SetBrake(item.Brake);
        }

        private void UpdatePedestrian(PedestrianEntity item)
        {
            if (!pedestrians.TryGetValue(item.Id, out var actor))
            {
                SpawnPedestrian(item, true);
                return;
            }
            SetPedestrianTarget(actor, item, false);
        }

        private void SetVehicleTarget(
            EntityActor actor,
            VehicleEntity item,
            string category,
            bool immediate)
        {
            if (roadProjector == null)
            {
                actor.SetTarget(item.X, item.Y, item.Angle, item.Speed, tickHz, coordinates, immediate);
                return;
            }
            roadProjector.Resolve(
                item.X, item.Y, item.Angle, item.LaneId, category,
                out var position, out var rotation);
            actor.SetTarget(position, rotation, item.Speed, tickHz, immediate);
        }

        private void SetPedestrianTarget(
            EntityActor actor,
            PedestrianEntity item,
            bool immediate)
        {
            if (roadProjector == null)
            {
                actor.SetTarget(item.X, item.Y, item.Angle, item.Speed, tickHz, coordinates, immediate);
                return;
            }
            roadProjector.Resolve(
                item.X, item.Y, item.Angle, item.LaneId, "pedestrian",
                out var position, out var rotation);
            actor.SetTarget(position, rotation, item.Speed, tickHz, immediate);
        }

        private EntityActor CreateActor(string id, string category, Color color, MaterialLibrary library)
        {
            var actor = new GameObject().AddComponent<EntityActor>();
            actor.transform.SetParent(transform, false);
            actor.Initialise(id, category, library, color);
            return actor;
        }

        private static Color ResolveColor(VehicleEntity entity)
        {
            if (!ColorUtility.TryParseHtmlString(entity.Color, out var parsed)) return DeterministicColor(entity.Id);
            // The organiser replay uses bright yellow as a connected-vehicle
            // category code. Preserve that semantic in data, but do not render
            // every vehicle as though it had identical yellow body paint.
            Color.RGBToHSV(parsed, out var hue, out var saturation, out var value);
            var categoryYellow = hue >= 0.105f && hue <= 0.19f && saturation > 0.72f && value > 0.82f;
            return categoryYellow ? DeterministicColor(entity.Id) : parsed;
        }

        private static Color DeterministicColor(string id)
        {
            var palette = new[]
            {
                new Color(0.92f, 0.94f, 0.95f), new Color(0.075f, 0.09f, 0.105f),
                new Color(0.68f, 0.7f, 0.72f), new Color(0.10f, 0.30f, 0.56f),
                new Color(0.62f, 0.055f, 0.045f), new Color(0.22f, 0.34f, 0.31f),
                new Color(0.82f, 0.82f, 0.78f), new Color(0.28f, 0.20f, 0.16f),
            };
            unchecked
            {
                var hash = 17;
                foreach (var character in id) hash = hash * 31 + character;
                return palette[Mathf.Abs(hash) % palette.Length];
            }
        }

        private static void Recycle(Dictionary<string, EntityActor> source, Stack<EntityActor> pool, string id)
        {
            if (!source.Remove(id, out var actor)) return;
            actor.gameObject.SetActive(false);
            pool.Push(actor);
        }

        private void ClearAll()
        {
            foreach (var id in new List<string>(vehicles.Keys)) Recycle(vehicles, vehiclePool, id);
            foreach (var id in new List<string>(bicycles.Keys)) Recycle(bicycles, bicyclePool, id);
            foreach (var id in new List<string>(pedestrians.Keys)) Recycle(pedestrians, pedestrianPool, id);
            foreach (var marker in vehicleLocatorMarkers) marker.Root.SetActive(false);
        }

        private void UpdateVehicleLocatorMarkers(UnityEngine.Camera camera, Vector3 cameraPosition)
        {
            const float cellSize = 110f;
            var clusters = new Dictionary<(int X, int Z), VehicleCluster>();
            foreach (var actor in vehicles.Values)
            {
                var position = actor.transform.position;
                var key = (Mathf.FloorToInt(position.x / cellSize), Mathf.FloorToInt(position.z / cellSize));
                if (!clusters.TryGetValue(key, out var cluster))
                {
                    cluster = new VehicleCluster { RepresentativeId = actor.Identifier };
                    clusters[key] = cluster;
                }
                cluster.PositionSum += position;
                cluster.Count++;
            }

            var markerIndex = 0;
            foreach (var cluster in clusters.Values)
            {
                var center = cluster.PositionSum / Mathf.Max(1, cluster.Count);
                var distance = Vector3.Distance(cameraPosition, center);
                if (distance < 180f) continue;
                while (vehicleLocatorMarkers.Count <= markerIndex)
                    vehicleLocatorMarkers.Add(CreateVehicleClusterMarker());
                var marker = vehicleLocatorMarkers[markerIndex++];
                var scale = Mathf.Clamp(distance * 0.008f, 1.2f, 16f);
                marker.Root.SetActive(true);
                marker.Root.transform.position = center + Vector3.up * (4.5f + scale * 0.32f);
                marker.Root.transform.localScale = Vector3.one * scale;
                marker.Label.text = cluster.Count.ToString();
                marker.Label.transform.rotation = camera.transform.rotation;
                marker.Selectable.Identifier = cluster.RepresentativeId;
            }
            for (; markerIndex < vehicleLocatorMarkers.Count; markerIndex++)
                vehicleLocatorMarkers[markerIndex].Root.SetActive(false);
        }

        private VehicleClusterMarker CreateVehicleClusterMarker()
        {
            var root = new GameObject("远景车辆聚合标记");
            root.transform.SetParent(transform, false);
            var selectable = root.AddComponent<SelectableObject>();
            selectable.Kind = "vehicle_cluster";
            selectable.Provenance = "SUMO/TraCI vehicle cluster";

            var beacon = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            beacon.name = "车辆定位信标";
            beacon.transform.SetParent(root.transform, false);
            beacon.transform.localScale = new Vector3(0.8f, 0.8f, 0.8f);
            var beaconRenderer = beacon.GetComponent<Renderer>();
            beaconRenderer.sharedMaterial = materials.SignalYellow;
            beaconRenderer.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            beaconRenderer.receiveShadows = false;

            var stem = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
            stem.name = "车辆定位引线";
            stem.transform.SetParent(root.transform, false);
            stem.transform.localPosition = Vector3.down * 1.35f;
            stem.transform.localScale = new Vector3(0.09f, 1.25f, 0.09f);
            var stemCollider = stem.GetComponent<Collider>();
            if (stemCollider != null) Destroy(stemCollider);
            var stemRenderer = stem.GetComponent<Renderer>();
            stemRenderer.sharedMaterial = materials.Headlight;
            stemRenderer.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            stemRenderer.receiveShadows = false;

            var labelObject = new GameObject("车辆聚合数量");
            labelObject.transform.SetParent(root.transform, false);
            labelObject.transform.localPosition = Vector3.up * 1.05f;
            var label = labelObject.AddComponent<TextMesh>();
            label.anchor = TextAnchor.MiddleCenter;
            label.alignment = TextAlignment.Center;
            label.characterSize = 0.12f;
            label.fontSize = 48;
            label.color = Color.white;
            var labelRenderer = label.GetComponent<MeshRenderer>();
            labelRenderer.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            labelRenderer.receiveShadows = false;
            root.SetActive(false);
            return new VehicleClusterMarker(root, label, selectable);
        }

        private sealed class VehicleCluster
        {
            public Vector3 PositionSum;
            public int Count;
            public string RepresentativeId = string.Empty;
        }

        private sealed class VehicleClusterMarker
        {
            public GameObject Root { get; }
            public TextMesh Label { get; }
            public SelectableObject Selectable { get; }

            public VehicleClusterMarker(GameObject root, TextMesh label, SelectableObject selectable)
            {
                Root = root;
                Label = label;
                Selectable = selectable;
            }
        }
    }

    public sealed class EntityRoadProjector
    {
        private sealed class LanePath
        {
            public Vector3[] Points = System.Array.Empty<Vector3>();
            public float HalfWidth;
            public bool IntersectsShowcase;
        }

        private readonly CoordinateService coordinates;
        private readonly ReferenceShowcaseFrame showcaseFrame;
        private readonly bool hasShowcase;
        private readonly Dictionary<string, LanePath> lanes = new();

        public EntityRoadProjector(SceneBuilder scene)
        {
            coordinates = scene.Coordinates;
            hasShowcase = scene.Junctions.ContainsKey(ReferenceShowcaseLayout.JunctionId);
            showcaseFrame = hasShowcase ? ReferenceShowcaseLayout.Resolve(scene) : default;
            foreach (var lane in scene.Document.Lanes)
            {
                if (lane.Shape.Count < 2) continue;
                var points = new Vector3[lane.Shape.Count];
                for (var index = 0; index < lane.Shape.Count; index++)
                    points[index] = coordinates.ToWorld(lane.Shape[index]);
                lanes[lane.SumoLaneId] = new LanePath
                {
                    Points = points,
                    HalfWidth = Mathf.Max(0.7f, lane.WidthM * 0.5f),
                    IntersectsShowcase = hasShowcase && ReferenceShowcaseLayout.IntersectsRoadSurfaceOverride(
                        showcaseFrame, points, lane.WidthM * 0.5f),
                };
            }
        }

        public void Resolve(
            float x,
            float y,
            float angle,
            string laneId,
            string category,
            out Vector3 position,
            out Quaternion rotation)
        {
            var baseHeight = category switch
            {
                "pedestrian" => 0.105f,
                "bicycle" => 0.055f,
                _ => 0.04f,
            };
            position = coordinates.ToWorld(x, y, baseHeight);
            rotation = coordinates.ToWorldRotation(angle);
            if (string.IsNullOrWhiteSpace(laneId) || !lanes.TryGetValue(laneId, out var lane)) return;

            ResolveClosestPoint(lane.Points, position, out var closest, out var tangent);
            var offset = Vector3.ProjectOnPlane(position - closest, Vector3.up);
            var bodyHalfWidth = category switch
            {
                "pedestrian" => 0.24f,
                "bicycle" => 0.38f,
                _ => 0.96f,
            };
            var allowedOffset = Mathf.Max(0.22f, lane.HalfWidth - bodyHalfWidth);
            if (offset.sqrMagnitude > allowedOffset * allowedOffset)
            {
                var corrected = offset.sqrMagnitude < 0.0001f
                    ? closest
                    : closest + offset.normalized * allowedOffset;
                position.x = corrected.x;
                position.z = corrected.z;
            }

            if (!hasShowcase || !lane.IntersectsShowcase ||
                !ReferenceShowcaseLayout.CoversRoadSurfaceOverride(showcaseFrame, position, 8f))
                return;

            ProjectToShowcaseCarriageway(category, tangent, ref position, ref rotation);
        }

        private void ProjectToShowcaseCarriageway(
            string category,
            Vector3 sourceTangent,
            ref Vector3 position,
            ref Quaternion rotation)
        {
            var local = ReferenceShowcaseLayout.ToLocal(showcaseFrame, position);
            var across = local.x;
            var along = local.y;
            var insideOpenJunction = Mathf.Abs(across) <= 33.5f && Mathf.Abs(along) <= 33.5f;
            var displayHeight = category == "pedestrian" ? 0.125f :
                category == "bicycle" ? 0.12f : 0.11f;
            if (insideOpenJunction)
            {
                position.y = displayHeight;
                return;
            }

            sourceTangent = Vector3.ProjectOnPlane(sourceTangent, Vector3.up).normalized;
            var followsMainRoad = Mathf.Abs(Vector3.Dot(sourceTangent, showcaseFrame.Forward)) >=
                                  Mathf.Abs(Vector3.Dot(sourceTangent, showcaseFrame.Right));
            Vector3 displayForward;
            if (followsMainRoad)
            {
                var side = Mathf.Abs(across) > 2.8f
                    ? Mathf.Sign(across)
                    : Vector3.Dot(sourceTangent, showcaseFrame.Forward) >= 0f ? 1f : -1f;
                across = side * ResolveLaneCenter(Mathf.Abs(across));
                position = showcaseFrame.Point(across, displayHeight, along);
                displayForward = Vector3.Dot(sourceTangent, showcaseFrame.Forward) >= 0f
                    ? showcaseFrame.Forward
                    : -showcaseFrame.Forward;
            }
            else
            {
                var side = Mathf.Abs(along) > 2.8f
                    ? Mathf.Sign(along)
                    : Vector3.Dot(sourceTangent, showcaseFrame.Right) >= 0f ? -1f : 1f;
                along = side * ResolveLaneCenter(Mathf.Abs(along));
                position = showcaseFrame.Point(across, displayHeight, along);
                displayForward = Vector3.Dot(sourceTangent, showcaseFrame.Right) >= 0f
                    ? showcaseFrame.Right
                    : -showcaseFrame.Right;
            }
            rotation = Quaternion.LookRotation(displayForward, Vector3.up);
        }

        private static float ResolveLaneCenter(float sourceOffset)
        {
            var centers = new[] { 5.7f, 11.5f, 17.3f, 23.1f };
            var best = centers[0];
            var bestDistance = Mathf.Abs(sourceOffset - best);
            for (var index = 1; index < centers.Length; index++)
            {
                var distance = Mathf.Abs(sourceOffset - centers[index]);
                if (distance >= bestDistance) continue;
                best = centers[index];
                bestDistance = distance;
            }
            return best;
        }

        private static void ResolveClosestPoint(
            IReadOnlyList<Vector3> points,
            Vector3 position,
            out Vector3 closest,
            out Vector3 tangent)
        {
            closest = points[0];
            tangent = Vector3.forward;
            var bestDistanceSquared = float.MaxValue;
            for (var index = 0; index < points.Count - 1; index++)
            {
                var from = points[index];
                var segment = Vector3.ProjectOnPlane(points[index + 1] - from, Vector3.up);
                var lengthSquared = segment.sqrMagnitude;
                if (lengthSquared < 0.0001f) continue;
                var offset = Vector3.ProjectOnPlane(position - from, Vector3.up);
                var progress = Mathf.Clamp01(Vector3.Dot(offset, segment) / lengthSquared);
                var candidate = from + segment * progress;
                var distanceSquared = Vector3.ProjectOnPlane(position - candidate, Vector3.up).sqrMagnitude;
                if (distanceSquared >= bestDistanceSquared) continue;
                bestDistanceSquared = distanceSquared;
                closest = candidate;
                tangent = segment.normalized;
            }
        }
    }
}
