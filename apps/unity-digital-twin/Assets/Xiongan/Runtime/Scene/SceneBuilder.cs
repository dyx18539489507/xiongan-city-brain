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
        private const string ShowcaseVisualAnchorJunctionId = ReferenceShowcaseLayout.JunctionId;

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
            lanes.Clear();
            junctions.Clear();
            foreach (var lane in document.Lanes) lanes[lane.SumoLaneId] = lane;
            foreach (var junction in document.Junctions) junctions[junction.SumoJunctionId] = junction;

            CreateGround();
            var asphalt = new MeshAccumulator();
            var bicycle = new MeshAccumulator();
            var sidewalk = new MeshAccumulator();
            var curb = new MeshAccumulator();
            var verge = new MeshAccumulator();
            var marking = new MeshAccumulator();
            var junctionMesh = new MeshAccumulator();
            var crossingMesh = new MeshAccumulator();
            var hasReferenceShowcase = junctions.ContainsKey(ShowcaseVisualAnchorJunctionId);
            ReferenceShowcaseFrame? showcaseFrame = hasReferenceShowcase
                ? ReferenceShowcaseLayout.Resolve(this)
                : null;

            for (var index = 0; index < document.Lanes.Count; index++)
            {
                var lane = document.Lanes[index];
                var points = lane.Shape.Select(point => Coordinates.ToWorld(point)).ToList();
                // Junction polygons are the single visible surface inside every
                // intersection. Drawing SUMO internal lanes a few millimetres
                // above the same polygon caused depth fighting while panning.
                if (lane.EdgeFunction == "internal") continue;
                if (lane.LaneKind == "bicycle")
                    AddRibbonOutsideShowcase(bicycle, points, lane.WidthM, 0.035f, 5f, showcaseFrame);
                else if (lane.LaneKind == "pedestrian")
                    AddRibbonOutsideShowcase(sidewalk, points, lane.WidthM, 0.085f, 3.2f, showcaseFrame);
                else
                {
                    AddRibbonOutsideShowcase(asphalt, points, lane.WidthM, 0.02f, 8f, showcaseFrame);
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
                if (showcaseFrame.HasValue && ordered.Any(lane => ReferenceShowcaseLayout.IntersectsRoadSurfaceOverride(
                        showcaseFrame.Value,
                        lane.Shape.Select(point => Coordinates.ToWorld(point)).ToList(),
                        lane.WidthM * 0.5f + 1f)))
                    continue;
                // Scene geometry is stored in the converted Unity coordinate
                // system: the minimum lane-index boundary offsets negatively,
                // while the maximum boundary offsets positively. This pairing
                // is verified by the fixed audit cameras and keeps raised verge
                // ribbons outside the asphalt carriageway.
                AddRoadEdgeDetails(ordered[0], -1f, curb, verge, marking);
                if (ordered.Count > 1) AddRoadEdgeDetails(ordered[^1], 1f, curb, verge, marking);
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
                if (hasReferenceShowcase && junction.SumoJunctionId == ShowcaseVisualAnchorJunctionId) continue;
                if (junction.Shape.Count >= 3)
                    junctionMesh.AddPolygon(junction.Shape.Select(point => Coordinates.ToWorld(point)).ToList(), 0.028f);
            }
            foreach (var crossing in document.Crossings.Where(item => item.JunctionId != ShowcaseVisualAnchorJunctionId))
                AddCrosswalk(crossingMesh, crossing);

            var approachConnections = document.Connections
                .Where(item => item.Direction is "s" or "l" or "r")
                .Where(item => lanes.TryGetValue(item.FromLaneId, out var lane) &&
                               lane.EdgeFunction != "internal" && IsDriveable(lane) && lane.Shape.Count >= 2)
                .GroupBy(item => item.FromLaneId);
            foreach (var approach in approachConnections)
            {
                var lane = lanes[approach.Key];
                var points = lane.Shape.Select(point => Coordinates.ToWorld(point)).ToList();
                if (!RoadMarkingPlacementRules.TryResolveArrow(points, out var arrowPosition, out var forward)) continue;
                if (showcaseFrame.HasValue && ReferenceShowcaseLayout.CoversRoadMarkingOverride(showcaseFrame.Value, arrowPosition)) continue;
                var directions = RoadMarkingPlacementRules.SelectDisplayDirections(
                    approach.Select(item => item.Direction));
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
                if (showcaseFrame.HasValue && ReferenceShowcaseLayout.CoversRoadMarkingOverride(showcaseFrame.Value, end)) continue;
                var previous = Coordinates.ToWorld(lane.Shape[^2]);
                var forward = (end - previous).normalized;
                var side = Vector3.Cross(Vector3.up, forward);
                marking.AddRibbon(new[] { end - side * lane.WidthM * 0.44f, end + side * lane.WidthM * 0.44f }, 0.42f, 0.071f, 1f);
            }

            asphalt.Build("SUMO道路面", Materials.Asphalt, transform);
            bicycle.Build("非机动车道", Materials.Bicycle, transform, false, SceneDetailClass.Context);
            sidewalk.Build("人行设施", Materials.Sidewalk, transform, false, SceneDetailClass.Context);
            curb.Build("花岗岩路缘石", Materials.Curb, transform, true, SceneDetailClass.Fine);
            verge.Build("道路侧分绿化带", Materials.Grass, transform, false, SceneDetailClass.Context);
            junctionMesh.Build("路口铺装", Materials.Junction, transform);
            crossingMesh.Build("斑马线", Materials.Marking, transform, false, SceneDetailClass.Fine);
            marking.Build("车道线停止线与导向箭头", Materials.Marking, transform, false, SceneDetailClass.Fine);

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
            const float apron = 3.5f;
            var minX = shape.Min(point => point.x) - apron;
            var maxX = shape.Max(point => point.x) + apron;
            var minZ = shape.Min(point => point.z) - apron;
            var maxZ = shape.Max(point => point.z) + apron;
            surface.AddPolygon(new[]
            {
                new Vector3(minX, 0f, minZ), new Vector3(maxX, 0f, minZ),
                new Vector3(maxX, 0f, maxZ), new Vector3(minX, 0f, maxZ),
            }, 0.031f);
            surface.Build("K08 连续沥青路口铺装", Materials.HeroAsphalt, transform);
        }

        private static bool IsDriveable(LaneRecord lane)
        {
            return lane.LaneKind is "motor" or "mixed";
        }

        private static void AddRibbonOutsideShowcase(
            MeshAccumulator accumulator,
            IReadOnlyList<Vector3> points,
            float width,
            float height,
            float textureMeters,
            ReferenceShowcaseFrame? frame)
        {
            var margin = width * 0.5f + 0.35f;
            if (!frame.HasValue || !ReferenceShowcaseLayout.IntersectsRoadSurfaceOverride(frame.Value, points, margin))
            {
                accumulator.AddRibbon(points, width, height, textureMeters);
                return;
            }

            for (var index = 0; index < points.Count - 1; index++)
            {
                var from = points[index];
                var to = points[index + 1];
                var distance = Vector3.Distance(from, to);
                var pieces = Mathf.Max(1, Mathf.CeilToInt(distance / 4f));
                for (var piece = 0; piece < pieces; piece++)
                {
                    var a = Vector3.Lerp(from, to, piece / (float)pieces);
                    var b = Vector3.Lerp(from, to, (piece + 1f) / pieces);
                    var midpoint = (a + b) * 0.5f;
                    if (ReferenceShowcaseLayout.CoversRoadSurfaceOverride(frame.Value, midpoint, margin)) continue;
                    accumulator.AddRibbon(new[] { a, b }, width, height, textureMeters);
                }
            }
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

        private void AddRoadEdgeDetails(LaneRecord lane, float sign, MeshAccumulator curb, MeshAccumulator verge, MeshAccumulator edgeLine)
        {
            var points = lane.Shape.Select(point => Coordinates.ToWorld(point)).ToList();
            curb.AddExtrudedRibbon(Offset(points, sign * (lane.WidthM * 0.5f + 0.16f)), 0.32f, 0.025f, 0.16f);
            // Verge polygons must sit below every driveable surface. Source OSM
            // edges occasionally overlap; a raised verge made legal SUMO cars
            // appear to drive on grass even though their lane was correct.
            verge.AddRibbon(Offset(points, sign * (lane.WidthM * 0.5f + 1.55f)), 2.45f, 0.012f, 5f);
            edgeLine.AddRibbon(Offset(points, sign * (lane.WidthM * 0.5f - 0.12f)), 0.1f, 0.067f, 1f);
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
                for (var stripe = -5; stripe <= 5; stripe++)
                {
                    var stripeCenter = crosswalkCenter + forward * stripe * 0.72f;
                    accumulator.AddRibbon(
                        new[] { stripeCenter - side * halfSpan, stripeCenter + side * halfSpan },
                        0.5f, 0.076f, 1f);
                }
            }
        }

        private void OnDestroy() => Materials?.Dispose();
    }
}
