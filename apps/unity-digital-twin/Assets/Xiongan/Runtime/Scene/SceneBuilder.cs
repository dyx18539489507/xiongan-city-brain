using System.Collections;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;
using Xiongan.DigitalTwin.Core;
using Xiongan.DigitalTwin.Data;

namespace Xiongan.DigitalTwin.Scene
{
    public sealed class SceneBuilder : MonoBehaviour
    {
        private const string ShowcaseVisualAnchorJunctionId = "cluster_11122023464_11122023574";

        [SerializeField] private SceneDocument document = new();
        [SerializeField] private int bakedBuildingCount;

        public SceneDocument Document => document;
        public int BakedBuildingCount => bakedBuildingCount;
        public CoordinateService Coordinates { get; private set; } = null!;
        public MaterialLibrary Materials { get; private set; } = null!;
        public IReadOnlyDictionary<string, LaneRecord> Lanes => lanes;
        public IReadOnlyDictionary<string, JunctionRecord> Junctions => junctions;

        private readonly Dictionary<string, LaneRecord> lanes = new();
        private readonly Dictionary<string, JunctionRecord> junctions = new();

        public IEnumerator Build(SceneDocument source, System.Action<float, string> onProgress)
        {
            document = source;
            bakedBuildingCount = document.Buildings.Count;
            Coordinates = new CoordinateService(document.CoordinateSystem.WorldOriginSumo);
            Materials = new MaterialLibrary();
            foreach (var lane in document.Lanes) lanes[lane.SumoLaneId] = lane;
            foreach (var junction in document.Junctions) junctions[junction.SumoJunctionId] = junction;

            CreateGround();
            var asphalt = new MeshAccumulator();
            var bicycle = new MeshAccumulator();
            var sidewalk = new MeshAccumulator();
            var curb = new MeshAccumulator();
            var verge = new MeshAccumulator();
            var marking = new MeshAccumulator();
            var yellowMarking = new MeshAccumulator();
            var junctionMesh = new MeshAccumulator();
            var crossingMesh = new MeshAccumulator();
            var heroJunction = document.Junctions.First(item => item.SumoJunctionId == ShowcaseVisualAnchorJunctionId);
            var heroCenter = Coordinates.ToWorld(heroJunction.Position);

            for (var index = 0; index < document.Lanes.Count; index++)
            {
                var lane = document.Lanes[index];
                var points = lane.Shape.Select(point => Coordinates.ToWorld(point)).ToList();
                var overlapsHeroInterior = lane.EdgeFunction == "internal" &&
                                           points.Any(point => Vector3.Distance(point, heroCenter) < 24f);
                if (overlapsHeroInterior && lane.LaneKind is "bicycle" or "pedestrian") continue;
                if (lane.LaneKind == "bicycle") bicycle.AddRibbon(points, lane.WidthM, 0.035f, 5f);
                else if (lane.LaneKind == "pedestrian") sidewalk.AddRibbon(points, lane.WidthM, 0.085f, 3.2f);
                else
                {
                    asphalt.AddRibbon(points, lane.WidthM, lane.EdgeFunction == "internal" ? 0.022f : 0.02f, 8f);
                }
                if (index % 500 == 0)
                {
                    onProgress(Mathf.Lerp(0.4f, 0.66f, index / (float)document.Lanes.Count), $"生成车道 {index}/{document.Lanes.Count}");
                    yield return null;
                }
            }

            foreach (var edge in document.Lanes
                         .Where(item => item.EdgeFunction != "internal" &&
                                        item.Shape.Count >= 2 &&
                                        item.LaneKind is not "pedestrian_crossing" and not "pedestrian_area")
                         .GroupBy(item => item.SumoEdgeId))
            {
                var ordered = edge.OrderBy(item => LaneIndex(item.SumoLaneId)).ToList();
                AddRoadEdgeDetails(ordered[0], -1f, curb, verge, yellowMarking);
                if (ordered.Count > 1) AddRoadEdgeDetails(ordered[^1], 1f, curb, verge, yellowMarking);
                var driveable = ordered.Where(IsDriveable).ToList();
                for (var laneIndex = 0; laneIndex < driveable.Count - 1; laneIndex++)
                {
                    var lane = driveable[laneIndex];
                    var points = lane.Shape.Select(point => Coordinates.ToWorld(point)).ToList();
                    AddDashedMarking(marking, Offset(points, lane.WidthM * 0.5f - 0.055f));
                }
            }

            foreach (var junction in document.Junctions)
            {
                if (junction.Shape.Count >= 3)
                    junctionMesh.AddPolygon(junction.Shape.Select(point => Coordinates.ToWorld(point)).ToList(), 0.028f);
            }
            CreateHeroJunctionSurface();
            foreach (var crossing in document.Crossings.Where(item => item.JunctionId != ShowcaseVisualAnchorJunctionId))
                AddCrosswalk(crossingMesh, crossing);
            AddHeroCrosswalks(crossingMesh, heroCenter);

            var approachConnections = document.Connections
                .Where(item => item.Direction is "s" or "l" or "r")
                .Where(item => lanes.TryGetValue(item.FromLaneId, out var lane) &&
                               lane.EdgeFunction != "internal" && IsDriveable(lane) && lane.Shape.Count >= 2)
                .GroupBy(item => item.FromLaneId);
            foreach (var approach in approachConnections)
            {
                var lane = lanes[approach.Key];
                var points = lane.Shape.Select(point => Coordinates.ToWorld(point)).ToList();
                if (!TryPointBeforeEnd(points, 16.5f, out var arrowPosition, out var forward)) continue;
                var directions = NormaliseDirections(approach
                    .Select(item => item.Direction)
                    .Distinct()
                    .OrderBy(DirectionOrder));
                if (directions.Length == 0) continue;
                marking.AddArrow(arrowPosition, forward, directions, 0.065f);
            }

            foreach (var approach in document.Connections
                         .Where(item => !string.IsNullOrWhiteSpace(item.TlsId))
                         .Where(item => lanes.TryGetValue(item.FromLaneId, out var lane) &&
                                        lane.EdgeFunction != "internal" && IsDriveable(lane) && lane.Shape.Count >= 2)
                         .GroupBy(item => item.FromLaneId))
            {
                var lane = lanes[approach.Key];
                var end = Coordinates.ToWorld(lane.Shape[^1]);
                var previous = Coordinates.ToWorld(lane.Shape[^2]);
                var forward = (end - previous).normalized;
                var side = Vector3.Cross(Vector3.up, forward);
                marking.AddRibbon(new[] { end - side * lane.WidthM * 0.44f, end + side * lane.WidthM * 0.44f }, 0.42f, 0.071f, 1f);
            }

            asphalt.Build("SUMO道路面", Materials.Asphalt, transform);
            bicycle.Build("非机动车道", Materials.Bicycle, transform, false);
            sidewalk.Build("人行设施", Materials.Sidewalk, transform, false);
            curb.Build("花岗岩路缘石", Materials.Curb, transform);
            verge.Build("道路侧分绿化带", Materials.Grass, transform, false);
            junctionMesh.Build("路口铺装", Materials.Junction, transform);
            crossingMesh.Build("斑马线", Materials.Marking, transform, false);
            marking.Build("车道线停止线与导向箭头", Materials.Marking, transform, false);
            yellowMarking.Build("道路边缘黄色标线", Materials.MarkingYellow, transform, false);

            onProgress(0.72f, "照片级道路与路口构造已生成");
            yield return null;
        }

        public void RestoreBaked()
        {
            Coordinates = new CoordinateService(document.CoordinateSystem.WorldOriginSumo);
            Materials = new MaterialLibrary();
            lanes.Clear();
            junctions.Clear();
            foreach (var lane in document.Lanes) lanes[lane.SumoLaneId] = lane;
            foreach (var junction in document.Junctions) junctions[junction.SumoJunctionId] = junction;
        }

        public void CompactForRuntime()
        {
            document.Connections.Clear();
            document.Crossings.Clear();
            document.PedestrianAreas.Clear();
            document.BicycleAreas.Clear();
            document.Buildings.Clear();
            document.Vegetation.Clear();
            document.RoadsideDevices.Clear();
        }

        public void ReleaseBakedMaterialOwnership() => Materials.ReleaseOwnership();

        public void RegisterGeneratedBuildings(int count)
        {
            bakedBuildingCount += Mathf.Max(0, count);
        }

        private void CreateGround()
        {
            var ground = new MeshAccumulator();
            ground.AddPolygon(new[]
            {
                new Vector3(-3600f, 0f, -3600f), new Vector3(3600f, 0f, -3600f),
                new Vector3(3600f, 0f, 3600f), new Vector3(-3600f, 0f, 3600f),
            }, -0.045f);
            ground.Build("雄安城市基底绿地", Materials.UrbanGround, transform, false);
        }

        private void CreateHeroJunctionSurface()
        {
            if (!junctions.TryGetValue(ShowcaseVisualAnchorJunctionId, out var junction)) return;
            var surface = new MeshAccumulator();
            var shape = junction.Shape.Select(point => Coordinates.ToWorld(point)).ToList();
            if (shape.Count < 3) return;
            const float apron = 1.25f;
            var minX = shape.Min(point => point.x) - apron;
            var maxX = shape.Max(point => point.x) + apron;
            var minZ = shape.Min(point => point.z) - apron;
            var maxZ = shape.Max(point => point.z) + apron;
            surface.AddPolygon(new[]
            {
                new Vector3(minX, 0f, minZ), new Vector3(maxX, 0f, minZ),
                new Vector3(maxX, 0f, maxZ), new Vector3(minX, 0f, maxZ),
            }, 0.031f);
            surface.Build("K08 连续沥青路口铺装", Materials.Asphalt, transform);
        }

        private static bool IsDriveable(LaneRecord lane)
        {
            return lane.LaneKind is "motor" or "mixed";
        }

        private static void AddDashedMarking(MeshAccumulator accumulator, IReadOnlyList<Vector3> points)
        {
            if (points.Count < 2) return;
            for (var index = 0; index < points.Count - 1; index++)
            {
                var from = points[index];
                var to = points[index + 1];
                var direction = to - from;
                direction.y = 0f;
                var length = direction.magnitude;
                if (length < 0.25f) continue;
                direction.Normalize();
                const float cycle = 8.5f;
                const float dash = 4.8f;
                for (var start = 1.2f; start < length; start += cycle)
                {
                    var end = Mathf.Min(start + dash, length);
                    accumulator.AddRibbon(new[] { from + direction * start, from + direction * end }, 0.11f, 0.062f, 1f);
                }
            }
        }

        private void AddRoadEdgeDetails(LaneRecord lane, float sign, MeshAccumulator curb, MeshAccumulator verge, MeshAccumulator yellow)
        {
            var points = lane.Shape.Select(point => Coordinates.ToWorld(point)).ToList();
            curb.AddExtrudedRibbon(Offset(points, sign * (lane.WidthM * 0.5f + 0.16f)), 0.32f, 0.025f, 0.16f);
            verge.AddRibbon(Offset(points, sign * (lane.WidthM * 0.5f + 1.55f)), 2.45f, 0.075f, 5f);
            yellow.AddRibbon(Offset(points, sign * (lane.WidthM * 0.5f - 0.12f)), 0.1f, 0.067f, 1f);
        }

        private static List<Vector3> Offset(IReadOnlyList<Vector3> points, float amount)
        {
            var result = new List<Vector3>(points.Count);
            for (var index = 0; index < points.Count; index++)
            {
                var direction = index == points.Count - 1 ? points[index] - points[index - 1] : points[index + 1] - points[index];
                direction.y = 0f;
                if (direction.sqrMagnitude < 0.001f) direction = Vector3.forward;
                result.Add(points[index] + Vector3.Cross(Vector3.up, direction.normalized) * amount);
            }
            return result;
        }

        private static int LaneIndex(string id)
        {
            var split = id.LastIndexOf('_');
            return split >= 0 && int.TryParse(id[(split + 1)..], out var index) ? index : 0;
        }

        private static int DirectionOrder(string direction)
        {
            return direction switch
            {
                "l" => 0,
                "s" => 1,
                "r" => 2,
                _ => 3,
            };
        }

        private static string NormaliseDirections(IEnumerable<string> source)
        {
            var directions = new string(source
                .SelectMany(value => value.ToLowerInvariant())
                .Where(value => value is 'l' or 's' or 'r')
                .Distinct()
                .OrderBy(value => DirectionOrder(value.ToString()))
                .ToArray());
            // A three-headed symbol reads as a paint error at web resolution. Keep the dominant
            // through movement while SUMO continues to retain all legal connection movements.
            return directions.Length == 3 ? "s" : directions;
        }

        private static bool TryPointBeforeEnd(
            IReadOnlyList<Vector3> points, float distanceFromEnd, out Vector3 position, out Vector3 forward)
        {
            position = Vector3.zero;
            forward = Vector3.forward;
            if (points.Count < 2) return false;
            var remaining = distanceFromEnd;
            for (var index = points.Count - 1; index > 0; index--)
            {
                var segment = points[index] - points[index - 1];
                segment.y = 0f;
                var length = segment.magnitude;
                if (length < 0.05f) continue;
                forward = segment / length;
                if (remaining <= length)
                {
                    position = points[index] - forward * remaining;
                    return true;
                }
                remaining -= length;
            }
            return false;
        }

        private void AddCrosswalk(MeshAccumulator accumulator, CrossingRecord crossing)
        {
            if (crossing.Shape.Count < 2) return;
            var start = Coordinates.ToWorld(crossing.Shape[0]);
            var end = Coordinates.ToWorld(crossing.Shape[^1]);
            var direction = end - start;
            direction.y = 0f;
            var length = direction.magnitude;
            if (length < 0.2f) return;
            direction.Normalize();
            var stripeCount = Mathf.Max(1, Mathf.FloorToInt(length / 1.05f));
            for (var stripe = 0; stripe < stripeCount; stripe++)
            {
                var center = start + direction * ((stripe + 0.5f) * length / stripeCount);
                accumulator.AddRibbon(new[] { center - direction * 0.33f, center + direction * 0.33f }, crossing.WidthM, 0.073f, 1f);
            }
        }

        private void AddHeroCrosswalks(MeshAccumulator accumulator, Vector3 heroCenter)
        {
            var approaches = document.Lanes
                .Where(lane => lane.EdgeFunction != "internal" && IsDriveable(lane) && lane.Shape.Count >= 2)
                .Select(lane =>
                {
                    var end = Coordinates.ToWorld(lane.Shape[^1]);
                    var previous = Coordinates.ToWorld(lane.Shape[^2]);
                    var forward = end - previous;
                    forward.y = 0f;
                    if (forward.sqrMagnitude > 0.001f) forward.Normalize();
                    return new { Lane = lane, End = end, Forward = forward, Distance = Vector3.Distance(end, heroCenter) };
                })
                .Where(item => item.Distance < 42f && item.Forward.sqrMagnitude > 0.5f)
                .GroupBy(item => Mathf.RoundToInt(Mathf.Repeat(
                    Mathf.Atan2(item.Forward.x, item.Forward.z) * Mathf.Rad2Deg, 360f) / 90f) % 4);

            foreach (var approach in approaches)
            {
                var lanes = approach.ToList();
                if (lanes.Count == 0) continue;
                var forward = lanes.Aggregate(Vector3.zero, (sum, lane) => sum + lane.Forward).normalized;
                var side = Vector3.Cross(Vector3.up, forward).normalized;
                var averageEnd = lanes.Aggregate(Vector3.zero, (sum, lane) => sum + lane.End) / lanes.Count;
                var projections = lanes.Select(lane => Vector3.Dot(lane.End - averageEnd, side)).ToList();
                var halfSpan = Mathf.Max(4.5f, (projections.Max() - projections.Min()) * 0.5f + (float)lanes.Average(lane => lane.Lane.WidthM) * 0.72f);
                var crosswalkCenter = averageEnd + forward * 2.45f;
                for (var stripe = -3; stripe <= 3; stripe++)
                {
                    var stripeCenter = crosswalkCenter + forward * stripe * 0.78f;
                    accumulator.AddRibbon(
                        new[] { stripeCenter - side * halfSpan, stripeCenter + side * halfSpan },
                        0.46f, 0.076f, 1f);
                }
            }
        }

        private void OnDestroy() => Materials?.Dispose();
    }
}
