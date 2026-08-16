using System.Collections;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;
using Xiongan.DigitalTwin.Interaction;

namespace Xiongan.DigitalTwin.Scene
{
    public sealed class UrbanContextBuilder : MonoBehaviour
    {
        private const string ShowcaseJunctionId = "cluster_11122023464_11122023574";
        private const string ShowcaseVisualAnchorJunctionId = ShowcaseJunctionId;

        public IEnumerator Build(SceneBuilder scene, System.Action<float, string> onProgress)
        {
            var showcaseJunction = scene.Document.Junctions.FirstOrDefault(item => item.SumoJunctionId == ShowcaseJunctionId);
            var showcaseAnchor = scene.Document.Junctions.FirstOrDefault(item => item.SumoJunctionId == ShowcaseVisualAnchorJunctionId)
                                 ?? showcaseJunction;
            var showcaseCenter = showcaseAnchor == null ? Vector3.zero : scene.Coordinates.ToWorld(showcaseAnchor.Position);
            var facades = Enumerable.Range(0, scene.Materials.Facades.Count).Select(_ => new MeshAccumulator()).ToArray();
            var roofs = new MeshAccumulator();
            var parapets = new MeshAccumulator();
            var roofEquipment = new MeshAccumulator();
            var osmGlazing = new MeshAccumulator();
            var osmWarmGlazing = new MeshAccumulator();
            var osmWindowFrames = new MeshAccumulator();
            for (var index = 0; index < scene.Document.Buildings.Count; index++)
            {
                var building = scene.Document.Buildings[index];
                var footprint = building.Footprint.Select(point => scene.Coordinates.ToWorld(point)).ToList();
                if (footprint.Count < 3) continue;
                if (showcaseJunction != null)
                {
                    var footprintCenter = new Vector3(footprint.Average(point => point.x), 0f, footprint.Average(point => point.z));
                    if (Vector3.Distance(footprintCenter, showcaseCenter) < 175f) continue;
                }
                var height = ResolveHeight(building.SceneId, building.HeightM, building.Levels);
                var hash = StableHash(building.SceneId);
                facades[hash % facades.Length].AddFacadeWalls(footprint, 0.08f, height, 10f + hash % 5);
                roofs.AddPolygon(footprint, height + 0.02f);
                parapets.AddFacadeWalls(footprint, height, height + 0.72f, 4f);
                AddRoofPlant(roofEquipment, footprint, height, hash);
                AddPolygonFacadeWindows(osmGlazing, osmWarmGlazing, osmWindowFrames, footprint, height, hash);
                if (index % 12 == 0) yield return null;
            }
            for (var index = 0; index < facades.Length; index++)
                facades[index].Build($"雄安现代建筑立面-{index + 1}", scene.Materials.Facades[index], transform);
            roofs.Build("建筑屋面", scene.Materials.BuildingRoof, transform);
            parapets.Build("建筑女儿墙", scene.Materials.Curb, transform);
            roofEquipment.Build("建筑屋顶设备", scene.Materials.Metal, transform);
            osmGlazing.Build("OSM建筑实体窗面", scene.Materials.BuildingGlass, transform, false);
            osmWarmGlazing.Build("OSM建筑少量暖色窗面", scene.Materials.BuildingGlassWarm, transform, false);
            osmWindowFrames.Build("OSM建筑实体层间窗框", scene.Materials.FacadeFrame, transform);
            CreateRepresentativeShowcaseDistrict(scene);
            var controlledInfill = CreateControlledJunctionInfill(scene, showcaseCenter);
            CreateCitywideLandUseInfill(scene, showcaseCenter, controlledInfill);
            CreateIdentifiableOpenSpaces(scene);

            var grass = new MeshAccumulator();
            var trunks = new MeshAccumulator();
            var crowns = new MeshAccumulator();
            var controlledTreeSource = Resources.Load<GameObject>("Art/Models/island_tree_02/island_tree_02_1k");
            foreach (var area in scene.Document.Vegetation)
            {
                var polygon = area.Shape.Select(point => scene.Coordinates.ToWorld(point)).ToList();
                grass.AddPolygon(polygon, 0.086f);
                ScatterTrees(area.SceneId, polygon, trunks, crowns);
            }

            foreach (var junction in scene.Document.Junctions.Where(item => item.Controlled))
            {
                var center = scene.Coordinates.ToWorld(junction.Position);
                if (junction.SumoJunctionId != ShowcaseJunctionId)
                {
                    AddLandmarkTrees(center, junction.SumoJunctionId, trunks, crowns, scene, controlledTreeSource);
                    foreach (var offset in new[]
                             {
                                 new Vector3(15f, 0f, 15f), new Vector3(-15f, 0f, 15f),
                                 new Vector3(15f, 0f, -15f), new Vector3(-15f, 0f, -15f),
                             }) CreateStreetLight(center + offset, scene, -Mathf.Atan2(offset.z, offset.x) * Mathf.Rad2Deg);
                }
            }

            if (showcaseJunction != null)
            {
                CreateFormalForegroundAssets(scene, showcaseCenter);
                CreateShowcaseStreetFurniture(scene, showcaseCenter);
            }

            grass.Build("OSM绿地与中央绿化", scene.Materials.Grass, transform, false);
            trunks.Build("真实化树干", scene.Materials.TreeBark, transform);
            crowns.Build("多层自然树冠", scene.Materials.TreeLeaves, transform);

            foreach (var device in scene.Document.RoadsideDevices)
                CreateRoadsideDevice(device.DeviceId, device.DeviceType, device.Provenance, scene.Coordinates.ToWorld(device.Position), scene);
            onProgress(0.82f, "建筑立面、自然绿化与城市家具已生成");
            yield return null;
        }

        private static float ResolveHeight(string id, float? height, float? levels)
        {
            if (height.HasValue && height.Value > 2f) return height.Value;
            if (levels.HasValue && levels.Value > 0f) return levels.Value * 3.2f;
            return 15f + StableHash(id) % 8 * 3.25f;
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

        private static void AddRoofPlant(MeshAccumulator equipment, IReadOnlyList<Vector3> footprint, float height, int hash)
        {
            var center = new Vector3(footprint.Average(point => point.x), height + 0.68f, footprint.Average(point => point.z));
            var width = 2.2f + hash % 4 * 0.45f;
            equipment.AddBox(center, new Vector3(width, 1.25f, width * 0.72f));
            if (hash % 3 == 0) equipment.AddBox(center + new Vector3(width, 0.25f, 0f), new Vector3(1.1f, 0.6f, 1.8f));
        }

        private static void AddPolygonFacadeWindows(
            MeshAccumulator glazing, MeshAccumulator warmGlazing, MeshAccumulator frames,
            IReadOnlyList<Vector3> footprint, float height, int seed)
        {
            if (footprint.Count < 3 || height < 7f) return;
            var center = footprint.Aggregate(Vector3.zero, (sum, point) => sum + point) / footprint.Count;
            const float floorHeight = 3.3f;
            var floors = Mathf.Max(1, Mathf.FloorToInt((height - 3.8f) / floorHeight));
            for (var edgeIndex = 0; edgeIndex < footprint.Count; edgeIndex++)
            {
                var from = footprint[edgeIndex];
                var to = footprint[(edgeIndex + 1) % footprint.Count];
                var direction = to - from;
                direction.y = 0f;
                var length = direction.magnitude;
                if (length < 4.2f) continue;
                direction /= length;
                var edgeCenter = (from + to) * 0.5f;
                var outward = Vector3.ProjectOnPlane(edgeCenter - center, Vector3.up).normalized;
                if (outward.sqrMagnitude < 0.2f) outward = Vector3.Cross(direction, Vector3.up).normalized;
                var moduleCount = Mathf.Max(1, Mathf.FloorToInt(length / 3.25f));
                var moduleWidth = length / moduleCount;
                for (var floor = 0; floor < floors; floor++)
                {
                    var y = 4.2f + floor * floorHeight;
                    if (y + 0.9f >= height) break;
                    for (var module = 0; module < moduleCount; module++)
                    {
                        var paneCenter = from + direction * (moduleWidth * (module + 0.5f)) +
                                         Vector3.up * y + outward * 0.055f;
                        var paneHalfWidth = moduleWidth * 0.31f;
                        const float paneHalfHeight = 0.82f;
                        var left = paneCenter - direction * paneHalfWidth;
                        var right = paneCenter + direction * paneHalfWidth;
                        var target = (seed + edgeIndex * 7 + floor * 11 + module * 3) % 37 == 0
                            ? warmGlazing
                            : glazing;
                        AddOutwardQuad(target, left - Vector3.up * paneHalfHeight, right - Vector3.up * paneHalfHeight,
                            right + Vector3.up * paneHalfHeight, left + Vector3.up * paneHalfHeight, outward);
                    }

                    var bandCenter = edgeCenter + Vector3.up * (y - 1.18f) + outward * 0.07f;
                    var bandHalf = 0.065f;
                    AddOutwardQuad(frames,
                        bandCenter - direction * length * 0.48f - Vector3.up * bandHalf,
                        bandCenter + direction * length * 0.48f - Vector3.up * bandHalf,
                        bandCenter + direction * length * 0.48f + Vector3.up * bandHalf,
                        bandCenter - direction * length * 0.48f + Vector3.up * bandHalf,
                        outward);
                }
            }
        }

        private static void AddOutwardQuad(
            MeshAccumulator accumulator, Vector3 a, Vector3 b, Vector3 c, Vector3 d, Vector3 outward)
        {
            var normal = Vector3.Cross(b - a, c - a).normalized;
            if (Vector3.Dot(normal, outward) >= 0f) accumulator.AddQuad(a, b, c, d);
            else accumulator.AddQuad(b, a, d, c);
        }

        private void CreateRepresentativeShowcaseDistrict(SceneBuilder scene)
        {
            var junction = scene.Document.Junctions.FirstOrDefault(item => item.SumoJunctionId == ShowcaseVisualAnchorJunctionId)
                           ?? scene.Document.Junctions.FirstOrDefault(item => item.SumoJunctionId == ShowcaseJunctionId);
            if (junction == null) return;
            var center = scene.Coordinates.ToWorld(junction.Position);
            var root = new GameObject("代表性视觉环境-非实测建筑");
            root.transform.SetParent(transform, false);
            CreateShowcaseCornerLandscaping(scene, root.transform, center);
            var plots = new[]
            {
                (new Vector3(-72f, 0f, -88f), new Vector2(44f, 28f), 47f, 0, 4),
                (new Vector3(-27f, 0f, -105f), new Vector2(30f, 24f), 25f, 3, 5),
                (new Vector3(28f, 0f, -106f), new Vector2(32f, 24f), 34f, 6, 6),
                (new Vector3(74f, 0f, -90f), new Vector2(45f, 29f), 51f, 5, 4),
                (new Vector3(-92f, 0f, -27f), new Vector2(28f, 54f), 24f, 2, 5),
                (new Vector3(94f, 0f, -25f), new Vector2(29f, 56f), 43f, 7, 6),
                (new Vector3(-92f, 0f, 32f), new Vector2(29f, 48f), 42f, 4, 4),
                (new Vector3(94f, 0f, 36f), new Vector2(31f, 50f), 29f, 1, 5),
                (new Vector3(-72f, 0f, 91f), new Vector2(43f, 29f), 35f, 6, 6),
                (new Vector3(-25f, 0f, 108f), new Vector2(31f, 25f), 23f, 2, 5),
                (new Vector3(30f, 0f, 111f), new Vector2(34f, 26f), 46f, 7, 4),
                (new Vector3(77f, 0f, 93f), new Vector2(45f, 31f), 33f, 3, 6),
            };
            var plotPaving = new MeshAccumulator();
            var plotPlanting = new MeshAccumulator();
            var plotLandscape = new MeshAccumulator();
            foreach (var (offset, size, height, materialIndex, style) in plots)
            {
                var plotCenter = center + offset;
                var towardRoad = offset.sqrMagnitude > 0.01f ? -offset.normalized : Vector3.forward;
                var sidePlot = Mathf.Abs(offset.x) > Mathf.Abs(offset.z);
                plotLandscape.AddPolygon(Rectangle(plotCenter, size.x + 20f, size.y + 18f), 0.086f);
                var plazaCenter = plotCenter + towardRoad * (sidePlot ? size.x * 0.5f + 3.5f : size.y * 0.5f + 3.5f);
                plotPaving.AddPolygon(Rectangle(
                    plazaCenter,
                    sidePlot ? 7.5f : size.x + 8f,
                    sidePlot ? size.y + 8f : 7.5f), 0.096f);
                plotPlanting.AddPolygon(Rectangle(
                    plotCenter + towardRoad * (sidePlot ? size.x * 0.5f + 8.3f : size.y * 0.5f + 8.3f),
                    sidePlot ? 4.2f : size.x + 6f,
                    sidePlot ? size.y + 6f : 4.2f), 0.105f);
                foreach (var wing in BuildingWings(plotCenter, size, height, style))
                {
                    var footprint = Rectangle(wing.Center, wing.Size.x, wing.Size.y);
                    var wall = new MeshAccumulator();
                    var roof = new MeshAccumulator();
                    var parapet = new MeshAccumulator();
                    wall.AddFacadeWalls(footprint, 0.08f, wing.Height, 8.5f);
                    roof.AddPolygon(footprint, wing.Height + 0.02f);
                    parapet.AddFacadeWalls(footprint, wing.Height, wing.Height + 0.8f, 3f);
                    wall.Build("多体量现代街区立面", scene.Materials.Facades[materialIndex], root.transform);
                    roof.Build("多体量街区屋面", scene.Materials.BuildingRoof, root.transform);
                    parapet.Build("多体量街区女儿墙", scene.Materials.Curb, root.transform);
                    if (style <= 3)
                        CreateProceduralFacadeModules(scene, root.transform, wing.Center, wing.Size, wing.Height, materialIndex);
                    else
                        CreateDistinctFacadeModules(scene, root.transform, wing.Center, wing.Size, wing.Height, materialIndex, style);
                }
                CreateBuildingStreetDetail(scene, root.transform, plotCenter, size, height, materialIndex, towardRoad);
            }
            plotPaving.Build("代表性街区实体硬质铺装", scene.Materials.HeroSidewalk, root.transform, false);
            plotPlanting.Build("代表性街区连续种植带", scene.Materials.HeroGrass, root.transform, false);
            plotLandscape.Build("代表性街区连续草坪", scene.Materials.HeroGrass, root.transform, false);
            scene.RegisterGeneratedBuildings(plots.Length);
        }

        private static IReadOnlyList<(Vector3 Center, Vector2 Size, float Height)> BuildingWings(
            Vector3 center, Vector2 size, float height, int style)
        {
            var wings = new List<(Vector3, Vector2, float)>
            {
                (center + new Vector3(0f, 0f, -size.y * 0.08f), new Vector2(size.x, size.y * 0.78f), height),
            };
            if (style == 1)
                wings.Add((center + new Vector3(size.x * 0.32f, 0f, size.y * 0.25f), new Vector2(size.x * 0.36f, size.y * 0.5f), height * 0.72f));
            else if (style == 2)
            {
                wings[0] = (center + new Vector3(size.x * 0.1f, 0f, -size.y * 0.08f), new Vector2(size.x * 0.72f, size.y * 0.82f), height);
                wings.Add((center + new Vector3(-size.x * 0.32f, 0f, size.y * 0.16f), new Vector2(size.x * 0.34f, size.y * 0.56f), height * 0.64f));
            }
            else if (style == 3)
            {
                wings[0] = (center + new Vector3(0f, 0f, -size.y * 0.12f), new Vector2(size.x * 0.62f, size.y * 0.7f), height);
                wings.Add((center + new Vector3(-size.x * 0.34f, 0f, size.y * 0.18f), new Vector2(size.x * 0.27f, size.y * 0.48f), height * 0.68f));
                wings.Add((center + new Vector3(size.x * 0.34f, 0f, size.y * 0.18f), new Vector2(size.x * 0.27f, size.y * 0.48f), height * 0.82f));
            }
            else if (style == 4)
            {
                wings[0] = (center, new Vector2(size.x, size.y), Mathf.Max(8.5f, height * 0.28f));
                wings.Add((center + new Vector3(size.x * 0.12f, 0f, -size.y * 0.08f), new Vector2(size.x * 0.5f, size.y * 0.62f), height));
            }
            else if (style == 5)
            {
                wings[0] = (center + new Vector3(0f, 0f, -size.y * 0.31f), new Vector2(size.x, size.y * 0.3f), height * 0.86f);
                wings.Add((center + new Vector3(-size.x * 0.36f, 0f, size.y * 0.12f), new Vector2(size.x * 0.28f, size.y * 0.58f), height));
                wings.Add((center + new Vector3(size.x * 0.36f, 0f, size.y * 0.12f), new Vector2(size.x * 0.28f, size.y * 0.58f), height * 0.72f));
            }
            else if (style == 6)
            {
                wings[0] = (center, new Vector2(size.x, size.y), Mathf.Max(7.5f, height * 0.25f));
                wings.Add((center + new Vector3(-size.x * 0.24f, 0f, 0f), new Vector2(size.x * 0.36f, size.y * 0.58f), height));
                wings.Add((center + new Vector3(size.x * 0.24f, 0f, size.y * 0.06f), new Vector2(size.x * 0.34f, size.y * 0.5f), height * 0.78f));
            }
            return wings;
        }

        private static IReadOnlyList<(Vector3 Center, float Radius)> CreateControlledJunctionInfill(
            SceneBuilder scene, Vector3 showcaseCenter)
        {
            var root = new GameObject("二十路口差异化城市街区填充");
            root.transform.SetParent(scene.transform, false);
            var facades = Enumerable.Range(0, scene.Materials.Facades.Count).Select(_ => new MeshAccumulator()).ToArray();
            var roofs = new MeshAccumulator();
            var parapets = new MeshAccumulator();
            var roofEquipment = new MeshAccumulator();
            var glazing = new MeshAccumulator();
            var frames = new MeshAccumulator();
            var facadeAccents = Enumerable.Range(0, scene.Materials.Facades.Count).Select(_ => new MeshAccumulator()).ToArray();
            var entranceGlass = new MeshAccumulator();
            var entranceFrames = new MeshAccumulator();
            var paving = new MeshAccumulator();
            var occupied = scene.Document.Buildings
                .Where(building => building.Footprint.Count >= 3)
                .Select(building =>
                {
                    var points = building.Footprint.Select(point => scene.Coordinates.ToWorld(point)).ToList();
                    var center = new Vector3(points.Average(point => point.x), 0f, points.Average(point => point.z));
                    var radius = points.Max(point => Vector3.Distance(center, new Vector3(point.x, 0f, point.z)));
                    return (Center: center, Radius: Mathf.Max(5f, radius));
                })
                .ToList();
            var generatedOccupancy = new List<(Vector3 Center, float Radius)>();
            var roadSegments = new List<(Vector3 From, Vector3 To)>();
            foreach (var lane in scene.Document.Lanes.Where(lane =>
                         lane.EdgeFunction != "internal" &&
                         (lane.LaneKind is "motor" or "mixed") &&
                         lane.Shape.Count >= 2))
            {
                var points = lane.Shape.Select(point => scene.Coordinates.ToWorld(point)).ToList();
                for (var index = 0; index < points.Count - 1; index++)
                    roadSegments.Add((points[index], points[index + 1]));
            }

            var created = 0;
            foreach (var junction in scene.Document.Junctions.Where(item => item.Controlled))
            {
                var center = scene.Coordinates.ToWorld(junction.Position);
                if (junction.SumoJunctionId == ShowcaseJunctionId) continue;
                var hash = StableHash(junction.SumoJunctionId);
                var candidates = CreateInfillCandidates(hash);
                var createdForJunction = 0;
                for (var plotIndex = 0; plotIndex < candidates.Count && createdForJunction < 14; plotIndex++)
                {
                    var sourceOffset = candidates[plotIndex];
                    var plotCenter = center + sourceOffset;
                    if (Vector3.Distance(plotCenter, showcaseCenter) < 152f) continue;

                    var innerPlot = sourceOffset.magnitude < 115f;
                    var width = (innerPlot ? 15f : 21f) + (hash + plotIndex * 7) % (innerPlot ? 11 : 15);
                    var depth = (innerPlot ? 13f : 17f) + (hash + plotIndex * 13) % (innerPlot ? 9 : 10);
                    var plotRadius = Mathf.Sqrt(width * width + depth * depth) * 0.5f;
                    var clearance = plotRadius + 3.5f;
                    if (IsNearRoad(plotCenter, clearance, roadSegments)) continue;
                    if (occupied.Any(existing =>
                            Vector3.Distance(existing.Center, plotCenter) < existing.Radius + plotRadius + 5f)) continue;

                    // The generic junction camera sits north-west of its target. Keep its
                    // approach clear so dense infill frames the intersection instead of
                    // putting the viewer inside a facade.
                    var cameraPlanarPosition = center + new Vector3(-34.8f, 0f, 95.6f);
                    if (Vector3.Distance(plotCenter, cameraPlanarPosition) < plotRadius + 42f) continue;

                    var styleSequence = new[] { 1, 2, 1, 3, 5, 1, 6, 4 };
                    var style = styleSequence[(hash + plotIndex) % styleSequence.Length];
                    var materialIndex = XionganFacadeIndex(
                        style == 4 ? "commercial" : "residential",
                        hash + plotIndex * 3,
                        facades.Length);
                    var distanceBand = Mathf.Clamp01(sourceOffset.magnitude / 160f);
                    var height = 24f + (hash + plotIndex * 19) % 6 * 3.05f + distanceBand * 2.5f;
                    if (style == 4) height += 6f;
                    var size = new Vector2(width, depth);
                    paving.AddPolygon(Rectangle(plotCenter, width + 9f, depth + 9f), 0.082f);
                    var wingIndex = 0;
                    foreach (var wing in BuildingWings(plotCenter, size, height, style))
                    {
                        var footprint = Rectangle(wing.Center, wing.Size.x, wing.Size.y);
                        facades[materialIndex].AddFacadeWalls(footprint, 0.085f, wing.Height, 8f);
                        roofs.AddPolygon(footprint, wing.Height + 0.025f);
                        parapets.AddFacadeWalls(footprint, wing.Height, wing.Height + 0.62f, 3f);
                        var accentIndex = (materialIndex + 2 + style + wingIndex) % facades.Length;
                        AddInfillFacadeBands(
                            glazing, frames, facadeAccents[accentIndex],
                            wing.Center, wing.Size, wing.Height,
                            hash + plotIndex * 43 + wingIndex * 17, style,
                            sourceOffset.magnitude > 120f);
                        wingIndex++;
                    }
                    AddInfillBuildingDetail(
                        roofEquipment, entranceGlass, entranceFrames,
                        plotCenter, size, height, style, center - plotCenter);
                    occupied.Add((plotCenter, plotRadius));
                    generatedOccupancy.Add((plotCenter, plotRadius));
                    created++;
                    createdForJunction++;
                }
                Debug.Log($"Controlled junction infill {junction.DisplayId}: {createdForJunction} buildings");
            }

            for (var index = 0; index < facades.Length; index++)
            {
                facades[index].Build($"差异化街区建筑立面-{index + 1}", scene.Materials.Facades[index], root.transform);
                facadeAccents[index].Build($"差异化街区立面构件-{index + 1}", scene.Materials.Facades[index], root.transform);
            }
            roofs.Build("差异化街区屋面与退台", scene.Materials.BuildingRoof, root.transform);
            parapets.Build("差异化街区女儿墙", scene.Materials.Curb, root.transform);
            roofEquipment.Build("差异化街区屋顶设备与冠部", scene.Materials.BuildingRoof, root.transform);
            glazing.Build("差异化街区实体窗带", scene.Materials.BuildingGlass, root.transform, false);
            frames.Build("差异化街区实体窗框与檐口", scene.Materials.FacadeFrame, root.transform);
            entranceGlass.Build("差异化街区实体门厅", scene.Materials.BuildingGlass, root.transform, false);
            entranceFrames.Build("差异化街区入口雨棚与框架", scene.Materials.FacadeFrame, root.transform);
            paving.Build($"差异化街区硬质场地-{created}", scene.Materials.Sidewalk, root.transform, false);
            root.name = $"二十路口差异化城市街区填充-{created}栋";
            scene.RegisterGeneratedBuildings(created);
            return generatedOccupancy;
        }

        private static IReadOnlyList<Vector3> CreateInfillCandidates(int seed)
        {
            var candidates = new List<Vector3>();
            // Generic junction cameras look from north-west towards south-east.
            // Populate that visible half first, then complete the side and rear
            // blocks so orbiting the camera still reveals a coherent district.
            var viewAngle = -70f + (seed % 15 - 7) * 0.85f;
            var radii = new[] { 50f, 64f, 78f, 94f, 112f, 134f, 158f, 186f };
            var visibleAngles = new[]
            {
                0f, -15f, 15f, -30f, 30f, -45f, 45f,
                -60f, 60f, -75f, 75f, -90f, 90f,
            };
            for (var ring = 0; ring < radii.Length; ring++)
            {
                foreach (var angleOffset in visibleAngles)
                {
                    var angle = (viewAngle + angleOffset + ((seed + ring * 19) % 9 - 4) * 0.75f) * Mathf.Deg2Rad;
                    var jitter = ((seed + ring * 37 + Mathf.RoundToInt(angleOffset) * 11) % 13 - 6) * 0.72f;
                    var resolvedRadius = radii[ring] + jitter;
                    candidates.Add(new Vector3(
                        Mathf.Cos(angle) * resolvedRadius,
                        0f,
                        Mathf.Sin(angle) * resolvedRadius));
                }
            }

            foreach (var angleOffset in new[] { -122f, 122f, -150f, 150f, 180f })
            {
                for (var ring = 1; ring < radii.Length; ring++)
                {
                    var angle = (viewAngle + angleOffset + ((seed + ring * 23) % 7 - 3)) * Mathf.Deg2Rad;
                    var resolvedRadius = radii[ring] + ((seed + ring * 29) % 9 - 4) * 0.9f;
                    candidates.Add(new Vector3(
                        Mathf.Cos(angle) * resolvedRadius,
                        0f,
                        Mathf.Sin(angle) * resolvedRadius));
                }
            }
            return candidates;
        }

        private static void CreateCitywideLandUseInfill(
            SceneBuilder scene, Vector3 showcaseCenter,
            IReadOnlyList<(Vector3 Center, float Radius)> controlledInfill)
        {
            var supportedTypes = new HashSet<string>
            {
                "residential", "commercial", "school", "kindergarten", "industrial",
                "exhibition_centre", "construction", "parking",
            };
            var zones = scene.Document.Zones
                .Where(zone => supportedTypes.Contains(zone.AreaType) && zone.Shape.Count >= 3)
                .Select(zone =>
                {
                    var polygon = zone.Shape.Select(point => scene.Coordinates.ToWorld(point)).ToList();
                    return (Id: zone.SceneId, Type: zone.AreaType, Polygon: polygon, Area: PolygonArea(polygon));
                })
                .Where(zone => zone.Area > 900f)
                .OrderBy(zone => ZonePriority(zone.Type))
                .ThenBy(zone => zone.Area)
                .ToList();
            if (zones.Count == 0) return;

            var preservedLand = scene.Document.Zones
                .Where(zone => zone.AreaType is "park" or "grass" && zone.Shape.Count >= 3)
                .Select(zone => zone.Shape.Select(point => scene.Coordinates.ToWorld(point)).ToList())
                .Concat(scene.Document.Vegetation
                    .Where(area => area.Shape.Count >= 3)
                    .Select(area => area.Shape.Select(point => scene.Coordinates.ToWorld(point)).ToList()))
                .ToList();
            var roadSegments = new List<(Vector3 From, Vector3 To)>();
            foreach (var lane in scene.Document.Lanes.Where(lane =>
                         lane.EdgeFunction != "internal" &&
                         (lane.LaneKind is "motor" or "mixed") &&
                         lane.Shape.Count >= 2))
            {
                var points = lane.Shape.Select(point => scene.Coordinates.ToWorld(point)).ToList();
                for (var index = 0; index < points.Count - 1; index++)
                    roadSegments.Add((points[index], points[index + 1]));
            }
            if (roadSegments.Count == 0) return;

            var allRoadPoints = roadSegments.SelectMany(segment => new[] { segment.From, segment.To }).ToList();
            var sceneMinX = allRoadPoints.Min(point => point.x) - 18f;
            var sceneMaxX = allRoadPoints.Max(point => point.x) + 18f;
            var sceneMinZ = allRoadPoints.Min(point => point.z) - 18f;
            var sceneMaxZ = allRoadPoints.Max(point => point.z) + 18f;
            var occupied = scene.Document.Buildings
                .Where(building => building.Footprint.Count >= 3)
                .Select(building =>
                {
                    var points = building.Footprint.Select(point => scene.Coordinates.ToWorld(point)).ToList();
                    var center = new Vector3(points.Average(point => point.x), 0f, points.Average(point => point.z));
                    var radius = points.Max(point => Vector3.Distance(center, new Vector3(point.x, 0f, point.z)));
                    return (Center: center, Radius: Mathf.Max(5f, radius));
                })
                .ToList();
            occupied.AddRange(controlledInfill);
            var controlledCenters = scene.Document.Junctions
                .Where(junction => junction.Controlled)
                .Select(junction => scene.Coordinates.ToWorld(junction.Position))
                .ToList();

            var root = new GameObject("全城功能区连续街区");
            root.transform.SetParent(scene.transform, false);
            var facades = Enumerable.Range(0, scene.Materials.Facades.Count).Select(_ => new MeshAccumulator()).ToArray();
            var roofs = new MeshAccumulator();
            var parapets = new MeshAccumulator();
            var glazing = new MeshAccumulator();
            var frames = new MeshAccumulator();
            var roofEquipment = new MeshAccumulator();
            var paving = new MeshAccumulator();
            var planting = new MeshAccumulator();
            var parkingGround = new MeshAccumulator();
            var parkingMarkings = new MeshAccumulator();
            var constructionGround = new MeshAccumulator();

            foreach (var zone in zones.Where(zone => zone.Type == "parking"))
                parkingGround.AddPolygon(zone.Polygon, 0.008f);
            foreach (var zone in zones.Where(zone => zone.Type == "construction"))
                constructionGround.AddPolygon(zone.Polygon, 0.009f);

            // This is a memory guard, not a distribution strategy. Buildings are
            // allocated in spatial rounds below so reaching the guard cannot leave
            // one end of the city systematically empty.
            const int citywideSafetyLimit = 740;
            var created = 0;
            var counts = new Dictionary<string, int>();
            foreach (var zone in zones)
            {
                if (created >= citywideSafetyLimit) break;
                var spacing = ZoneSpacing(zone.Type);
                var density = ZoneDensity(zone.Type);
                var zoneLimit = Mathf.Clamp(
                    Mathf.FloorToInt(zone.Area / (spacing * spacing) * density),
                    zone.Type is "parking" or "construction" ? 1 : 2,
                    zone.Type == "commercial" ? 34 : 24);
                var minX = Mathf.Max(sceneMinX, zone.Polygon.Min(point => point.x));
                var maxX = Mathf.Min(sceneMaxX, zone.Polygon.Max(point => point.x));
                var minZ = Mathf.Max(sceneMinZ, zone.Polygon.Min(point => point.z));
                var maxZ = Mathf.Min(sceneMaxZ, zone.Polygon.Max(point => point.z));
                if (maxX <= minX || maxZ <= minZ) continue;

                var seed = StableHash(zone.Id);
                var startX = Mathf.Floor(minX / spacing) * spacing + (seed % 13) * spacing / 13f;
                var startZ = Mathf.Floor(minZ / spacing) * spacing + (seed % 17) * spacing / 17f;
                var placedInZone = 0;
                var row = 0;
                for (var z = startZ; z <= maxZ && placedInZone < zoneLimit && created < citywideSafetyLimit; z += spacing, row++)
                {
                    var column = 0;
                    for (var x = startX; x <= maxX && placedInZone < zoneLimit && created < citywideSafetyLimit; x += spacing, column++)
                    {
                        var hash = StableHash($"{zone.Id}:{row}:{column}");
                        var jitterX = ((hash % 101) / 100f - 0.5f) * spacing * 0.3f;
                        var jitterZ = (((hash / 101) % 101) / 100f - 0.5f) * spacing * 0.3f;
                        var plotCenter = new Vector3(x + jitterX, 0f, z + jitterZ);
                        if (!PointInPolygon(plotCenter, zone.Polygon)) continue;
                        if (Vector3.Distance(plotCenter, showcaseCenter) < 228f) continue;
                        if (controlledCenters.Any(center => Vector3.Distance(center, plotCenter) < 118f)) continue;
                        if (preservedLand.Any(polygon => PointInPolygon(plotCenter, polygon))) continue;
                        if (zones.Any(other =>
                                other.Id != zone.Id && other.Area < zone.Area * 0.94f &&
                                other.Type != zone.Type && PointInPolygon(plotCenter, other.Polygon))) continue;

                        ResolveZonePlot(zone.Type, hash, out var width, out var depth, out var height, out var style);
                        var plotRadius = Mathf.Sqrt(width * width + depth * depth) * 0.5f;
                        if (!TryFindNearestRoadSegment(plotCenter, roadSegments, out var roadFrom, out var roadTo,
                                out var roadDistanceSquared)) continue;
                        var roadDistance = Mathf.Sqrt(roadDistanceSquared);
                        if (roadDistance < plotRadius + 7.5f || roadDistance > ZoneMaximumRoadDistance(zone.Type)) continue;
                        var roadDirection = roadTo - roadFrom;
                        roadDirection.y = 0f;
                        if (roadDirection.sqrMagnitude < 0.001f) roadDirection = Vector3.right;
                        roadDirection.Normalize();
                        if (!IsOrientedRectangleInsidePolygon(
                                plotCenter, width + 11f, depth + 11f, roadDirection, zone.Polygon)) continue;
                        if (preservedLand.Any(polygon =>
                                OrientedRectangle(plotCenter, width + 12f, depth + 12f, roadDirection)
                                    .Any(corner => PointInPolygon(corner, polygon)))) continue;
                        if (occupied.Any(existing =>
                                Vector3.Distance(existing.Center, plotCenter) < existing.Radius + plotRadius + 6f)) continue;

                        var materialIndex = XionganFacadeIndex(zone.Type, hash, facades.Length);
                        AddCitywideBuilding(
                            facades[materialIndex], roofs, parapets, glazing, frames, roofEquipment,
                            plotCenter, width, depth, height, roadDirection, style, hash);
                        paving.AddPolygon(
                            OrientedRectangle(plotCenter, width + 9f, depth + 9f, roadDirection), 0.082f);
                        if (zone.Type is "residential" or "school" or "kindergarten")
                        {
                            var side = Vector3.Cross(Vector3.up, roadDirection).normalized;
                            var gardenCenter = plotCenter + side * (depth * 0.5f + 3.2f);
                            planting.AddPolygon(
                                OrientedRectangle(gardenCenter, width * 0.62f, 3.8f, roadDirection), 0.092f);
                        }
                        if (zone.Type == "parking")
                            AddParkingBayMarkings(parkingMarkings, plotCenter, width, depth, roadDirection);

                        occupied.Add((plotCenter, plotRadius));
                        counts[zone.Type] = counts.TryGetValue(zone.Type, out var count) ? count + 1 : 1;
                        placedInZone++;
                        created++;
                    }
                }
                Debug.Log($"Citywide land-use infill {zone.Type} {zone.Id}: {placedInZone} buildings");
            }

            // Cover the city in road-connected planning cells, then give every
            // under-filled cell one plot per round. This avoids the old south-to-
            // north scan bias and forms continuous planned-new-city street walls.
            const float coverageCellSize = 112f;
            var firstCellX = Mathf.FloorToInt(sceneMinX / coverageCellSize);
            var lastCellX = Mathf.CeilToInt(sceneMaxX / coverageCellSize);
            var firstCellZ = Mathf.FloorToInt(sceneMinZ / coverageCellSize);
            var lastCellZ = Mathf.CeilToInt(sceneMaxZ / coverageCellSize);
            var coverageCells = new List<(int X, int Z, Vector3 Center, int Target, int Order)>();
            for (var cellZ = firstCellZ; cellZ <= lastCellZ; cellZ++)
            {
                for (var cellX = firstCellX; cellX <= lastCellX; cellX++)
                {
                    var center = new Vector3(
                        (cellX + 0.5f) * coverageCellSize, 0f,
                        (cellZ + 0.5f) * coverageCellSize);
                    if (!TryFindNearestRoadSegment(center, roadSegments, out _, out _, out var roadDistanceSquared) ||
                        roadDistanceSquared > 122f * 122f) continue;
                    if (Vector3.Distance(center, showcaseCenter) < 214f) continue;
                    if (controlledCenters.Any(controlled => Vector3.Distance(controlled, center) < 112f)) continue;
                    if (preservedLand.Any(polygon => PointInPolygon(center, polygon))) continue;

                    var containingZone = zones
                        .Where(zone => PointInPolygon(center, zone.Polygon))
                        .OrderBy(zone => zone.Area)
                        .FirstOrDefault();
                    if (containingZone.Type is "parking" or "construction") continue;
                    var target = containingZone.Type switch
                    {
                        "residential" => 4,
                        "commercial" => 4,
                        "school" or "kindergarten" => 3,
                        "industrial" or "exhibition_centre" => 2,
                        _ => 3,
                    };
                    coverageCells.Add((
                        cellX, cellZ, center, target,
                        StableHash($"coverage-order:{cellX}:{cellZ}")));
                }
            }
            coverageCells = coverageCells
                .OrderBy(cell => cell.Order)
                .ThenBy(cell => cell.X)
                .ThenBy(cell => cell.Z)
                .ToList();

            int CellOccupancy((int X, int Z, Vector3 Center, int Target, int Order) cell)
            {
                var half = coverageCellSize * 0.5f;
                return occupied.Count(item =>
                    Mathf.Abs(item.Center.x - cell.Center.x) < half &&
                    Mathf.Abs(item.Center.z - cell.Center.z) < half);
            }

            var coverageCreated = 0;
            var coveredCells = 0;
            for (var round = 0; round < 5 && created < citywideSafetyLimit; round++)
            {
                foreach (var cell in coverageCells)
                {
                    if (created >= citywideSafetyLimit) break;
                    if (CellOccupancy(cell) >= cell.Target) continue;
                    var placed = false;
                    for (var attempt = 0; attempt < 24 && !placed; attempt++)
                    {
                        var hash = StableHash($"coverage-plot:{cell.X}:{cell.Z}:{round}:{attempt}");
                        var plotCenter = cell.Center + new Vector3(
                            ((hash % 1009) / 1008f - 0.5f) * coverageCellSize * 0.82f,
                            0f,
                            (((hash / 1009) % 1009) / 1008f - 0.5f) * coverageCellSize * 0.82f);
                        if (Vector3.Distance(plotCenter, showcaseCenter) < 220f) continue;
                        if (controlledCenters.Any(controlled => Vector3.Distance(controlled, plotCenter) < 118f)) continue;
                        if (preservedLand.Any(polygon => PointInPolygon(plotCenter, polygon))) continue;

                        var containingZone = zones
                            .Where(zone => PointInPolygon(plotCenter, zone.Polygon))
                            .OrderBy(zone => zone.Area)
                            .FirstOrDefault();
                        var areaType = string.IsNullOrEmpty(containingZone.Id)
                            ? (hash % 6 == 0 ? "commercial" : "residential")
                            : containingZone.Type;
                        if (areaType is "parking" or "construction") continue;

                        ResolveZonePlot(areaType, hash, out var width, out var depth, out var height, out var style);
                        width *= 0.86f;
                        depth *= 0.86f;
                        height *= 0.94f;
                        var plotRadius = Mathf.Sqrt(width * width + depth * depth) * 0.5f;
                        if (!TryFindNearestRoadSegment(plotCenter, roadSegments, out var roadFrom, out var roadTo,
                                out var candidateRoadDistanceSquared)) continue;
                        var roadDistance = Mathf.Sqrt(candidateRoadDistanceSquared);
                        if (roadDistance < plotRadius + 7f || roadDistance > 104f) continue;
                        var roadDirection = roadTo - roadFrom;
                        roadDirection.y = 0f;
                        if (roadDirection.sqrMagnitude < 0.001f) roadDirection = Vector3.right;
                        roadDirection.Normalize();
                        var footprint = OrientedRectangle(
                            plotCenter, width + 10f, depth + 10f, roadDirection);
                        if (preservedLand.Any(polygon =>
                                footprint.Any(corner => PointInPolygon(corner, polygon)))) continue;
                        if (occupied.Any(existing =>
                                Vector3.Distance(existing.Center, plotCenter) < existing.Radius + plotRadius + 4.5f)) continue;

                        var materialIndex = XionganFacadeIndex(areaType, hash, facades.Length);
                        AddCitywideBuilding(
                            facades[materialIndex], roofs, parapets, glazing, frames, roofEquipment,
                            plotCenter, width, depth, height, roadDirection, style, hash, true);
                        paving.AddPolygon(
                            OrientedRectangle(plotCenter, width + 8f, depth + 8f, roadDirection), 0.082f);
                        if (areaType is "residential" or "school" or "kindergarten")
                        {
                            var side = Vector3.Cross(Vector3.up, roadDirection).normalized;
                            planting.AddPolygon(
                                OrientedRectangle(
                                    plotCenter + side * (depth * 0.5f + 2.8f),
                                    width * 0.6f, 3.4f, roadDirection),
                                0.092f);
                        }
                        occupied.Add((plotCenter, plotRadius));
                        counts[areaType] = counts.TryGetValue(areaType, out var count) ? count + 1 : 1;
                        coverageCreated++;
                        created++;
                        placed = true;
                    }
                }
            }

            // A second pass derives plots directly from road edges. Random points
            // alone miss narrow or irregular blocks; road-normal offsets give those
            // cells a predictable street frontage while retaining all collision,
            // park and controlled-junction exclusions.
            var roadEdgeCreated = 0;
            for (var sweep = 0; sweep < 5 && created < citywideSafetyLimit; sweep++)
            {
                foreach (var cell in coverageCells)
                {
                    if (created >= citywideSafetyLimit) break;
                    if (CellOccupancy(cell) >= cell.Target) continue;
                    if (!TryFindNearestRoadSegment(cell.Center, roadSegments, out var roadFrom, out var roadTo,
                            out _)) continue;
                    var roadDirection = roadTo - roadFrom;
                    roadDirection.y = 0f;
                    if (roadDirection.sqrMagnitude < 0.001f) continue;
                    roadDirection.Normalize();
                    var roadNormal = Vector3.Cross(Vector3.up, roadDirection).normalized;
                    var roadAnchor = ClosestPointOnSegment(cell.Center, roadFrom, roadTo);
                    var placed = false;
                    for (var attempt = 0; attempt < 18 && !placed; attempt++)
                    {
                        var hash = StableHash($"road-edge-plot:{cell.X}:{cell.Z}:{sweep}:{attempt}");
                        var initialZone = zones
                            .Where(zone => PointInPolygon(cell.Center, zone.Polygon))
                            .OrderBy(zone => zone.Area)
                            .FirstOrDefault();
                        var areaType = string.IsNullOrEmpty(initialZone.Id)
                            ? (hash % 7 == 0 ? "commercial" : "residential")
                            : initialZone.Type;
                        if (areaType is "parking" or "construction") continue;
                        ResolveZonePlot(areaType, hash, out var width, out var depth, out var height, out var style);
                        width *= 0.78f;
                        depth *= 0.8f;
                        height *= 0.9f;
                        var plotRadius = Mathf.Sqrt(width * width + depth * depth) * 0.5f;
                        var sideSign = (attempt & 1) == 0 ? -1f : 1f;
                        var ring = attempt / 2 % 3;
                        var alongOffset = ((hash / 101) % 1009 / 1008f - 0.5f) * 42f;
                        var plotCenter = roadAnchor + roadDirection * alongOffset +
                                         roadNormal * sideSign * (plotRadius + 11f + ring * 7f);
                        if (Mathf.Abs(plotCenter.x - cell.Center.x) > coverageCellSize * 0.68f ||
                            Mathf.Abs(plotCenter.z - cell.Center.z) > coverageCellSize * 0.68f) continue;
                        if (Vector3.Distance(plotCenter, showcaseCenter) < 220f) continue;
                        if (controlledCenters.Any(controlled => Vector3.Distance(controlled, plotCenter) < 118f)) continue;
                        if (preservedLand.Any(polygon => PointInPolygon(plotCenter, polygon))) continue;
                        var containingZone = zones
                            .Where(zone => PointInPolygon(plotCenter, zone.Polygon))
                            .OrderBy(zone => zone.Area)
                            .FirstOrDefault();
                        if (containingZone.Type is "parking" or "construction") continue;

                        if (!TryFindNearestRoadSegment(plotCenter, roadSegments, out _, out _,
                                out var candidateRoadDistanceSquared)) continue;
                        var roadDistance = Mathf.Sqrt(candidateRoadDistanceSquared);
                        if (roadDistance < plotRadius + 5.5f || roadDistance > 102f) continue;
                        var footprint = OrientedRectangle(
                            plotCenter, width + 8f, depth + 8f, roadDirection);
                        if (preservedLand.Any(polygon =>
                                footprint.Any(corner => PointInPolygon(corner, polygon)))) continue;
                        if (occupied.Any(existing =>
                                Vector3.Distance(existing.Center, plotCenter) < existing.Radius + plotRadius + 3.2f)) continue;

                        var materialIndex = XionganFacadeIndex(areaType, hash, facades.Length);
                        AddCitywideBuilding(
                            facades[materialIndex], roofs, parapets, glazing, frames, roofEquipment,
                            plotCenter, width, depth, height, roadDirection, style, hash, true);
                        paving.AddPolygon(
                            OrientedRectangle(plotCenter, width + 7f, depth + 7f, roadDirection), 0.082f);
                        if (areaType is "residential" or "school" or "kindergarten")
                        {
                            planting.AddPolygon(
                                OrientedRectangle(
                                    plotCenter + roadNormal * (depth * 0.5f + 2.5f),
                                    width * 0.56f, 3.1f, roadDirection),
                                0.092f);
                        }
                        occupied.Add((plotCenter, plotRadius));
                        counts[areaType] = counts.TryGetValue(areaType, out var count) ? count + 1 : 1;
                        roadEdgeCreated++;
                        created++;
                        placed = true;
                    }
                }
            }
            coveredCells = coverageCells.Count(cell => CellOccupancy(cell) >= cell.Target);

            for (var index = 0; index < facades.Length; index++)
                facades[index].Build($"全城背景建筑立面-{index + 1}", scene.Materials.Facades[index], root.transform);
            roofs.Build("全城背景建筑屋面", scene.Materials.BuildingRoof, root.transform);
            parapets.Build("全城背景建筑女儿墙", scene.Materials.Curb, root.transform);
            glazing.Build("全城背景建筑实体窗带", scene.Materials.BuildingGlass, root.transform, false);
            frames.Build("全城背景建筑实体窗框", scene.Materials.FacadeFrame, root.transform);
            roofEquipment.Build("全城背景建筑屋顶机房", scene.Materials.BuildingRoof, root.transform);
            paving.Build("全城建筑前场硬质铺装", scene.Materials.Sidewalk, root.transform, false);
            planting.Build("住宅学校庭院绿地", scene.Materials.Grass, root.transform, false);
            parkingGround.Build("停车功能区实体铺装", scene.Materials.ParkingGround, root.transform, false);
            parkingMarkings.Build("停车功能区实体标线", scene.Materials.Marking, root.transform, false);
            constructionGround.Build("施工功能区实体场地", scene.Materials.ConstructionGround, root.transform, false);
            root.name = $"全城功能区连续街区-{created}栋";
            scene.RegisterGeneratedBuildings(created);
            Debug.Log($"Citywide land-use infill complete: {created} buildings; " +
                      string.Join(", ", counts.OrderBy(item => item.Key).Select(item => $"{item.Key}={item.Value}")) +
                      $"; coverage infill={coverageCreated}; road-edge infill={roadEdgeCreated}; " +
                      $"cells={coveredCells}/{coverageCells.Count}");
        }

        private static int XionganFacadeIndex(string areaType, int seed, int materialCount)
        {
            if (materialCount <= 1) return 0;
            var choices = areaType switch
            {
                "commercial" or "exhibition_centre" => new[] { 1, 3, 6, 7 },
                "school" or "kindergarten" => new[] { 0, 4, 5, 7 },
                "industrial" => new[] { 1, 3, 7 },
                _ => new[] { 0, 2, 4, 5, 7 },
            };
            return choices[seed % choices.Length] % materialCount;
        }

        private static void CreateIdentifiableOpenSpaces(SceneBuilder scene)
        {
            var openSpaces = scene.Document.Zones
                .Where(zone => zone.AreaType is "park" or "grass" && zone.Shape.Count >= 3)
                .Select(zone => (
                    Id: zone.SceneId,
                    Polygon: zone.Shape.Select(point => scene.Coordinates.ToWorld(point)).ToList()))
                .Where(area => PolygonArea(area.Polygon) > 1400f)
                .ToList();
            if (openSpaces.Count == 0) return;

            var root = new GameObject("可识别公园广场与公共廊亭");
            root.transform.SetParent(scene.transform, false);
            var paths = new MeshAccumulator();
            var plazas = new MeshAccumulator();
            var pavilionWalls = new MeshAccumulator();
            var pavilionRoofs = new MeshAccumulator();
            var pavilionFrames = new MeshAccumulator();
            var created = 0;

            foreach (var area in openSpaces)
            {
                var minX = area.Polygon.Min(point => point.x);
                var maxX = area.Polygon.Max(point => point.x);
                var minZ = area.Polygon.Min(point => point.z);
                var maxZ = area.Polygon.Max(point => point.z);
                var boundsCenter = new Vector3((minX + maxX) * 0.5f, 0f, (minZ + maxZ) * 0.5f);
                var vertexCenter = area.Polygon.Aggregate(Vector3.zero, (sum, point) => sum + point) /
                                   area.Polygon.Count;
                var centerCandidates = new List<Vector3> { boundsCenter, vertexCenter };
                centerCandidates.AddRange(area.Polygon.Select(point => Vector3.Lerp(vertexCenter, point, 0.32f)));
                var center = centerCandidates.FirstOrDefault(candidate =>
                    PointInPolygon(candidate, area.Polygon) &&
                    IsOrientedRectangleInsidePolygon(candidate, 18f, 14f, Vector3.right, area.Polygon));
                if (!PointInPolygon(center, area.Polygon)) continue;

                var longDirection = maxX - minX >= maxZ - minZ ? Vector3.right : Vector3.forward;
                var crossDirection = Vector3.Cross(Vector3.up, longDirection).normalized;
                var promenadeLength = Mathf.Clamp(
                    longDirection == Vector3.right ? (maxX - minX) * 0.54f : (maxZ - minZ) * 0.54f,
                    24f, 74f);
                var promenade = OrientedRectangle(center, promenadeLength, 3.8f, longDirection);
                if (promenade.All(corner => PointInPolygon(corner, area.Polygon)))
                    paths.AddPolygon(promenade, 0.098f);
                var crossLength = Mathf.Clamp(
                    longDirection == Vector3.right ? (maxZ - minZ) * 0.38f : (maxX - minX) * 0.38f,
                    16f, 46f);
                var crossPath = OrientedRectangle(center, crossLength, 3.2f, crossDirection);
                if (crossPath.All(corner => PointInPolygon(corner, area.Polygon)))
                    paths.AddPolygon(crossPath, 0.099f);

                var seed = StableHash(area.Id);
                var pavilionCenter = center + longDirection * Mathf.Min(11f + seed % 7, promenadeLength * 0.28f) +
                                      crossDirection * ((seed & 1) == 0 ? 7f : -7f);
                const float pavilionWidth = 11.5f;
                const float pavilionDepth = 6.8f;
                var pavilion = OrientedRectangle(
                    pavilionCenter, pavilionWidth, pavilionDepth, longDirection);
                if (!pavilion.All(corner => PointInPolygon(corner, area.Polygon))) continue;

                plazas.AddPolygon(
                    OrientedRectangle(pavilionCenter, pavilionWidth + 7f, pavilionDepth + 7f, longDirection),
                    0.096f);
                pavilionWalls.AddExtrudedPolygon(pavilion, 0.11f, 3.15f);
                pavilionRoofs.AddPolygon(
                    OrientedRectangle(pavilionCenter, pavilionWidth + 1.8f, pavilionDepth + 1.8f, longDirection),
                    3.42f);
                var side = Vector3.Cross(Vector3.up, longDirection).normalized;
                foreach (var along in new[] { -0.42f, 0.42f })
                foreach (var across in new[] { -0.42f, 0.42f })
                    pavilionFrames.AddBox(
                        pavilionCenter + longDirection * pavilionWidth * along +
                        side * pavilionDepth * across + Vector3.up * 1.62f,
                        new Vector3(0.28f, 3.24f, 0.28f));
                created++;
            }

            paths.Build("公园十字慢行步道", scene.Materials.Sidewalk, root.transform, false);
            plazas.Build("公园廊亭前场铺装", scene.Materials.HeroSidewalk, root.transform, false);
            pavilionWalls.Build("公园公共廊亭浅色实体墙", scene.Materials.Facades[0], root.transform);
            pavilionRoofs.Build("公园公共廊亭平屋盖", scene.Materials.BuildingRoof, root.transform);
            pavilionFrames.Build("公园公共廊亭细柱", scene.Materials.FacadeFrame, root.transform);
            root.name = $"可识别公园广场与公共廊亭-{created}处";
            Debug.Log($"Identifiable open spaces complete: {created}/{openSpaces.Count}");
        }

        private static void AddCitywideBuilding(
            MeshAccumulator facade, MeshAccumulator roofs, MeshAccumulator parapets,
            MeshAccumulator glazing, MeshAccumulator frames, MeshAccumulator roofEquipment,
            Vector3 center, float width, float depth, float height,
            Vector3 roadDirection, int style, int seed, bool simplified = false)
        {
            var volumes = new List<(Vector3 Center, float Width, float Depth, float Height, Vector3 Direction)>();
            var normal = Vector3.Cross(Vector3.up, roadDirection).normalized;
            if (style == 4)
            {
                volumes.Add((center, width, depth, Mathf.Min(10.5f, height * 0.32f), roadDirection));
                volumes.Add((center + roadDirection * width * 0.06f - normal * depth * 0.04f,
                    width * 0.68f, depth * 0.7f, height, roadDirection));
            }
            else if (style == 2 && width > 25f)
            {
                volumes.Add((center - roadDirection * width * 0.25f, width * 0.43f, depth, height, roadDirection));
                volumes.Add((center + roadDirection * width * 0.25f, width * 0.43f, depth * 0.88f,
                    height * 0.78f, roadDirection));
            }
            else if (style == 5 && width > 26f && depth > 17f)
            {
                volumes.Add((center - normal * depth * 0.2f, width, depth * 0.55f, height, roadDirection));
                volumes.Add((center - roadDirection * width * 0.28f + normal * depth * 0.12f,
                    depth * 0.7f, width * 0.34f, height * 0.72f, normal));
            }
            else if (style == 6 && width > 27f)
            {
                volumes.Add((center - normal * depth * 0.08f, width, depth * 0.72f, height, roadDirection));
                volumes.Add((center + normal * depth * 0.35f, width * 0.58f, depth * 0.24f,
                    height * 0.56f, roadDirection));
            }
            else
            {
                volumes.Add((center, width, depth, height, roadDirection));
            }

            for (var index = 0; index < volumes.Count; index++)
            {
                var volume = volumes[index];
                var footprint = OrientedRectangle(
                    volume.Center, volume.Width, volume.Depth, volume.Direction);
                facade.AddFacadeWalls(footprint, 0.084f, volume.Height, 8.5f);
                roofs.AddPolygon(footprint, volume.Height + 0.024f);
                parapets.AddFacadeWalls(footprint, volume.Height, volume.Height + 0.58f, 4f);
                AddCitywideFacadeBands(
                    glazing, frames, footprint, volume.Height, seed + index * 31, style, simplified);
            }

            var equipmentCenter = center + roadDirection * width * 0.12f - normal * depth * 0.08f;
            var equipment = OrientedRectangle(
                equipmentCenter,
                Mathf.Clamp(width * 0.22f, 3.2f, 8f),
                Mathf.Clamp(depth * 0.2f, 2.8f, 6.5f),
                roadDirection);
            roofEquipment.AddExtrudedPolygon(equipment, height + 0.08f, height + 1.25f + style * 0.08f);
        }

        private static void AddCitywideFacadeBands(
            MeshAccumulator glazing, MeshAccumulator frames,
            IReadOnlyList<Vector3> footprint, float height, int seed, int style, bool simplified)
        {
            if (footprint.Count < 3 || height < 7f) return;
            var center = footprint.Aggregate(Vector3.zero, (sum, point) => sum + point) / footprint.Count;
            var floorHeight = 3.25f + seed % 3 * 0.12f;
            for (var edgeIndex = 0; edgeIndex < footprint.Count; edgeIndex++)
            {
                if (simplified && edgeIndex % 2 == 1) continue;
                var from = footprint[edgeIndex];
                var to = footprint[(edgeIndex + 1) % footprint.Count];
                var direction = to - from;
                direction.y = 0f;
                var length = direction.magnitude;
                if (length < 4f) continue;
                direction /= length;
                var edgeCenter = (from + to) * 0.5f;
                var outward = Vector3.ProjectOnPlane(edgeCenter - center, Vector3.up).normalized;
                if (outward.sqrMagnitude < 0.2f) continue;

                var groundCenter = edgeCenter + Vector3.up * 2.05f + outward * 0.075f;
                AddOutwardQuad(frames,
                    groundCenter - direction * length * 0.46f - Vector3.up * 1.72f,
                    groundCenter + direction * length * 0.46f - Vector3.up * 1.72f,
                    groundCenter + direction * length * 0.46f + Vector3.up * 1.72f,
                    groundCenter - direction * length * 0.46f + Vector3.up * 1.72f,
                    outward);

                if (style == 4)
                {
                    var curtainBottom = 4.15f;
                    var curtainTop = Mathf.Max(curtainBottom + 2f, height - 1.15f);
                    AddFacadeStrip(glazing, edgeCenter, direction, outward, length * 0.86f,
                        curtainBottom, curtainTop, 0.09f);
                    var columns = Mathf.Max(3, Mathf.FloorToInt(length / (simplified ? 10f : 7f)));
                    for (var column = 0; column <= columns; column++)
                    {
                        var along = -length * 0.43f + length * 0.86f * column / columns;
                        AddFacadeStrip(frames, edgeCenter + direction * along, direction, outward,
                            0.12f, curtainBottom, curtainTop, 0.12f);
                    }
                }
                else
                {
                    var floor = 0;
                    for (var y = 5.15f; y + 0.85f < height; y += floorHeight * (simplified ? 3f : 2f), floor++)
                    {
                        var bandWidth = length * (style is 3 or 6 ? 0.86f : 0.78f);
                        AddFacadeStrip(glazing, edgeCenter, direction, outward, bandWidth,
                            y - 0.72f, y + 0.72f, 0.09f);
                        AddFacadeStrip(frames, edgeCenter, direction, outward, length * 0.9f,
                            y - 1.08f, y - 0.94f, 0.12f);
                        if ((floor + edgeIndex + seed) % 3 == 0)
                        {
                            var dividerOffset = ((floor + seed) % 2 == 0 ? -1f : 1f) * bandWidth * 0.22f;
                            AddFacadeStrip(frames, edgeCenter + direction * dividerOffset, direction, outward,
                                0.13f, y - 0.86f, y + 0.86f, 0.13f);
                        }
                    }
                }
            }
        }

        private static void AddFacadeStrip(
            MeshAccumulator target, Vector3 edgeCenter, Vector3 direction, Vector3 outward,
            float width, float bottom, float top, float offset)
        {
            var surface = edgeCenter + outward * offset;
            AddOutwardQuad(target,
                surface - direction * width * 0.5f + Vector3.up * bottom,
                surface + direction * width * 0.5f + Vector3.up * bottom,
                surface + direction * width * 0.5f + Vector3.up * top,
                surface - direction * width * 0.5f + Vector3.up * top,
                outward);
        }

        private static void AddParkingBayMarkings(
            MeshAccumulator markings, Vector3 center, float width, float depth, Vector3 direction)
        {
            var normal = Vector3.Cross(Vector3.up, direction).normalized;
            var bays = Mathf.Clamp(Mathf.FloorToInt(width / 3f), 3, 10);
            for (var bay = 0; bay <= bays; bay++)
            {
                var along = -width * 0.42f + width * 0.84f * bay / bays;
                var from = center + direction * along - normal * depth * 0.34f;
                var to = center + direction * along + normal * depth * 0.34f;
                markings.AddRibbon(new[] { from, to }, 0.1f, 0.088f, 1f);
            }
        }

        private static int ZonePriority(string areaType)
        {
            return areaType switch
            {
                "kindergarten" => 0,
                "school" => 1,
                "industrial" => 2,
                "exhibition_centre" => 3,
                "residential" => 4,
                "construction" => 5,
                "parking" => 6,
                _ => 7,
            };
        }

        private static float ZoneSpacing(string areaType)
        {
            return areaType switch
            {
                "kindergarten" => 43f,
                "school" => 58f,
                "industrial" => 64f,
                "exhibition_centre" => 58f,
                "commercial" => 52f,
                "construction" => 62f,
                "parking" => 58f,
                _ => 43f,
            };
        }

        private static float ZoneDensity(string areaType)
        {
            return areaType switch
            {
                "school" => 0.58f,
                "kindergarten" => 0.5f,
                "industrial" => 0.46f,
                "construction" => 0.28f,
                "parking" => 0.22f,
                "commercial" => 0.48f,
                _ => 0.57f,
            };
        }

        private static float ZoneMaximumRoadDistance(string areaType)
        {
            return areaType switch
            {
                "industrial" => 118f,
                "construction" => 125f,
                "commercial" => 110f,
                _ => 96f,
            };
        }

        private static void ResolveZonePlot(
            string areaType, int seed,
            out float width, out float depth, out float height, out int style)
        {
            // Xiong'an is read here as a restrained, planned northern new city:
            // mid-rise courtyard/slab housing, calm podium offices, continuous
            // street walls and low civic/campus bars rather than random towers.
            style = 1;
            switch (areaType)
            {
                case "commercial":
                    width = 31f + seed % 18;
                    depth = 19f + seed / 7 % 10;
                    height = 24f + seed / 13 % 8 * 3.3f;
                    style = seed % 5 == 0 ? 4 : seed % 3 == 0 ? 6 : 3;
                    if (style == 4) height += 7f;
                    break;
                case "school":
                    width = 40f + seed % 18;
                    depth = 15f + seed / 7 % 7;
                    height = 14f + seed / 13 % 3 * 2.8f;
                    style = seed % 3 == 0 ? 6 : 5;
                    break;
                case "kindergarten":
                    width = 25f + seed % 13;
                    depth = 15f + seed / 7 % 6;
                    height = 10.5f + seed / 13 % 3 * 2.1f;
                    style = seed % 2 == 0 ? 5 : 6;
                    break;
                case "industrial":
                    width = 42f + seed % 19;
                    depth = 23f + seed / 7 % 11;
                    height = 12f + seed / 13 % 3 * 2.6f;
                    style = 3;
                    break;
                case "exhibition_centre":
                    width = 46f + seed % 15;
                    depth = 24f + seed / 7 % 9;
                    height = 17f + seed / 13 % 4 * 2.7f;
                    style = 6;
                    break;
                case "construction":
                    width = 24f + seed % 15;
                    depth = 16f + seed / 7 % 10;
                    height = 10f + seed / 13 % 5 * 2.3f;
                    style = 3;
                    break;
                case "parking":
                    width = 26f + seed % 14;
                    depth = 17f + seed / 7 % 9;
                    height = 8f + seed / 13 % 3 * 2.2f;
                    style = 3;
                    break;
                default:
                    width = 29f + seed % 18;
                    depth = 15f + seed / 7 % 7;
                    height = 27f + seed / 13 % 5 * 3.15f;
                    style = seed % 7 == 0 ? 5 : seed % 4 == 0 ? 2 : 1;
                    break;
            }
        }

        private static float PolygonArea(IReadOnlyList<Vector3> polygon)
        {
            var area = 0f;
            for (var index = 0; index < polygon.Count; index++)
            {
                var next = (index + 1) % polygon.Count;
                area += polygon[index].x * polygon[next].z - polygon[next].x * polygon[index].z;
            }
            return Mathf.Abs(area) * 0.5f;
        }

        private static bool PointInPolygon(Vector3 point, IReadOnlyList<Vector3> polygon)
        {
            var inside = false;
            for (int index = 0, previous = polygon.Count - 1; index < polygon.Count; previous = index++)
            {
                var a = polygon[index];
                var b = polygon[previous];
                if ((a.z > point.z) == (b.z > point.z)) continue;
                var crossingX = (b.x - a.x) * (point.z - a.z) / (b.z - a.z) + a.x;
                if (point.x < crossingX) inside = !inside;
            }
            return inside;
        }

        private static bool IsOrientedRectangleInsidePolygon(
            Vector3 center, float width, float depth, Vector3 direction,
            IReadOnlyList<Vector3> polygon)
        {
            return OrientedRectangle(center, width, depth, direction)
                .All(corner => PointInPolygon(corner, polygon));
        }

        private static List<Vector3> OrientedRectangle(
            Vector3 center, float width, float depth, Vector3 direction)
        {
            direction.y = 0f;
            if (direction.sqrMagnitude < 0.001f) direction = Vector3.right;
            direction.Normalize();
            var normal = Vector3.Cross(Vector3.up, direction).normalized;
            var along = direction * width * 0.5f;
            var across = normal * depth * 0.5f;
            return new List<Vector3>
            {
                center - along - across,
                center + along - across,
                center + along + across,
                center - along + across,
            };
        }

        private static bool TryFindNearestRoadSegment(
            Vector3 point, IReadOnlyList<(Vector3 From, Vector3 To)> segments,
            out Vector3 nearestFrom, out Vector3 nearestTo, out float distanceSquared)
        {
            nearestFrom = Vector3.zero;
            nearestTo = Vector3.right;
            distanceSquared = float.PositiveInfinity;
            foreach (var segment in segments)
            {
                var candidate = DistanceToSegmentSquared(point, segment.From, segment.To);
                if (candidate >= distanceSquared) continue;
                distanceSquared = candidate;
                nearestFrom = segment.From;
                nearestTo = segment.To;
            }
            return !float.IsPositiveInfinity(distanceSquared);
        }

        private static void AddInfillBuildingDetail(
            MeshAccumulator roofEquipment, MeshAccumulator entranceGlass, MeshAccumulator entranceFrames,
            Vector3 center, Vector2 size, float height, int style, Vector3 towardJunction)
        {
            var equipmentWidth = Mathf.Clamp(size.x * (0.18f + style * 0.018f), 3.2f, 7.2f);
            var equipmentDepth = Mathf.Clamp(size.y * (0.16f + (style % 3) * 0.025f), 2.8f, 6.5f);
            roofEquipment.AddBox(
                center + new Vector3(size.x * 0.17f, height + 0.7f, -size.y * 0.12f),
                new Vector3(equipmentWidth, 1.35f + style * 0.12f, equipmentDepth));
            if (style is 3 or 4 or 6)
            {
                roofEquipment.AddBox(
                    center + new Vector3(-size.x * 0.18f, height + 0.42f, size.y * 0.14f),
                    new Vector3(Mathf.Clamp(size.x * 0.32f, 5f, 11f), 0.78f, Mathf.Clamp(size.y * 0.22f, 3.5f, 8f)));
            }

            towardJunction.y = 0f;
            if (towardJunction.sqrMagnitude < 0.01f) towardJunction = Vector3.forward;
            towardJunction.Normalize();
            var frontAlongX = Mathf.Abs(towardJunction.x) > Mathf.Abs(towardJunction.z);
            var sign = frontAlongX ? Mathf.Sign(towardJunction.x) : Mathf.Sign(towardJunction.z);
            if (Mathf.Abs(sign) < 0.5f) sign = 1f;
            var front = frontAlongX
                ? center + Vector3.right * sign * (size.x * 0.5f + 0.12f)
                : center + Vector3.forward * sign * (size.y * 0.5f + 0.12f);
            var lobbySize = frontAlongX
                ? new Vector3(0.18f, 3.7f, Mathf.Clamp(size.y * 0.4f, 4.2f, 8.5f))
                : new Vector3(Mathf.Clamp(size.x * 0.4f, 4.2f, 8.5f), 3.7f, 0.18f);
            entranceGlass.AddBox(front + Vector3.up * 2.05f, lobbySize);

            var canopyPosition = front + Vector3.up * 4.15f + towardJunction * 1.25f;
            var canopySize = frontAlongX
                ? new Vector3(2.7f, 0.2f, lobbySize.z + 1.15f)
                : new Vector3(lobbySize.x + 1.15f, 0.2f, 2.7f);
            entranceFrames.AddBox(canopyPosition, canopySize);
            var sideOffset = frontAlongX ? Vector3.forward * lobbySize.z * 0.52f : Vector3.right * lobbySize.x * 0.52f;
            var postSize = frontAlongX ? new Vector3(0.16f, 3.9f, 0.16f) : new Vector3(0.16f, 3.9f, 0.16f);
            entranceFrames.AddBox(front + sideOffset + towardJunction * 1.08f + Vector3.up * 1.95f, postSize);
            entranceFrames.AddBox(front - sideOffset + towardJunction * 1.08f + Vector3.up * 1.95f, postSize);
        }

        private static void AddInfillFacadeBands(
            MeshAccumulator glazing, MeshAccumulator frames, MeshAccumulator accents,
            Vector3 center, Vector2 size,
            float height, int seed, int style, bool simplified)
        {
            var floorHeight = 3.25f + seed % 3 * 0.14f;
            var floors = Mathf.Max(2, Mathf.FloorToInt((height - 4.2f) / floorHeight));

            void AddFace(bool alongX, float sign)
            {
                var span = alongX ? size.x : size.y;
                var normalExtent = alongX ? size.y * 0.5f : size.x * 0.5f;
                var normal = (alongX ? Vector3.forward : Vector3.right) * sign;
                var tangent = alongX ? Vector3.right : Vector3.forward;
                Vector3 At(float along, float y, float depth = 0.08f) =>
                    center + tangent * along + Vector3.up * y + normal * (normalExtent + depth);
                Vector3 FaceSize(float alongSize, float ySize, float depth) => alongX
                    ? new Vector3(alongSize, ySize, depth)
                    : new Vector3(depth, ySize, alongSize);

                // A continuous stone or metal ground floor gives every generated
                // building a believable street-level datum instead of a bare box.
                accents.AddBox(At(0f, 2.05f, 0.11f), FaceSize(span * 0.93f, 3.72f, 0.18f));

                if (style == 4)
                {
                    var curtainHeight = Mathf.Max(4f, height - 5.4f);
                    glazing.AddBox(At(0f, 4.2f + curtainHeight * 0.5f), FaceSize(span * 0.88f, curtainHeight, 0.12f));
                    var columns = Mathf.Max(4, Mathf.FloorToInt(span / (simplified ? 5.2f : 3.2f)));
                    for (var column = 0; column <= columns; column++)
                    {
                        var along = -span * 0.44f + span * 0.88f * column / columns;
                        frames.AddBox(At(along, 4.2f + curtainHeight * 0.5f, 0.14f), FaceSize(0.11f, curtainHeight, 0.17f));
                    }
                    for (var floor = simplified ? 2 : 1; floor < floors; floor += simplified ? 2 : 1)
                        frames.AddBox(At(0f, 4.2f + floor * floorHeight, 0.14f), FaceSize(span * 0.9f, 0.1f, 0.17f));
                    accents.AddBox(At(-span * 0.455f, height * 0.53f, 0.16f), FaceSize(span * 0.055f, height - 2.1f, 0.24f));
                    accents.AddBox(At(span * 0.455f, height * 0.53f, 0.16f), FaceSize(span * 0.055f, height - 2.1f, 0.24f));
                    return;
                }

                var modules = Mathf.Max(3, Mathf.FloorToInt(span /
                    (simplified ? 5.2f : style == 5 ? 2.8f : 3.5f)));
                var moduleWidth = span / modules;
                for (var floor = 0; floor < floors; floor += simplified ? 2 : 1)
                {
                    var y = 4.7f + floor * floorHeight;
                    if (y + 1f >= height) break;
                    if (style is 3 or 6)
                    {
                        var bandWidth = style == 3 ? span * 0.9f : span * 0.78f;
                        glazing.AddBox(At(0f, y), FaceSize(bandWidth, style == 3 ? 1.62f : 1.34f, 0.12f));
                        frames.AddBox(At(0f, y - 1.05f, 0.14f), FaceSize(span * 0.92f, style == 6 ? 0.28f : 0.13f, 0.18f));
                        if (style == 6 && floor % 2 == 1)
                            frames.AddBox(At(0f, y - 1.3f, 0.72f), FaceSize(span * 0.84f, 0.16f, 1.35f));
                        continue;
                    }

                    for (var module = 0; module < modules; module++)
                    {
                        if (style == 2 && (module + floor + seed) % 4 == 0) continue;
                        var along = -span * 0.5f + moduleWidth * (module + 0.5f);
                        var width = style == 5 ? moduleWidth * 0.48f : moduleWidth * 0.62f;
                        glazing.AddBox(At(along, y), FaceSize(width, style == 5 ? 1.82f : 1.55f, 0.12f));
                        if (style == 5)
                            frames.AddBox(At(along + width * 0.62f, y, 0.18f), FaceSize(0.14f, 2.15f, 0.2f));
                    }
                    if (style == 2 && floor % 2 == 1)
                        frames.AddBox(At(0f, y - 1.18f, 0.62f), FaceSize(span * 0.82f, 0.15f, 1.18f));
                }

                switch (style)
                {
                    case 1:
                        accents.AddBox(At(-span * 0.34f, height * 0.54f, 0.16f), FaceSize(0.32f, height - 4.4f, 0.24f));
                        accents.AddBox(At(span * 0.34f, height * 0.54f, 0.16f), FaceSize(0.32f, height - 4.4f, 0.24f));
                        break;
                    case 2:
                        var baySign = (seed & 1) == 0 ? -1f : 1f;
                        accents.AddBox(At(baySign * span * 0.34f, height * 0.55f, 0.17f), FaceSize(span * 0.13f, height - 4.2f, 0.25f));
                        break;
                    case 3:
                        for (var floor = 2; floor < floors; floor += 2)
                            accents.AddBox(At(0f, 4.1f + floor * floorHeight, 0.18f), FaceSize(span * 0.94f, 0.28f, 0.34f));
                        break;
                    case 5:
                        accents.AddBox(At(0f, height * 0.55f, 0.17f), FaceSize(span * 0.15f, height - 4f, 0.25f));
                        break;
                    case 6:
                        accents.AddBox(At(0f, 7.2f, 0.18f), FaceSize(span * 0.96f, 0.48f, 0.34f));
                        accents.AddBox(At(0f, height - 1.05f, 0.18f), FaceSize(span * 0.9f, 0.64f, 0.34f));
                        break;
                }
            }

            AddFace(true, 1f);
            AddFace(false, -1f);
            if (!simplified)
            {
                AddFace(true, -1f);
                AddFace(false, 1f);
            }
            frames.AddBox(center + new Vector3(0f, height + 0.24f, size.y * 0.5f), new Vector3(size.x + 0.32f, 0.48f, 0.32f));
            frames.AddBox(center + new Vector3(0f, height + 0.24f, -size.y * 0.5f), new Vector3(size.x + 0.32f, 0.48f, 0.32f));
            frames.AddBox(center + new Vector3(size.x * 0.5f, height + 0.24f, 0f), new Vector3(0.32f, 0.48f, size.y));
            frames.AddBox(center + new Vector3(-size.x * 0.5f, height + 0.24f, 0f), new Vector3(0.32f, 0.48f, size.y));
        }

        private static bool IsNearRoad(
            Vector3 point, float clearance, IReadOnlyList<(Vector3 From, Vector3 To)> segments)
        {
            var limit = clearance * clearance;
            foreach (var segment in segments)
            {
                if (Mathf.Abs(segment.From.x - point.x) > clearance + Mathf.Abs(segment.To.x - segment.From.x) &&
                    Mathf.Abs(segment.From.z - point.z) > clearance + Mathf.Abs(segment.To.z - segment.From.z)) continue;
                if (DistanceToSegmentSquared(point, segment.From, segment.To) < limit) return true;
            }
            return false;
        }

        private static float DistanceToSegmentSquared(Vector3 point, Vector3 from, Vector3 to)
        {
            return Vector3.SqrMagnitude(
                Vector3.ProjectOnPlane(point, Vector3.up) - ClosestPointOnSegment(point, from, to));
        }

        private static Vector3 ClosestPointOnSegment(Vector3 point, Vector3 from, Vector3 to)
        {
            point.y = from.y = to.y = 0f;
            var segment = to - from;
            if (segment.sqrMagnitude < 0.001f) return from;
            var amount = Mathf.Clamp01(Vector3.Dot(point - from, segment) / segment.sqrMagnitude);
            return from + segment * amount;
        }

        private static void CreateProceduralFacadeModules(
            SceneBuilder scene, Transform parent, Vector3 center, Vector2 size, float height, int materialIndex)
        {
            var frame = new MeshAccumulator();
            var reveals = new MeshAccumulator();
            var coolGlazing = new MeshAccumulator();
            var warmGlazing = new MeshAccumulator();
            var solidPanels = new MeshAccumulator();
            var balconyGlass = new MeshAccumulator();
            const float floorHeight = 3.45f;
            const float moduleWidth = 3.45f;
            const float groundFloorHeight = 4.35f;
            var upperFloors = Mathf.Max(2, Mathf.FloorToInt((height - groundFloorHeight - 0.5f) / floorHeight));

            void AddElevation(bool alongX, float fixedOffset, float span, float facingSign)
            {
                var modules = Mathf.Max(3, Mathf.FloorToInt(span / moduleWidth));
                var resolvedWidth = span / modules;
                var surfaceOffset = facingSign * 0.16f;

                for (var index = 0; index < modules; index++)
                {
                    var along = -span * 0.5f + resolvedWidth * (index + 0.5f);
                    var groundPosition = alongX
                        ? center + new Vector3(along, groundFloorHeight * 0.5f, fixedOffset + surfaceOffset)
                        : center + new Vector3(fixedOffset + surfaceOffset, groundFloorHeight * 0.5f, along);
                    var groundWindow = alongX
                        ? new Vector3(resolvedWidth * 0.76f, groundFloorHeight * 0.7f, 0.12f)
                        : new Vector3(0.12f, groundFloorHeight * 0.7f, resolvedWidth * 0.76f);
                    var groundReveal = alongX
                        ? new Vector3(groundWindow.x + 0.32f, groundWindow.y + 0.28f, 0.18f)
                        : new Vector3(0.18f, groundWindow.y + 0.28f, groundWindow.z + 0.32f);
                    reveals.AddBox(groundPosition - (alongX ? Vector3.forward : Vector3.right) * facingSign * 0.045f, groundReveal);
                    (index % 11 == materialIndex % 11 ? warmGlazing : coolGlazing).AddBox(groundPosition, groundWindow);
                }

                for (var floor = 0; floor < upperFloors; floor++)
                {
                    var floorBase = groundFloorHeight + floor * floorHeight;
                    for (var index = 0; index < modules; index++)
                    {
                        var along = -span * 0.5f + resolvedWidth * (index + 0.5f);
                        var position = alongX
                            ? center + new Vector3(along, floorBase + floorHeight * 0.52f, fixedOffset + surfaceOffset)
                            : center + new Vector3(fixedOffset + surfaceOffset, floorBase + floorHeight * 0.52f, along);
                        var solid = (index + floor * 2 + materialIndex) % 17 == 0;
                        var widthRatio = materialIndex % 3 == 0 ? 0.68f : materialIndex % 3 == 1 ? 0.59f : 0.64f;
                        var heightRatio = materialIndex % 3 == 0 ? 0.49f : materialIndex % 3 == 1 ? 0.56f : 0.53f;
                        var windowSize = alongX
                            ? new Vector3(resolvedWidth * widthRatio, floorHeight * heightRatio, 0.12f)
                            : new Vector3(0.12f, floorHeight * heightRatio, resolvedWidth * widthRatio);
                        if (solid)
                        {
                            var panelSize = alongX
                                ? new Vector3(resolvedWidth * 0.82f, floorHeight * 0.76f, 0.22f)
                                : new Vector3(0.22f, floorHeight * 0.76f, resolvedWidth * 0.82f);
                            solidPanels.AddBox(position, panelSize);
                        }
                        else
                        {
                            var revealSize = alongX
                                ? new Vector3(windowSize.x + 0.3f, windowSize.y + 0.28f, 0.18f)
                                : new Vector3(0.18f, windowSize.y + 0.28f, windowSize.z + 0.3f);
                            reveals.AddBox(position - (alongX ? Vector3.forward : Vector3.right) * facingSign * 0.045f, revealSize);
                            if ((index * 7 + floor * 5 + materialIndex) % 29 == 0) warmGlazing.AddBox(position, windowSize);
                            else coolGlazing.AddBox(position, windowSize);
                        }

                        if (!solid)
                        {
                            var sillPosition = position - Vector3.up * (windowSize.y * 0.5f + 0.08f);
                            var sillSize = alongX
                                ? new Vector3(windowSize.x + 0.24f, 0.12f, 0.4f)
                                : new Vector3(0.4f, 0.12f, windowSize.z + 0.24f);
                            frame.AddBox(sillPosition, sillSize);
                            if ((materialIndex + index + floor) % 3 == 0)
                            {
                                var shadePosition = position + Vector3.up * (windowSize.y * 0.5f + 0.14f);
                                var shadeSize = alongX
                                    ? new Vector3(windowSize.x + 0.28f, 0.1f, 0.78f)
                                    : new Vector3(0.78f, 0.1f, windowSize.z + 0.28f);
                                frame.AddBox(shadePosition, shadeSize);
                            }
                        }
                    }

                    var bandCenter = alongX
                        ? center + new Vector3(0f, floorBase, fixedOffset + facingSign * 0.16f)
                        : center + new Vector3(fixedOffset + facingSign * 0.16f, floorBase, 0f);
                    var bandSize = alongX
                        ? new Vector3(span, 0.14f, 0.36f)
                        : new Vector3(0.36f, 0.14f, span);
                    if (floor == 0 || floor == upperFloors - 1 || floor % 2 == materialIndex % 2)
                        frame.AddBox(bandCenter, bandSize);

                    if (facingSign > 0f && materialIndex % 3 == 1 && floor > 0 && floor % 2 == 1)
                    {
                        var slabPosition = alongX
                            ? center + new Vector3(0f, floorBase + 0.12f, fixedOffset + facingSign * 0.62f)
                            : center + new Vector3(fixedOffset + facingSign * 0.62f, floorBase + 0.12f, 0f);
                        var slabSize = alongX
                            ? new Vector3(span * 0.86f, 0.16f, 1.25f)
                            : new Vector3(1.25f, 0.16f, span * 0.86f);
                        frame.AddBox(slabPosition, slabSize);
                        var railPosition = slabPosition + Vector3.up * 0.58f +
                                           (alongX ? Vector3.forward : Vector3.right) * facingSign * 0.55f;
                        var railSize = alongX
                            ? new Vector3(span * 0.84f, 0.92f, 0.07f)
                            : new Vector3(0.07f, 0.92f, span * 0.84f);
                        balconyGlass.AddBox(railPosition, railSize);
                    }
                }

                for (var index = 0; index <= modules; index += 3)
                {
                    var along = -span * 0.5f + resolvedWidth * index;
                    var position = alongX
                        ? center + new Vector3(along, groundFloorHeight + (height - groundFloorHeight) * 0.5f, fixedOffset + facingSign * 0.26f)
                        : center + new Vector3(fixedOffset + facingSign * 0.26f, groundFloorHeight + (height - groundFloorHeight) * 0.5f, along);
                    var finSize = alongX
                        ? new Vector3(0.16f, height - groundFloorHeight - 0.5f, 0.58f)
                        : new Vector3(0.58f, height - groundFloorHeight - 0.5f, 0.16f);
                    frame.AddBox(position, finSize);
                }

                foreach (var pier in new[] { -0.34f, 0.34f })
                {
                    var pierPosition = alongX
                        ? center + new Vector3(span * pier, groundFloorHeight + (height - groundFloorHeight) * 0.5f, fixedOffset + facingSign * 0.24f)
                        : center + new Vector3(fixedOffset + facingSign * 0.24f, groundFloorHeight + (height - groundFloorHeight) * 0.5f, span * pier);
                    var pierSize = alongX
                        ? new Vector3(0.46f, height - groundFloorHeight - 0.35f, 0.52f)
                        : new Vector3(0.52f, height - groundFloorHeight - 0.35f, 0.46f);
                    solidPanels.AddBox(pierPosition, pierSize);
                }

                if (facingSign > 0f && upperFloors >= 4)
                {
                    var featureWidth = Mathf.Min(span * 0.42f, 13.5f);
                    var featureHeight = Mathf.Min((height - groundFloorHeight) * 0.62f, 12.5f);
                    var featureCenterY = groundFloorHeight + featureHeight * 0.5f + floorHeight * 0.45f;
                    var featureDepth = 0.82f;
                    var featureNormal = (alongX ? Vector3.forward : Vector3.right) * facingSign;
                    var featureCenter = alongX
                        ? center + new Vector3(0f, featureCenterY, fixedOffset) + featureNormal * 0.48f
                        : center + new Vector3(fixedOffset, featureCenterY, 0f) + featureNormal * 0.48f;
                    var sideSize = alongX
                        ? new Vector3(0.24f, featureHeight, featureDepth)
                        : new Vector3(featureDepth, featureHeight, 0.24f);
                    var capSize = alongX
                        ? new Vector3(featureWidth, 0.24f, featureDepth)
                        : new Vector3(featureDepth, 0.24f, featureWidth);
                    var sideDirection = alongX ? Vector3.right : Vector3.forward;
                    frame.AddBox(featureCenter - sideDirection * featureWidth * 0.5f, sideSize);
                    frame.AddBox(featureCenter + sideDirection * featureWidth * 0.5f, sideSize);
                    frame.AddBox(featureCenter - Vector3.up * featureHeight * 0.5f, capSize);
                    frame.AddBox(featureCenter + Vector3.up * featureHeight * 0.5f, capSize);
                }

                var crownCenter = alongX
                    ? center + new Vector3(0f, height - 0.45f, fixedOffset + facingSign * 0.23f)
                    : center + new Vector3(fixedOffset + facingSign * 0.23f, height - 0.45f, 0f);
                var crownSize = alongX
                    ? new Vector3(span, 0.72f, 0.42f)
                    : new Vector3(0.42f, 0.72f, span);
                frame.AddBox(crownCenter, crownSize);
            }

            AddElevation(true, size.y * 0.5f, size.x, 1f);
            AddElevation(true, -size.y * 0.5f, size.x, -1f);
            AddElevation(false, size.x * 0.5f, size.y, 1f);
            AddElevation(false, -size.x * 0.5f, size.y, -1f);
            frame.Build("实体建筑深窗框、遮阳、阳台与檐口", scene.Materials.FacadeFrame, parent);
            reveals.Build("实体建筑窗洞暗部", scene.Materials.FacadeFrame, parent);
            coolGlazing.Build("实体冷色反射窗单元", scene.Materials.BuildingGlass, parent);
            warmGlazing.Build("实体暖色反射窗单元", scene.Materials.BuildingGlassWarm, parent);
            balconyGlass.Build("实体阳台玻璃栏板", scene.Materials.BuildingGlass, parent, false);
            solidPanels.Build("实体立面错落实墙板", scene.Materials.Facades[(materialIndex + 2) % scene.Materials.Facades.Count], parent);
        }

        private static void CreateDistinctFacadeModules(
            SceneBuilder scene, Transform parent, Vector3 center, Vector2 size,
            float height, int materialIndex, int style)
        {
            var glass = new MeshAccumulator();
            var warmGlass = new MeshAccumulator();
            var frame = new MeshAccumulator();
            var accent = new MeshAccumulator();
            var balcony = new MeshAccumulator();

            void AddFace(bool alongX, float sign)
            {
                var span = alongX ? size.x : size.y;
                var normalExtent = alongX ? size.y * 0.5f : size.x * 0.5f;
                var normal = (alongX ? Vector3.forward : Vector3.right) * sign;
                var tangent = alongX ? Vector3.right : Vector3.forward;
                Vector3 At(float along, float y, float depth = 0.12f) =>
                    center + tangent * along + Vector3.up * y + normal * (normalExtent + depth);
                Vector3 FaceSize(float alongSize, float ySize, float depth) => alongX
                    ? new Vector3(alongSize, ySize, depth)
                    : new Vector3(depth, ySize, alongSize);

                if (style == 4)
                {
                    var curtainHeight = Mathf.Max(4f, height - 5.2f);
                    glass.AddBox(At(0f, 3.8f + curtainHeight * 0.5f), FaceSize(span * 0.92f, curtainHeight, 0.13f));
                    var modules = Mathf.Max(4, Mathf.FloorToInt(span / 3.1f));
                    for (var module = 0; module <= modules; module++)
                    {
                        var along = -span * 0.46f + span * 0.92f * module / modules;
                        frame.AddBox(At(along, 3.8f + curtainHeight * 0.5f, 0.2f), FaceSize(0.095f, curtainHeight + 0.25f, 0.22f));
                    }
                    for (var y = 4.2f; y < height - 0.8f; y += 3.45f)
                        frame.AddBox(At(0f, y, 0.2f), FaceSize(span * 0.94f, 0.11f, 0.23f));
                    accent.AddBox(At(0f, 1.9f, 0.16f), FaceSize(span * 0.96f, 3.7f, 0.28f));
                }
                else if (style == 5)
                {
                    const float floorHeight = 3.25f;
                    var modules = Mathf.Max(3, Mathf.FloorToInt(span / 3.35f));
                    var moduleWidth = span / modules;
                    var floors = Mathf.Max(2, Mathf.FloorToInt((height - 3.8f) / floorHeight));
                    for (var floor = 0; floor < floors; floor++)
                    {
                        var y = 4.25f + floor * floorHeight;
                        for (var module = 0; module < modules; module++)
                        {
                            var along = -span * 0.5f + moduleWidth * (module + 0.5f);
                            var target = (module + floor + materialIndex) % 7 == 0 ? warmGlass : glass;
                            target.AddBox(At(along, y), FaceSize(moduleWidth * 0.56f, 1.62f, 0.13f));
                        }
                        frame.AddBox(At(0f, y - 1.08f, 0.18f), FaceSize(span * 0.94f, 0.16f, 0.22f));
                        if (sign > 0f && floor % 2 == 1)
                        {
                            balcony.AddBox(At(0f, y - 1.2f, 0.82f), FaceSize(span * 0.82f, 0.16f, 1.55f));
                            glass.AddBox(At(0f, y - 0.66f, 1.56f), FaceSize(span * 0.78f, 0.92f, 0.07f));
                        }
                    }
                    accent.AddBox(At(0f, 1.85f, 0.14f), FaceSize(span * 0.9f, 3.5f, 0.24f));
                }
                else
                {
                    for (var y = 4.8f; y < height - 1.8f; y += 4.4f)
                    {
                        glass.AddBox(At(0f, y), FaceSize(span * 0.9f, 2.15f, 0.13f));
                        accent.AddBox(At(0f, y - 1.3f, 0.18f), FaceSize(span, 0.42f, 0.28f));
                    }
                    for (var along = -span * 0.4f; along <= span * 0.4f; along += Mathf.Max(4.2f, span / 5f))
                        frame.AddBox(At(along, height * 0.53f, 0.32f), FaceSize(0.22f, height * 0.82f, 0.54f));
                    accent.AddBox(At(0f, height - 0.78f, 0.22f), FaceSize(span + 0.4f, 1.05f, 0.38f));
                }
            }

            AddFace(true, 1f);
            AddFace(true, -1f);
            AddFace(false, 1f);
            AddFace(false, -1f);
            glass.Build("差异化建筑冷色玻璃", scene.Materials.BuildingGlass, parent, false);
            warmGlass.Build("住宅少量暖色窗", scene.Materials.BuildingGlassWarm, parent, false);
            frame.Build("差异化建筑幕墙框架", scene.Materials.FacadeFrame, parent);
            accent.Build("差异化建筑实体横带与基座", scene.Materials.Facades[(materialIndex + 3) % scene.Materials.Facades.Count], parent);
            balcony.Build("住宅实体阳台板", scene.Materials.Curb, parent);
        }

        private static void CreateBuildingStreetDetail(
            SceneBuilder scene, Transform parent, Vector3 center, Vector2 size, float height, int materialIndex, Vector3 towardRoad)
        {
            var frontAlongX = Mathf.Abs(towardRoad.x) > Mathf.Abs(towardRoad.z);
            var frontSign = frontAlongX ? Mathf.Sign(towardRoad.x) : Mathf.Sign(towardRoad.z);
            if (Mathf.Abs(frontSign) < 0.5f) frontSign = 1f;
            var outward = frontAlongX ? Vector3.right * frontSign : Vector3.forward * frontSign;
            var lateral = frontAlongX ? Vector3.forward : Vector3.right;
            var frontExtent = frontAlongX ? size.x * 0.5f : size.y * 0.5f;
            var facadeSpan = frontAlongX ? size.y : size.x;
            Vector3 At(float across, float y, float depth) => center + lateral * across + Vector3.up * y + outward * (frontExtent + depth);
            Vector3 BoxSize(float across, float y, float depth) => frontAlongX
                ? new Vector3(depth, y, across)
                : new Vector3(across, y, depth);

            var podium = new MeshAccumulator();
            podium.AddBox(At(0f, 2.05f, 0.62f), BoxSize(facadeSpan * 0.86f, 4.1f, 1.24f));
            podium.AddBox(At(-facadeSpan * 0.34f, 3.05f, 0.9f), BoxSize(facadeSpan * 0.13f, 6.1f, 1.8f));
            podium.AddBox(At(facadeSpan * 0.34f, 3.05f, 0.9f), BoxSize(facadeSpan * 0.13f, 6.1f, 1.8f));
            podium.Build("代表性建筑入口基座", scene.Materials.Facades[(materialIndex + 1) % scene.Materials.Facades.Count], parent);

            var canopy = new MeshAccumulator();
            canopy.AddBox(At(0f, 4.65f, 2.25f), BoxSize(facadeSpan * 0.56f, 0.28f, 4.5f));
            canopy.AddBox(At(-facadeSpan * 0.23f, 2.28f, 3.85f), BoxSize(0.28f, 4.56f, 0.28f));
            canopy.AddBox(At(facadeSpan * 0.23f, 2.28f, 3.85f), BoxSize(0.28f, 4.56f, 0.28f));
            canopy.Build("代表性建筑入口雨棚", scene.Materials.Metal, parent);

            var lobby = new MeshAccumulator();
            lobby.AddBox(At(0f, 2.18f, 1.32f), BoxSize(facadeSpan * 0.46f, 3.62f, 0.16f));
            var doorFrames = new MeshAccumulator();
            for (var mullion = -2; mullion <= 2; mullion++)
                doorFrames.AddBox(At(facadeSpan * 0.095f * mullion, 2.18f, 1.46f), BoxSize(0.08f, 3.68f, 0.14f));
            lobby.Build("代表性建筑通高玻璃门厅", scene.Materials.BuildingGlass, parent, false);
            doorFrames.Build("代表性建筑门厅细框", scene.Materials.FacadeFrame, parent);

            var roofPlant = new MeshAccumulator();
            roofPlant.AddBox(center + new Vector3(size.x * 0.18f, height + 1.15f, 0f), new Vector3(5.2f, 2.3f, 3.8f));
            roofPlant.AddBox(center + new Vector3(-size.x * 0.16f, height + 0.72f, 0f), new Vector3(size.x * 0.28f, 1.35f, size.y * 0.32f));
            roofPlant.Build("代表性建筑屋顶机房", scene.Materials.BuildingRoof, parent);

            var roofScreen = new MeshAccumulator();
            var screenSpan = Mathf.Min(facadeSpan * 0.62f, 23f);
            for (var index = -3; index <= 3; index++)
                roofScreen.AddBox(center + lateral * (screenSpan * index / 7f) + Vector3.up * (height + 1.35f), BoxSize(0.12f, 2.3f, 0.34f));
            roofScreen.AddBox(center + Vector3.up * (height + 2.46f), BoxSize(screenSpan, 0.15f, 0.34f));
            roofScreen.AddBox(center + Vector3.up * (height + 0.24f), BoxSize(screenSpan, 0.15f, 0.34f));
            roofScreen.Build("代表性建筑屋顶实体格栅轮廓", scene.Materials.Metal, parent);
        }

        private static void CreateShowcaseCornerLandscaping(SceneBuilder scene, Transform parent, Vector3 center)
        {
            var paving = new MeshAccumulator();
            var pocketGreen = new MeshAccumulator();
            var planterEdges = new MeshAccumulator();
            var shrubMasses = new MeshAccumulator();
            foreach (var offset in new[]
                     {
                         new Vector3(-43f, 0f, -44f), new Vector3(43f, 0f, -44f),
                         new Vector3(-43f, 0f, 44f), new Vector3(43f, 0f, 44f),
                     })
            {
                paving.AddPolygon(Rectangle(center + offset, 57f, 58f), 0.082f);
                pocketGreen.AddPolygon(Rectangle(center + offset, 51f, 51f), 0.094f);
                var signX = Mathf.Sign(offset.x);
                var signZ = Mathf.Sign(offset.z);
                planterEdges.AddBox(center + offset + new Vector3(-signX * 21f, 0.17f, 0f), new Vector3(0.44f, 0.34f, 34f));
                planterEdges.AddBox(center + offset + new Vector3(0f, 0.17f, -signZ * 21f), new Vector3(34f, 0.34f, 0.44f));
                for (var segment = -3; segment <= 3; segment++)
                {
                    var heightVariation = 0.68f + (segment + 3) % 3 * 0.08f;
                    shrubMasses.AddEllipsoid(
                        center + offset + new Vector3(-signX * 19.5f, heightVariation, segment * 5.15f),
                        new Vector3(1.05f, heightVariation, 1.35f), 12, 18);
                    shrubMasses.AddEllipsoid(
                        center + offset + new Vector3(segment * 5.15f, heightVariation, -signZ * 19.5f),
                        new Vector3(1.35f, heightVariation, 1.05f), 12, 18);
                }
            }
            paving.Build("Showcase corner paving", scene.Materials.HeroSidewalk, parent, false);
            pocketGreen.Build("Showcase corner planting", scene.Materials.HeroGrass, parent, false);
            planterEdges.Build("Showcase stone planter edges", scene.Materials.Curb, parent);
            shrubMasses.Build("Showcase clipped evergreen hedge masses", scene.Materials.ShrubLeaves, parent);
        }

        private static List<Vector3> Rectangle(Vector3 center, float width, float depth)
        {
            return new List<Vector3>
            {
                center + new Vector3(-width * 0.5f, 0f, -depth * 0.5f),
                center + new Vector3(width * 0.5f, 0f, -depth * 0.5f),
                center + new Vector3(width * 0.5f, 0f, depth * 0.5f),
                center + new Vector3(-width * 0.5f, 0f, depth * 0.5f),
            };
        }

        private static void CreateFormalForegroundAssets(SceneBuilder scene, Vector3 center)
        {
            var lampSource = Resources.Load<GameObject>("Art/Models/street_lamp_01/street_lamp_01_1k");
            var treeSource = Resources.Load<GameObject>("Art/Models/island_tree_02/island_tree_02_1k");
            var offsets = new List<Vector3>();
            for (var distance = 38f; distance <= 104f; distance += 22f)
            {
                offsets.Add(new Vector3(-22f, 0f, -distance));
                offsets.Add(new Vector3(22f, 0f, -distance));
                offsets.Add(new Vector3(-22f, 0f, distance));
                offsets.Add(new Vector3(22f, 0f, distance));
                offsets.Add(new Vector3(-distance, 0f, -22f));
                offsets.Add(new Vector3(-distance, 0f, 22f));
                offsets.Add(new Vector3(distance, 0f, -22f));
                offsets.Add(new Vector3(distance, 0f, 22f));
            }
            offsets.AddRange(new[]
            {
                new Vector3(-47f, 0f, -51f), new Vector3(-36f, 0f, -55f),
                new Vector3(47f, 0f, -51f), new Vector3(36f, 0f, -55f),
                new Vector3(-49f, 0f, 48f), new Vector3(-37f, 0f, 54f),
            });
            offsets = offsets.Where(offset => !(offset.x > 0f && offset.z > 0f)).ToList();
            var treeIndex = 0;
            foreach (var offset in offsets.Distinct())
            {
                var seed = StableHash(offset.ToString());
                var height = 10.6f + seed % 17 * 0.15f;
                CreateBoulevardTree(scene, center + offset, height, seed);
                if (treeSource != null && treeIndex++ % 3 == 0)
                    CreatePbrBoulevardTree(
                        scene, treeSource,
                        center + offset + new Vector3(0.85f, 0f, -0.55f),
                        height * 0.92f, seed);
            }
            if (lampSource != null)
            {
                var lampOffsets = new List<Vector3>();
                foreach (var distance in new[] { 34f, 70f, 104f })
                {
                    lampOffsets.Add(new Vector3(-18f, 0f, -distance));
                    lampOffsets.Add(new Vector3(18f, 0f, -distance));
                    lampOffsets.Add(new Vector3(-18f, 0f, distance));
                    lampOffsets.Add(new Vector3(18f, 0f, distance));
                    lampOffsets.Add(new Vector3(-distance, 0f, -18f));
                    lampOffsets.Add(new Vector3(-distance, 0f, 18f));
                    lampOffsets.Add(new Vector3(distance, 0f, -18f));
                    lampOffsets.Add(new Vector3(distance, 0f, 18f));
                }
                foreach (var offset in lampOffsets)
                {
                    var lamp = Object.Instantiate(lampSource, center + offset, Quaternion.identity, scene.transform);
                    lamp.name = "CC0正式城市路灯";
                    var bounds = CalculateBounds(lamp);
                    var scale = bounds.size.y > 0.01f ? 9.2f / bounds.size.y : 1f;
                    lamp.transform.localScale = Vector3.one * scale;
                    ApplyLampMaterials(lamp, scene);
                }
            }
        }

        private static void CreatePbrBoulevardTree(
            SceneBuilder scene, GameObject source, Vector3 position, float targetHeight, int seed)
        {
            var tree = Object.Instantiate(source, position, Quaternion.Euler(0f, seed % 360, 0f), scene.transform);
            tree.name = "CC0 高精度三维行道树";
            var bounds = CalculateBounds(tree);
            var scale = targetHeight / Mathf.Max(0.01f, bounds.size.y);
            tree.transform.localScale = Vector3.one * scale;
            bounds = CalculateBounds(tree);
            tree.transform.position += Vector3.up * (position.y - bounds.min.y);
            ApplyTreeMaterials(tree, scene);
        }

        private static void CreateBoulevardTree(SceneBuilder scene, Vector3 position, float height, int seed)
        {
            var random = new System.Random(seed);
            var root = new GameObject("程序化高精度三维行道树");
            root.transform.SetParent(scene.transform, false);
            var wood = new MeshAccumulator();
            var foliage = new MeshAccumulator();
            var trunkRadius = height * (0.022f + (float)random.NextDouble() * 0.006f);
            var trunkTop = position + Vector3.up * height * 0.58f;
            wood.AddCylinderBetween(position + Vector3.up * 0.03f, trunkTop, trunkRadius, 14);

            const int branchCount = 13;
            for (var branch = 0; branch < branchCount; branch++)
            {
                var angle = branch * Mathf.PI * 2f / branchCount + (float)random.NextDouble() * 0.42f;
                var start = position + Vector3.up * height * (0.31f + branch % 6 * 0.045f);
                var reach = height * (0.17f + (float)random.NextDouble() * 0.095f);
                var end = position + new Vector3(Mathf.Cos(angle) * reach, height * (0.64f + (float)random.NextDouble() * 0.25f), Mathf.Sin(angle) * reach);
                wood.AddCylinderBetween(start, end, trunkRadius * (0.38f + (float)random.NextDouble() * 0.18f), 9);

                for (var twig = 0; twig < 2; twig++)
                {
                    var twigAngle = angle + (twig == 0 ? -0.55f : 0.55f) + ((float)random.NextDouble() - 0.5f) * 0.3f;
                    var twigStart = Vector3.Lerp(start, end, 0.58f + twig * 0.12f);
                    var twigTip = end + new Vector3(
                        Mathf.Cos(twigAngle) * height * (0.065f + (float)random.NextDouble() * 0.045f),
                        height * (0.025f + (float)random.NextDouble() * 0.055f),
                        Mathf.Sin(twigAngle) * height * (0.065f + (float)random.NextDouble() * 0.045f));
                    wood.AddCylinderBetween(twigStart, twigTip, trunkRadius * 0.24f, 7);
                    AddFoliageCluster(foliage, twigTip, height * (0.115f + (float)random.NextDouble() * 0.035f), random);
                }
                AddFoliageCluster(foliage, end, height * (0.14f + (float)random.NextDouble() * 0.04f), random);
            }

            for (var cluster = 0; cluster < 12; cluster++)
            {
                var angle = cluster * Mathf.PI * 0.77f + (float)random.NextDouble();
                var radius = height * (0.045f + (float)random.NextDouble() * 0.1f);
                var clusterCenter = position + new Vector3(
                    Mathf.Cos(angle) * radius,
                    height * (0.63f + (float)random.NextDouble() * 0.31f),
                    Mathf.Sin(angle) * radius);
                AddFoliageCluster(foliage, clusterCenter, height * (0.13f + (float)random.NextDouble() * 0.045f), random);
            }

            wood.Build($"行道树树干与分枝-{seed}", scene.Materials.PbrTreeBranches, root.transform);
            foliage.Build($"行道树多向叶簇-{seed}", scene.Materials.PbrTreeLeaves, root.transform);
        }

        private static void AddFoliageCluster(MeshAccumulator foliage, Vector3 center, float size, System.Random random)
        {
            center += new Vector3(
                ((float)random.NextDouble() - 0.5f) * size * 0.35f,
                ((float)random.NextDouble() - 0.5f) * size * 0.22f,
                ((float)random.NextDouble() - 0.5f) * size * 0.35f);
            for (var plane = 0; plane < 4; plane++)
            {
                var yaw = plane * Mathf.PI * 0.25f + (float)random.NextDouble() * 0.42f;
                var right = new Vector3(Mathf.Cos(yaw), 0f, Mathf.Sin(yaw));
                var up = (Vector3.up + new Vector3(-right.z, 0f, right.x) * (((float)random.NextDouble() - 0.5f) * 0.24f)).normalized;
                var halfWidth = size * (0.48f + (float)random.NextDouble() * 0.16f);
                var halfHeight = size * (0.34f + (float)random.NextDouble() * 0.13f);
                foliage.AddQuad(
                    center - right * halfWidth - up * halfHeight,
                    center + right * halfWidth - up * halfHeight,
                    center + right * halfWidth + up * halfHeight,
                    center - right * halfWidth + up * halfHeight);
            }
        }

        private static void CreateShowcaseStreetFurniture(SceneBuilder scene, Vector3 center)
        {
            foreach (var (offset, yaw) in new[]
                     {
                         (new Vector3(-31f, 0f, -71f), 0f),
                         (new Vector3(-68f, 0f, 31f), 90f),
                         (new Vector3(72f, 0f, -31f), -90f),
                     }) CreateBusShelter(scene, center + offset, yaw);

            foreach (var (offset, yaw) in new[]
                     {
                         (new Vector3(-28f, 0f, -29f), 0f),
                         (new Vector3(28f, 0f, 29f), 180f),
                         (new Vector3(-29f, 0f, 28f), 90f),
                         (new Vector3(29f, 0f, -28f), -90f),
                     }) CreateWayfindingSign(scene, center + offset, yaw);

            foreach (var (offset, yaw) in new[]
                     {
                         (new Vector3(-38f, 0f, -42f), 90f),
                         (new Vector3(38f, 0f, -42f), 90f),
                         (new Vector3(-42f, 0f, 38f), 0f),
                         (new Vector3(42f, 0f, 38f), 0f),
                     }) CreateUrbanBench(scene, center + offset, yaw);

            foreach (var offset in new[]
                     {
                         new Vector3(-31f, 0f, -26f), new Vector3(-31f, 0f, -22f),
                         new Vector3(31f, 0f, 26f), new Vector3(31f, 0f, 22f),
                         new Vector3(-26f, 0f, 31f), new Vector3(-22f, 0f, 31f),
                         new Vector3(26f, 0f, -31f), new Vector3(22f, 0f, -31f),
                     }) CreateBollard(scene, center + offset);
        }

        private static void CreateUrbanBench(SceneBuilder scene, Vector3 position, float yaw)
        {
            var root = new GameObject("实体城市座椅");
            root.transform.SetParent(scene.transform, false);
            root.transform.SetPositionAndRotation(position, Quaternion.Euler(0f, yaw, 0f));
            for (var slat = -2; slat <= 2; slat++)
                CreatePrimitive(PrimitiveType.Cube, "座椅木质条板", root.transform,
                    new Vector3(0f, 0.54f, slat * 0.13f), new Vector3(2.2f, 0.065f, 0.1f), scene.Materials.TreeBark);
            foreach (var x in new[] { -0.82f, 0.82f })
                CreatePrimitive(PrimitiveType.Cube, "座椅金属支脚", root.transform,
                    new Vector3(x, 0.28f, 0f), new Vector3(0.09f, 0.52f, 0.52f), scene.Materials.Metal);
        }

        private static void CreateBollard(SceneBuilder scene, Vector3 position)
        {
            var root = new GameObject("实体防撞柱");
            root.transform.SetParent(scene.transform, false);
            root.transform.position = position;
            CreatePrimitive(PrimitiveType.Cylinder, "防撞柱柱体", root.transform,
                new Vector3(0f, 0.44f, 0f), new Vector3(0.075f, 0.44f, 0.075f), scene.Materials.Metal);
            CreatePrimitive(PrimitiveType.Cylinder, "防撞柱反光环", root.transform,
                new Vector3(0f, 0.64f, 0f), new Vector3(0.081f, 0.055f, 0.081f), scene.Materials.Marking);
        }

        private static void CreateBusShelter(SceneBuilder scene, Vector3 position, float yaw)
        {
            var root = new GameObject("实体公交候车亭");
            root.transform.SetParent(scene.transform, false);
            root.transform.SetPositionAndRotation(position, Quaternion.Euler(0f, yaw, 0f));
            CreatePrimitive(PrimitiveType.Cube, "候车亭顶棚", root.transform, new Vector3(0f, 3.1f, 0f), new Vector3(6.4f, 0.18f, 2.25f), scene.Materials.Metal);
            CreatePrimitive(PrimitiveType.Cube, "候车亭玻璃背板", root.transform, new Vector3(0f, 1.55f, 0.92f), new Vector3(5.7f, 2.85f, 0.12f), scene.Materials.BuildingGlass);
            CreatePrimitive(PrimitiveType.Cube, "候车亭左侧板", root.transform, new Vector3(-2.9f, 1.55f, 0f), new Vector3(0.12f, 2.85f, 1.8f), scene.Materials.BuildingGlass);
            CreatePrimitive(PrimitiveType.Cube, "候车长椅", root.transform, new Vector3(0.35f, 0.63f, 0.48f), new Vector3(3.9f, 0.17f, 0.65f), scene.Materials.Curb);
            foreach (var x in new[] { -1.35f, 1.35f })
                CreatePrimitive(PrimitiveType.Cube, "长椅支脚", root.transform, new Vector3(x, 0.32f, 0.48f), new Vector3(0.12f, 0.64f, 0.48f), scene.Materials.Metal);
        }

        private static void CreateWayfindingSign(SceneBuilder scene, Vector3 position, float yaw)
        {
            var root = new GameObject("城市道路导向牌");
            root.transform.SetParent(scene.transform, false);
            root.transform.SetPositionAndRotation(position, Quaternion.Euler(0f, yaw, 0f));
            CreatePrimitive(PrimitiveType.Cylinder, "导向牌立柱", root.transform, new Vector3(0f, 1.75f, 0f), new Vector3(0.075f, 1.75f, 0.075f), scene.Materials.Metal);
            CreatePrimitive(PrimitiveType.Cube, "蓝色导向牌实体", root.transform, new Vector3(0f, 3.25f, 0f), new Vector3(1.75f, 0.72f, 0.12f), scene.Materials.WayfindingBlue);
        }

        private static Bounds CalculateBounds(GameObject root)
        {
            var renderers = root.GetComponentsInChildren<Renderer>(true);
            if (renderers.Length == 0) return new Bounds(root.transform.position, Vector3.one);
            var bounds = renderers[0].bounds;
            for (var index = 1; index < renderers.Length; index++) bounds.Encapsulate(renderers[index].bounds);
            return bounds;
        }

        private static void ApplyLampMaterials(GameObject lamp, SceneBuilder scene)
        {
            foreach (var renderer in lamp.GetComponentsInChildren<Renderer>(true))
            {
                var materials = renderer.sharedMaterials;
                for (var index = 0; index < materials.Length; index++)
                {
                    var key = $"{renderer.name} {materials[index]?.name}".ToLowerInvariant();
                    materials[index] = key.Contains("glass") || key.Contains("bulb") || key.Contains("emission")
                        ? scene.Materials.Headlight
                        : scene.Materials.PbrStreetLamp;
                }
                renderer.sharedMaterials = materials;
            }
        }

        private static void ApplyTreeMaterials(GameObject tree, SceneBuilder scene)
        {
            foreach (var renderer in tree.GetComponentsInChildren<Renderer>(true))
            {
                var materials = renderer.sharedMaterials;
                for (var index = 0; index < materials.Length; index++)
                {
                    var key = $"{renderer.name} {materials[index]?.name}".ToLowerInvariant();
                    materials[index] = key.Contains("leaf") || key.Contains("leave")
                        ? scene.Materials.PbrTreeLeaves
                        : scene.Materials.PbrTreeBranches;
                }
                renderer.sharedMaterials = materials;
                renderer.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.On;
                renderer.receiveShadows = true;
            }
        }

        private static void ScatterTrees(string seed, IReadOnlyList<Vector3> polygon, MeshAccumulator trunks, MeshAccumulator crowns)
        {
            if (polygon.Count < 3) return;
            var minX = polygon.Min(point => point.x);
            var maxX = polygon.Max(point => point.x);
            var minZ = polygon.Min(point => point.z);
            var maxZ = polygon.Max(point => point.z);
            var random = new System.Random(StableHash(seed));
            var requested = Mathf.Clamp(Mathf.RoundToInt((maxX - minX + maxZ - minZ) / 24f), 8, 52);
            var placed = 0;
            for (var attempt = 0; attempt < requested * 12 && placed < requested; attempt++)
            {
                var point = new Vector3(Mathf.Lerp(minX, maxX, (float)random.NextDouble()), 0f, Mathf.Lerp(minZ, maxZ, (float)random.NextDouble()));
                if (!Inside(point, polygon)) continue;
                AddTree(point, 6.4f + (float)random.NextDouble() * 4.8f, random.Next(), trunks, crowns);
                placed++;
            }
        }

        private static void AddLandmarkTrees(
            Vector3 center, string seed, MeshAccumulator trunks, MeshAccumulator crowns,
            SceneBuilder scene, GameObject pbrTreeSource)
        {
            var random = new System.Random(StableHash(seed));
            for (var index = 0; index < 8; index++)
            {
                var angle = (index + 0.5f) * Mathf.PI * 0.25f;
                var radius = 23f + (index % 2) * 5f;
                var point = center + new Vector3(Mathf.Cos(angle) * radius, 0f, Mathf.Sin(angle) * radius);
                var height = 7.5f + (float)random.NextDouble() * 3f;
                var treeSeed = random.Next();
                if (pbrTreeSource != null && index % 2 == 0)
                    CreatePbrBoulevardTree(scene, pbrTreeSource, point, height, treeSeed);
                else
                    AddTree(point, height, treeSeed, trunks, crowns);
            }
        }

        private static void AddTree(Vector3 point, float height, int seed, MeshAccumulator trunks, MeshAccumulator crowns)
        {
            var random = new System.Random(seed);
            trunks.AddCylinder(point + Vector3.up * height * 0.28f, height * 0.045f, height * 0.56f, 9);
            var crownCenter = point + Vector3.up * height * 0.7f;
            var width = height * (0.24f + (float)random.NextDouble() * 0.07f);
            crowns.AddEllipsoid(crownCenter, new Vector3(width * 0.8f, height * 0.25f, width * 0.74f), 10, 16);
            for (var cluster = 0; cluster < 7; cluster++)
            {
                var angle = ((float)random.NextDouble() * Mathf.PI * 2f) + cluster * 0.94f;
                var radius = width * (0.28f + (float)random.NextDouble() * 0.38f);
                var offset = new Vector3(
                    Mathf.Cos(angle) * radius,
                    height * (-0.07f + (float)random.NextDouble() * 0.16f),
                    Mathf.Sin(angle) * radius);
                var clusterWidth = width * (0.5f + (float)random.NextDouble() * 0.24f);
                crowns.AddEllipsoid(
                    crownCenter + offset,
                    new Vector3(clusterWidth, height * (0.12f + (float)random.NextDouble() * 0.08f), clusterWidth * (0.78f + (float)random.NextDouble() * 0.35f)),
                    9,
                    14);
            }
        }

        private static bool Inside(Vector3 point, IReadOnlyList<Vector3> polygon)
        {
            var inside = false;
            for (int i = 0, j = polygon.Count - 1; i < polygon.Count; j = i++)
            {
                var a = polygon[i];
                var b = polygon[j];
                if ((a.z > point.z) != (b.z > point.z) && point.x < (b.x - a.x) * (point.z - a.z) / (b.z - a.z + 0.00001f) + a.x) inside = !inside;
            }
            return inside;
        }

        private static void CreateStreetLight(Vector3 position, SceneBuilder scene, float rotation)
        {
            var root = new GameObject("现代智慧路灯");
            root.transform.SetParent(scene.transform, false);
            root.transform.SetPositionAndRotation(position, Quaternion.Euler(0f, rotation, 0f));
            CreatePrimitive(PrimitiveType.Cylinder, "锥形灯杆", root.transform, new Vector3(0f, 4.7f, 0f), new Vector3(0.12f, 4.7f, 0.12f), scene.Materials.Metal);
            CreatePrimitive(PrimitiveType.Cube, "灯臂", root.transform, new Vector3(1.15f, 9.22f, 0f), new Vector3(2.3f, 0.1f, 0.1f), scene.Materials.Metal);
            var fixture = CreatePrimitive(PrimitiveType.Cube, "LED灯具", root.transform, new Vector3(2.28f, 9.08f, 0f), new Vector3(0.85f, 0.12f, 0.34f), scene.Materials.Headlight);
            fixture.transform.localRotation = Quaternion.Euler(0f, 0f, -6f);
            CreatePrimitive(PrimitiveType.Sphere, "环境感知相机", root.transform, new Vector3(0f, 7.8f, 0.18f), Vector3.one * 0.22f, scene.Materials.BuildingGlass);
        }

        private static void CreateRoadsideDevice(string id, string type, string provenance, Vector3 position, SceneBuilder scene)
        {
            var root = new GameObject(id);
            root.transform.SetParent(scene.transform, false);
            root.transform.position = position;
            var selectable = root.AddComponent<SelectableObject>();
            selectable.Identifier = id;
            selectable.Kind = type;
            selectable.Provenance = provenance;
            CreatePrimitive(PrimitiveType.Cylinder, "设备杆", root.transform, new Vector3(0f, 2.8f, 0f), new Vector3(0.13f, 2.8f, 0.13f), scene.Materials.Metal);
            CreatePrimitive(PrimitiveType.Cube, type == "camera" ? "道路摄像机" : "C-V2X RSU", root.transform, new Vector3(0f, 5.65f, 0f), type == "camera" ? new Vector3(1.15f, 0.45f, 0.45f) : new Vector3(0.75f, 0.9f, 0.38f), scene.Materials.BuildingGlass);
        }

        private static GameObject CreatePrimitive(PrimitiveType primitive, string name, Transform parent, Vector3 localPosition, Vector3 localScale, Material material)
        {
            var gameObject = GameObject.CreatePrimitive(primitive);
            gameObject.name = name;
            gameObject.transform.SetParent(parent, false);
            gameObject.transform.localPosition = localPosition;
            gameObject.transform.localScale = localScale;
            gameObject.GetComponent<Renderer>().sharedMaterial = material;
            var collider = gameObject.GetComponent<Collider>();
            if (collider != null) Object.DestroyImmediate(collider);
            return gameObject;
        }

        private static void CreateJunctionLabel(string text, Vector3 position)
        {
            var root = new GameObject($"路口标签-{text}");
            root.transform.position = position;
            var label = root.AddComponent<TextMesh>();
            label.text = text;
            label.fontSize = 42;
            label.characterSize = 0.18f;
            label.anchor = TextAnchor.MiddleCenter;
            label.alignment = TextAlignment.Center;
            label.color = new Color(0.12f, 1f, 0.78f);
            root.AddComponent<Billboard>();
        }
    }
}
