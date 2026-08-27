using System.Collections;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;
using Xiongan.DigitalTwin.Interaction;

namespace Xiongan.DigitalTwin.Scene
{
    public sealed class UrbanContextBuilder : MonoBehaviour
    {
        private const string ShowcaseJunctionId = ReferenceShowcaseLayout.JunctionId;
        private const string ShowcaseVisualAnchorJunctionId = ShowcaseJunctionId;

        public IEnumerator Build(
            SceneBuilder scene,
            System.Action<float, string> onProgress,
            bool includeModeledInfill = true)
        {
            var showcaseJunction = scene.Document.Junctions.FirstOrDefault(item => item.SumoJunctionId == ShowcaseJunctionId);
            var showcaseAnchor = scene.Document.Junctions.FirstOrDefault(item => item.SumoJunctionId == ShowcaseVisualAnchorJunctionId)
                                 ?? showcaseJunction;
            Vector3? showcaseCenter = showcaseAnchor == null
                ? null
                : scene.Coordinates.ToWorld(showcaseAnchor.Position);
            var facades = Enumerable.Range(0, scene.Materials.Facades.Count).Select(_ => new MeshAccumulator()).ToArray();
            var roofs = new MeshAccumulator();
            var parapets = new MeshAccumulator();
            var roofEquipment = new MeshAccumulator();
            var osmGlazing = new MeshAccumulator();
            var osmWarmGlazing = new MeshAccumulator();
            var osmWindowFrames = new MeshAccumulator();
            var osmArchitecturalBases = new MeshAccumulator();
            var osmRoofTiles = new MeshAccumulator();
            for (var index = 0; index < scene.Document.Buildings.Count; index++)
            {
                var building = scene.Document.Buildings[index];
                var footprint = building.Footprint.Select(point => scene.Coordinates.ToWorld(point)).ToList();
                if (footprint.Count < 3) continue;
                var footprintCenter = new Vector3(
                    footprint.Average(point => point.x), 0f, footprint.Average(point => point.z));
                if (IsInsideShowcaseExclusion(footprintCenter, showcaseCenter, 175f)) continue;
                var height = ResolveHeight(building.SceneId, building.HeightM, building.Levels);
                var hash = StableHash(building.SceneId);
                facades[hash % facades.Length].AddFacadeWalls(footprint, 0.08f, height, 10f + hash % 5);
                roofs.AddPolygon(footprint, height + 0.02f);
                parapets.AddFacadeWalls(footprint, height, height + 0.72f, 4f);
                var baseFootprint = ScalePolygonFromCenter(footprint, footprintCenter, 1.008f);
                var eaveFootprint = ScalePolygonFromCenter(footprint, footprintCenter, 1.04f);
                osmArchitecturalBases.AddFacadeWalls(baseFootprint, 0.078f, 1.28f, 6f);
                osmRoofTiles.AddExtrudedPolygon(eaveFootprint, height + 0.04f, height + 0.38f);
                AddRoofPlant(roofEquipment, footprint, height, hash);
                AddPolygonFacadeWindows(osmGlazing, osmWarmGlazing, osmWindowFrames, footprint, height, hash);
                if (index % 12 == 0) yield return null;
            }
            for (var index = 0; index < facades.Length; index++)
                facades[index].Build($"雄安现代建筑立面-{index + 1}", scene.Materials.Facades[index], transform);
            roofs.Build("建筑屋面", scene.Materials.BuildingRoof, transform);
            parapets.Build("建筑女儿墙", scene.Materials.Curb, transform, true, SceneDetailClass.Fine);
            roofEquipment.Build("建筑屋顶设备", scene.Materials.Metal, transform, true, SceneDetailClass.Fine);
            osmGlazing.Build("OSM建筑实体窗格", scene.Materials.BuildingGlass, transform, false, SceneDetailClass.Fine);
            osmWarmGlazing.Build("OSM建筑少量暖色窗格", scene.Materials.BuildingGlassWarm, transform, false, SceneDetailClass.Fine);
            osmWindowFrames.Build("OSM建筑实体层间窗框", scene.Materials.FacadeFrame, transform, true, SceneDetailClass.Fine);
            osmArchitecturalBases.Build("OSM建筑统一石材首层", scene.Materials.ArchitecturalStone, transform, true, SceneDetailClass.Context);
            osmRoofTiles.Build("OSM建筑统一灰色外挑屋面", scene.Materials.GreyRoofTile, transform, true, SceneDetailClass.Context);
            if (includeModeledInfill)
            {
                if (showcaseJunction != null) ReferenceShowcaseBuilder.Build(scene, transform);
                var controlledInfill = CreateControlledJunctionInfill(scene, showcaseCenter);
                CreateCitywideLandUseInfill(scene, showcaseCenter, controlledInfill);
                CreateIdentifiableOpenSpaces(scene);
            }

            var grass = new MeshAccumulator();
            var trunks = new MeshAccumulator();
            var crowns = new MeshAccumulator();
            var controlledTreeSource = Resources.Load<GameObject>("Art/Models/island_tree_02/island_tree_02_1k");
            foreach (var area in scene.Document.Vegetation)
            {
                var polygon = area.Shape.Select(point => scene.Coordinates.ToWorld(point)).ToList();
                // OSM vegetation can overlap road polygons. Keep it above the
                // city base but below asphalt, cycleways and footways so it can
                // never visually replace a legal traffic surface.
                grass.AddPolygon(polygon, 0.008f);
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
                // The B01 reference showcase owns its foreground assets and
                // street furniture so generic K08-era objects cannot overlap it.
            }

            grass.Build("OSM绿地与中央绿化", scene.Materials.Grass, transform, false, SceneDetailClass.Context);
            trunks.Build("真实化树干", scene.Materials.TreeBark, transform, true, SceneDetailClass.Fine);
            crowns.Build("多层自然树冠", scene.Materials.TreeLeaves, transform, true, SceneDetailClass.Context);

            ReferenceShowcaseFrame? showcaseFrame = showcaseJunction == null
                ? null
                : ReferenceShowcaseLayout.Resolve(scene);
            foreach (var device in scene.Document.RoadsideDevices)
            {
                var position = scene.Coordinates.ToWorld(device.Position);
                if (showcaseFrame.HasValue && device.ManagedJunctions.Contains(ShowcaseJunctionId))
                    position = ReferenceShowcaseLayout.ResolveRoadsideDevicePosition(
                        showcaseFrame.Value, device.DeviceType);
                var managedJunction = device.ManagedJunctions
                    .Select(id => scene.Document.Junctions.FirstOrDefault(item => item.SumoJunctionId == id))
                    .FirstOrDefault(item => item != null);
                var facingTarget = managedJunction == null
                    ? position + Vector3.forward
                    : scene.Coordinates.ToWorld(managedJunction.Position);
                CreateRoadsideDevice(
                    device.DeviceId, device.DeviceType, device.Provenance,
                    position, facingTarget, scene);
            }
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

        private static bool IsInsideShowcaseExclusion(
            Vector3 point, Vector3? showcaseCenter, float radius)
        {
            return showcaseCenter.HasValue &&
                   Vector3.Distance(point, showcaseCenter.Value) < radius;
        }

        private static List<Vector3> ScalePolygonFromCenter(
            IReadOnlyList<Vector3> polygon, Vector3 center, float scale)
        {
            return polygon.Select(point => center + (point - center) * scale).ToList();
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
            CreateShowcaseBoulevardMedians(scene, root.transform, center);
            var plots = new[]
            {
                (new Vector3(-72f, 0f, -88f), new Vector2(42f, 27f), 24.5f, 0, 7, "residential"),
                (new Vector3(-27f, 0f, -105f), new Vector2(33f, 23f), 19.4f, 2, 8, "school"),
                (new Vector3(28f, 0f, -106f), new Vector2(35f, 23f), 28.7f, 5, 5, "residential"),
                (new Vector3(74f, 0f, -90f), new Vector2(44f, 28f), 37.4f, 6, 9, "commercial"),
                (new Vector3(-92f, 0f, -27f), new Vector2(30f, 47f), 27.2f, 1, 7, "residential"),
                (new Vector3(94f, 0f, -25f), new Vector2(31f, 49f), 35.8f, 3, 3, "commercial"),
                (new Vector3(-92f, 0f, 32f), new Vector2(31f, 45f), 32.6f, 4, 5, "residential"),
                (new Vector3(94f, 0f, 36f), new Vector2(32f, 47f), 25.8f, 7, 6, "commercial"),
                (new Vector3(-72f, 0f, 91f), new Vector2(42f, 28f), 22.8f, 2, 7, "residential"),
                (new Vector3(77f, 0f, 93f), new Vector2(45f, 30f), 29.3f, 1, 8, "exhibition_centre"),
            };
            var plotPaving = new MeshAccumulator();
            var plotPlanting = new MeshAccumulator();
            var plotLandscape = new MeshAccumulator();
            var facades = Enumerable.Range(0, scene.Materials.Facades.Count).Select(_ => new MeshAccumulator()).ToArray();
            var roofs = new MeshAccumulator();
            var parapets = new MeshAccumulator();
            var glazing = new MeshAccumulator();
            var frames = new MeshAccumulator();
            var roofEquipment = new MeshAccumulator();
            var architecturalBases = new MeshAccumulator();
            var brickAccents = new MeshAccumulator();
            var roofTiles = new MeshAccumulator();
            var timberScreens = new MeshAccumulator();
            var entranceGlass = new MeshAccumulator();
            foreach (var (offset, size, height, materialIndex, style, areaType) in plots)
            {
                var plotCenter = center + offset;
                var towardRoad = offset.sqrMagnitude > 0.01f ? -offset.normalized : Vector3.forward;
                var roadDirection = Vector3.Cross(Vector3.up, towardRoad).normalized;
                plotLandscape.AddPolygon(
                    OrientedRectangle(plotCenter, size.x + 20f, size.y + 18f, roadDirection), 0.086f);
                var plazaCenter = plotCenter + towardRoad * (size.y * 0.5f + 3.5f);
                plotPaving.AddPolygon(
                    OrientedRectangle(plazaCenter, size.x + 8f, 7.5f, roadDirection), 0.096f);
                plotPlanting.AddPolygon(
                    OrientedRectangle(plotCenter + towardRoad * (size.y * 0.5f + 8.3f),
                        size.x + 6f, 4.2f, roadDirection), 0.105f);
                var groupSeed = StableHash($"showcase-group:{Mathf.Sign(offset.x)}:{Mathf.Sign(offset.z)}");
                AddCitywideBuilding(
                    facades[materialIndex], roofs, parapets, glazing, frames, roofEquipment,
                    architecturalBases, brickAccents, roofTiles, timberScreens, entranceGlass,
                    plotCenter, size.x, size.y, height, roadDirection, towardRoad,
                    areaType, style, groupSeed);
            }
            for (var index = 0; index < facades.Length; index++)
                facades[index].Build($"代表性组团建筑立面-{index + 1}", scene.Materials.Facades[index], root.transform);
            roofs.Build("代表性组团实体屋面", scene.Materials.BuildingRoof, root.transform);
            parapets.Build("代表性组团低女儿墙", scene.Materials.Curb, root.transform, true, SceneDetailClass.Fine);
            glazing.Build("代表性组团实体窗格", scene.Materials.BuildingGlass, root.transform, false, SceneDetailClass.Fine);
            frames.Build("代表性组团窗框与层间檐口", scene.Materials.FacadeFrame, root.transform, true, SceneDetailClass.Fine);
            roofEquipment.Build("代表性组团屋顶设备", scene.Materials.BuildingRoof, root.transform, true, SceneDetailClass.Fine);
            architecturalBases.Build("代表性组团石材基座与院墙", scene.Materials.ArchitecturalStone, root.transform, true, SceneDetailClass.Context);
            brickAccents.Build("代表性组团暖灰砖红构件", scene.Materials.BrickAccent, root.transform, true, SceneDetailClass.Context);
            roofTiles.Build("代表性组团灰色深檐", scene.Materials.GreyRoofTile, root.transform, true, SceneDetailClass.Context);
            timberScreens.Build("代表性组团入口格栅雨棚", scene.Materials.TimberScreen, root.transform, true, SceneDetailClass.Fine);
            entranceGlass.Build("代表性组团首层门厅", scene.Materials.BuildingGlass, root.transform, false, SceneDetailClass.Context);
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
            else if (style == 7)
            {
                // A restrained U-shaped courtyard is the dominant residential
                // composition in the Xiong'an-inspired generated districts.
                wings[0] = (center + new Vector3(0f, 0f, -size.y * 0.31f),
                    new Vector2(size.x, size.y * 0.3f), height);
                wings.Add((center + new Vector3(-size.x * 0.39f, 0f, size.y * 0.08f),
                    new Vector2(size.x * 0.22f, size.y * 0.62f), height * 0.96f));
                wings.Add((center + new Vector3(size.x * 0.39f, 0f, size.y * 0.08f),
                    new Vector2(size.x * 0.22f, size.y * 0.62f), height * 0.92f));
            }
            return wings;
        }

        private static IReadOnlyList<(Vector3 Center, float Radius)> CreateControlledJunctionInfill(
            SceneBuilder scene, Vector3? showcaseCenter)
        {
            var root = new GameObject("二十路口差异化城市街区填充");
            root.transform.SetParent(scene.transform, false);
            var facades = Enumerable.Range(0, scene.Materials.Facades.Count).Select(_ => new MeshAccumulator()).ToArray();
            var roofs = new MeshAccumulator();
            var parapets = new MeshAccumulator();
            var roofEquipment = new MeshAccumulator();
            var glazing = new MeshAccumulator();
            var frames = new MeshAccumulator();
            var architecturalBases = new MeshAccumulator();
            var brickAccents = new MeshAccumulator();
            var roofTiles = new MeshAccumulator();
            var timberScreens = new MeshAccumulator();
            var entranceGlass = new MeshAccumulator();
            var paving = new MeshAccumulator();
            var planting = new MeshAccumulator();
            var districtTreeTrunks = new MeshAccumulator();
            var districtTreeCrowns = new MeshAccumulator();
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
                for (var plotIndex = 0; plotIndex < candidates.Count && createdForJunction < 17; plotIndex++)
                {
                    var sourceOffset = candidates[plotIndex];
                    var plotCenter = center + sourceOffset;
                    if (IsInsideShowcaseExclusion(plotCenter, showcaseCenter, 152f)) continue;

                    var innerPlot = sourceOffset.magnitude < 115f;
                    var groupSeed = StableHash($"junction-group:{junction.SumoJunctionId}:{plotIndex / 4}");
                    var width = (innerPlot ? 19f : 25f) + groupSeed % (innerPlot ? 7 : 9);
                    var depth = (innerPlot ? 16f : 20f) + groupSeed / 7 % (innerPlot ? 5 : 7);
                    var plotRadius = Mathf.Sqrt(width * width + depth * depth) * 0.5f;
                    var clearance = plotRadius + 3.5f;
                    if (IsNearRoad(plotCenter, clearance, roadSegments)) continue;
                    if (occupied.Any(existing =>
                            Vector3.Distance(existing.Center, plotCenter) < existing.Radius + plotRadius + 5f)) continue;

                    // The generic junction camera sits north-west of its target. Keep its
                    // approach clear so dense infill frames the intersection instead of
                    // putting the viewer inside a facade.
                    var cameraPlanarPosition = center + new Vector3(-34.8f, 0f, 95.6f);
                    if (Vector3.Distance(plotCenter, cameraPlanarPosition) < plotRadius + 30f) continue;

                    var areaType = groupSeed % 13 == 0 && plotIndex < 4 ? "commercial" : "residential";
                    ResolveZonePlot(areaType, groupSeed, out _, out _, out var height, out var style);
                    var memberHeight = height;
                    var memberWidth = width;
                    var memberDepth = depth;
                    ApplyGroupMemberVariation(areaType, hash + plotIndex * 17,
                        ref memberWidth, ref memberDepth, ref memberHeight);
                    width = memberWidth;
                    depth = memberDepth;
                    height = memberHeight;
                    plotRadius = Mathf.Sqrt(width * width + depth * depth) * 0.5f;
                    if (!TryFindNearestRoadSegment(plotCenter, roadSegments,
                            out var roadFrom, out var roadTo, out _)) continue;
                    var roadDirection = roadTo - roadFrom;
                    roadDirection.y = 0f;
                    if (roadDirection.sqrMagnitude < 0.001f) roadDirection = Vector3.right;
                    roadDirection.Normalize();
                    var streetDirection = center - plotCenter;
                    streetDirection.y = 0f;
                    if (streetDirection.sqrMagnitude < 0.001f)
                        streetDirection = Vector3.Cross(Vector3.up, roadDirection);
                    streetDirection.Normalize();
                    var materialIndex = XionganFacadeIndex(areaType, groupSeed, facades.Length);
                    AddCitywideBuilding(
                        facades[materialIndex], roofs, parapets, glazing, frames, roofEquipment,
                        architecturalBases, brickAccents, roofTiles, timberScreens, entranceGlass,
                        plotCenter, width, depth, height, roadDirection, streetDirection,
                        areaType, style, groupSeed, sourceOffset.magnitude > 120f);
                    AddPlotGroundTreatment(
                        paving, planting, plotCenter, width, depth, roadDirection, streetDirection,
                        areaType, 9f);
                    AddDistrictPlotTrees(
                        districtTreeTrunks, districtTreeCrowns, plotCenter, width, depth,
                        roadDirection, streetDirection, areaType, groupSeed);
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
            }
            roofs.Build("差异化街区屋面与退台", scene.Materials.BuildingRoof, root.transform);
            parapets.Build("差异化街区女儿墙", scene.Materials.Curb, root.transform, true, SceneDetailClass.Fine);
            roofEquipment.Build("差异化街区屋顶设备与冠部", scene.Materials.BuildingRoof, root.transform, true, SceneDetailClass.Fine);
            glazing.Build("差异化街区实体窗格", scene.Materials.BuildingGlass, root.transform, false, SceneDetailClass.Fine);
            frames.Build("差异化街区实体窗框与檐口", scene.Materials.FacadeFrame, root.transform, true, SceneDetailClass.Fine);
            architecturalBases.Build("重点路口组团石材基座与院墙", scene.Materials.ArchitecturalStone, root.transform, true, SceneDetailClass.Context);
            brickAccents.Build("重点路口组团暖灰砖红构件", scene.Materials.BrickAccent, root.transform, true, SceneDetailClass.Context);
            roofTiles.Build("重点路口组团灰色深檐", scene.Materials.GreyRoofTile, root.transform, true, SceneDetailClass.Context);
            timberScreens.Build("重点路口组团入口格栅与雨棚", scene.Materials.TimberScreen, root.transform, true, SceneDetailClass.Fine);
            entranceGlass.Build("差异化街区实体门厅", scene.Materials.BuildingGlass, root.transform, false, SceneDetailClass.Context);
            paving.Build($"差异化街区硬质场地-{created}", scene.Materials.Sidewalk, root.transform, false, SceneDetailClass.Context);
            planting.Build($"差异化街区庭院绿地-{created}", scene.Materials.Grass, root.transform, false, SceneDetailClass.Context);
            districtTreeTrunks.Build("差异化街区庭院树干", scene.Materials.TreeBark, root.transform, true, SceneDetailClass.Context);
            districtTreeCrowns.Build("差异化街区庭院树冠", scene.Materials.TreeLeaves, root.transform, true, SceneDetailClass.Context);
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
            SceneBuilder scene, Vector3? showcaseCenter,
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
            var architecturalBases = new MeshAccumulator();
            var brickAccents = new MeshAccumulator();
            var roofTiles = new MeshAccumulator();
            var timberScreens = new MeshAccumulator();
            var entranceGlass = new MeshAccumulator();
            var paving = new MeshAccumulator();
            var planting = new MeshAccumulator();
            var districtTreeTrunks = new MeshAccumulator();
            var districtTreeCrowns = new MeshAccumulator();
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
            const int citywideSafetyLimit = 900;
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
                        if (IsInsideShowcaseExclusion(plotCenter, showcaseCenter, 228f)) continue;
                        if (controlledCenters.Any(center => Vector3.Distance(center, plotCenter) < 118f)) continue;
                        if (preservedLand.Any(polygon => PointInPolygon(plotCenter, polygon))) continue;
                        if (zones.Any(other =>
                                other.Id != zone.Id && other.Area < zone.Area * 0.94f &&
                                other.Type != zone.Type && PointInPolygon(plotCenter, other.Polygon))) continue;

                        var groupSeed = StableHash($"xiongan-group:{zone.Id}:{row / 2}:{column / 2}");
                        ResolveZonePlot(zone.Type, groupSeed, out var width, out var depth, out var height, out var style);
                        ApplyGroupMemberVariation(zone.Type, hash, ref width, ref depth, ref height);
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

                        var streetDirection = ClosestPointOnSegment(plotCenter, roadFrom, roadTo) - plotCenter;
                        streetDirection.y = 0f;
                        if (streetDirection.sqrMagnitude < 0.001f)
                            streetDirection = Vector3.Cross(Vector3.up, roadDirection);
                        streetDirection.Normalize();
                        var materialIndex = XionganFacadeIndex(zone.Type, groupSeed, facades.Length);
                        AddCitywideBuilding(
                            facades[materialIndex], roofs, parapets, glazing, frames, roofEquipment,
                            architecturalBases, brickAccents, roofTiles, timberScreens, entranceGlass,
                            plotCenter, width, depth, height, roadDirection, streetDirection,
                            zone.Type, style, groupSeed);
                        AddPlotGroundTreatment(
                            paving, planting, plotCenter, width, depth, roadDirection, streetDirection,
                            zone.Type, 9f);
                        AddDistrictPlotTrees(
                            districtTreeTrunks, districtTreeCrowns, plotCenter, width, depth,
                            roadDirection, streetDirection, zone.Type, groupSeed);
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
                    if (IsInsideShowcaseExclusion(center, showcaseCenter, 214f)) continue;
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
            for (var round = 0; round < 12 && created < citywideSafetyLimit; round++)
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
                        if (IsInsideShowcaseExclusion(plotCenter, showcaseCenter, 220f)) continue;
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

                        var groupSeed = StableHash($"coverage-group:{cell.X}:{cell.Z}:{areaType}");
                        ResolveZonePlot(areaType, groupSeed, out var width, out var depth, out var height, out var style);
                        ApplyGroupMemberVariation(areaType, hash, ref width, ref depth, ref height);
                        width *= 0.74f;
                        depth *= 0.74f;
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
                                Vector3.Distance(existing.Center, plotCenter) < existing.Radius + plotRadius + 3f)) continue;

                        var streetDirection = ClosestPointOnSegment(plotCenter, roadFrom, roadTo) - plotCenter;
                        streetDirection.y = 0f;
                        if (streetDirection.sqrMagnitude < 0.001f)
                            streetDirection = Vector3.Cross(Vector3.up, roadDirection);
                        streetDirection.Normalize();
                        var materialIndex = XionganFacadeIndex(areaType, groupSeed, facades.Length);
                        AddCitywideBuilding(
                            facades[materialIndex], roofs, parapets, glazing, frames, roofEquipment,
                            architecturalBases, brickAccents, roofTiles, timberScreens, entranceGlass,
                            plotCenter, width, depth, height, roadDirection, streetDirection,
                            areaType, style, groupSeed, true);
                        AddPlotGroundTreatment(
                            paving, planting, plotCenter, width, depth, roadDirection, streetDirection,
                            areaType, 8f);
                        AddDistrictPlotTrees(
                            districtTreeTrunks, districtTreeCrowns, plotCenter, width, depth,
                            roadDirection, streetDirection, areaType, groupSeed);
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
            for (var sweep = 0; sweep < 10 && created < citywideSafetyLimit; sweep++)
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
                        var groupSeed = StableHash($"road-edge-group:{cell.X}:{cell.Z}:{areaType}");
                        ResolveZonePlot(areaType, groupSeed, out var width, out var depth, out var height, out var style);
                        ApplyGroupMemberVariation(areaType, hash, ref width, ref depth, ref height);
                        width *= 0.7f;
                        depth *= 0.72f;
                        height *= 0.9f;
                        var plotRadius = Mathf.Sqrt(width * width + depth * depth) * 0.5f;
                        var sideSign = (attempt & 1) == 0 ? -1f : 1f;
                        var ring = attempt / 2 % 3;
                        var alongOffset = ((hash / 101) % 1009 / 1008f - 0.5f) * 42f;
                        var plotCenter = roadAnchor + roadDirection * alongOffset +
                                         roadNormal * sideSign * (plotRadius + 11f + ring * 7f);
                        if (Mathf.Abs(plotCenter.x - cell.Center.x) > coverageCellSize * 0.68f ||
                            Mathf.Abs(plotCenter.z - cell.Center.z) > coverageCellSize * 0.68f) continue;
                        if (IsInsideShowcaseExclusion(plotCenter, showcaseCenter, 220f)) continue;
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
                                Vector3.Distance(existing.Center, plotCenter) < existing.Radius + plotRadius + 2.2f)) continue;

                        var streetDirection = roadAnchor - plotCenter;
                        streetDirection.y = 0f;
                        if (streetDirection.sqrMagnitude < 0.001f) streetDirection = -roadNormal * sideSign;
                        streetDirection.Normalize();
                        var materialIndex = XionganFacadeIndex(areaType, groupSeed, facades.Length);
                        AddCitywideBuilding(
                            facades[materialIndex], roofs, parapets, glazing, frames, roofEquipment,
                            architecturalBases, brickAccents, roofTiles, timberScreens, entranceGlass,
                            plotCenter, width, depth, height, roadDirection, streetDirection,
                            areaType, style, groupSeed, true);
                        AddPlotGroundTreatment(
                            paving, planting, plotCenter, width, depth, roadDirection, streetDirection,
                            areaType, 7f);
                        AddDistrictPlotTrees(
                            districtTreeTrunks, districtTreeCrowns, plotCenter, width, depth,
                            roadDirection, streetDirection, areaType, groupSeed);
                        occupied.Add((plotCenter, plotRadius));
                        counts[areaType] = counts.TryGetValue(areaType, out var count) ? count + 1 : 1;
                        roadEdgeCreated++;
                        created++;
                        placed = true;
                    }
                }
            }
            coveredCells = coverageCells.Count(cell => CellOccupancy(cell) >= cell.Target);

            // Large OSM land-use polygons can remain visually empty even when
            // their sparse source footprints are valid. Add a bounded layer of
            // low-poly planning trees to unused, road-connected parts of each
            // developed block, including the green buffers of construction land.
            var supplementalTrees = 0;
            foreach (var zone in zones)
            {
                var spacing = zone.Type == "construction" ? 42f : 55f;
                var target = Mathf.Clamp(
                    Mathf.FloorToInt(zone.Area / (spacing * spacing)),
                    2,
                    zone.Type == "construction" ? 36 : 18);
                var minX = Mathf.Max(sceneMinX, zone.Polygon.Min(point => point.x));
                var maxX = Mathf.Min(sceneMaxX, zone.Polygon.Max(point => point.x));
                var minZ = Mathf.Max(sceneMinZ, zone.Polygon.Min(point => point.z));
                var maxZ = Mathf.Min(sceneMaxZ, zone.Polygon.Max(point => point.z));
                var seed = StableHash($"supplemental-green:{zone.Id}");
                var placed = 0;
                var row = 0;
                for (var z = minZ + spacing * 0.45f; z < maxZ && placed < target; z += spacing, row++)
                {
                    var column = 0;
                    for (var x = minX + spacing * 0.45f; x < maxX && placed < target; x += spacing, column++)
                    {
                        var pointSeed = StableHash($"supplemental-green:{zone.Id}:{row}:{column}");
                        var point = new Vector3(
                            x + ((pointSeed % 101) / 100f - 0.5f) * spacing * 0.34f,
                            0f,
                            z + (((pointSeed / 101) % 101) / 100f - 0.5f) * spacing * 0.34f);
                        if (!PointInPolygon(point, zone.Polygon)) continue;
                        if (IsInsideShowcaseExclusion(point, showcaseCenter, 225f)) continue;
                        if (controlledCenters.Any(center => Vector3.Distance(center, point) < 38f)) continue;
                        if (!TryFindNearestRoadSegment(point, roadSegments, out _, out _, out var roadDistanceSquared))
                            continue;
                        var roadDistance = Mathf.Sqrt(roadDistanceSquared);
                        if (roadDistance < 11f || roadDistance > 92f) continue;
                        if (occupied.Any(existing =>
                                Vector3.Distance(existing.Center, point) < existing.Radius + 5f)) continue;

                        var height = 5.6f + (seed + pointSeed) % 17 * 0.14f;
                        AddPlanningTree(
                            districtTreeTrunks, districtTreeCrowns,
                            point, height, pointSeed);
                        placed++;
                        supplementalTrees++;
                    }
                }
            }

            for (var index = 0; index < facades.Length; index++)
                facades[index].Build($"全城背景建筑立面-{index + 1}", scene.Materials.Facades[index],
                    root.transform, true, SceneDetailClass.Essential, 768f);
            roofs.Build("全城背景建筑屋面", scene.Materials.BuildingRoof, root.transform,
                true, SceneDetailClass.Essential, 768f);
            parapets.Build("全城背景建筑女儿墙", scene.Materials.Curb, root.transform, true, SceneDetailClass.Fine);
            glazing.Build("全城背景建筑实体窗格", scene.Materials.BuildingGlass, root.transform, false, SceneDetailClass.Fine);
            frames.Build("全城背景建筑实体窗框", scene.Materials.FacadeFrame, root.transform, true, SceneDetailClass.Fine);
            roofEquipment.Build("全城背景建筑屋顶机房", scene.Materials.BuildingRoof, root.transform, true, SceneDetailClass.Fine);
            architecturalBases.Build("雄安组团统一石材基座与院墙", scene.Materials.ArchitecturalStone, root.transform, true, SceneDetailClass.Context);
            brickAccents.Build("雄安组团暖灰砖红识别构件", scene.Materials.BrickAccent, root.transform, true, SceneDetailClass.Context);
            roofTiles.Build("雄安组团灰色深檐与屋面", scene.Materials.GreyRoofTile, root.transform, true, SceneDetailClass.Context);
            timberScreens.Build("雄安组团入口格栅与雨棚", scene.Materials.TimberScreen, root.transform, true, SceneDetailClass.Fine);
            entranceGlass.Build("雄安组团首层门廊与商业界面", scene.Materials.BuildingGlass, root.transform, false, SceneDetailClass.Context);
            paving.Build("全城建筑前场硬质铺装", scene.Materials.Sidewalk, root.transform, false, SceneDetailClass.Context);
            planting.Build("住宅学校庭院绿地", scene.Materials.Grass, root.transform, false, SceneDetailClass.Context);
            districtTreeTrunks.Build("全城规划地块树干", scene.Materials.TreeBark, root.transform, true, SceneDetailClass.Context);
            districtTreeCrowns.Build("全城规划地块树冠", scene.Materials.TreeLeaves, root.transform, true, SceneDetailClass.Context);
            parkingGround.Build("停车功能区实体铺装", scene.Materials.ParkingGround, root.transform, false, SceneDetailClass.Context);
            parkingMarkings.Build("停车功能区实体标线", scene.Materials.Marking, root.transform, false, SceneDetailClass.Fine);
            constructionGround.Build("施工功能区实体场地", scene.Materials.ConstructionGround, root.transform, false, SceneDetailClass.Context);
            root.name = $"全城功能区连续街区-{created}栋";
            scene.RegisterGeneratedBuildings(created);
            Debug.Log($"Citywide land-use infill complete: {created} buildings; " +
                      string.Join(", ", counts.OrderBy(item => item.Key).Select(item => $"{item.Key}={item.Value}")) +
                      $"; coverage infill={coverageCreated}; road-edge infill={roadEdgeCreated}; " +
                      $"cells={coveredCells}/{coverageCells.Count}; supplemental trees={supplementalTrees}");
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

            paths.Build("公园十字慢行步道", scene.Materials.Sidewalk, root.transform, false, SceneDetailClass.Context);
            plazas.Build("公园廊亭前场铺装", scene.Materials.HeroSidewalk, root.transform, false, SceneDetailClass.Context);
            pavilionWalls.Build("公园公共廊亭浅色实体墙", scene.Materials.Facades[0], root.transform);
            pavilionRoofs.Build("公园公共廊亭平屋盖", scene.Materials.BuildingRoof, root.transform);
            pavilionFrames.Build("公园公共廊亭细柱", scene.Materials.FacadeFrame, root.transform, true, SceneDetailClass.Fine);
            root.name = $"可识别公园广场与公共廊亭-{created}处";
            Debug.Log($"Identifiable open spaces complete: {created}/{openSpaces.Count}");
        }

        private static void AddCitywideBuilding(
            MeshAccumulator facade, MeshAccumulator roofs, MeshAccumulator parapets,
            MeshAccumulator glazing, MeshAccumulator frames, MeshAccumulator roofEquipment,
            MeshAccumulator architecturalBases, MeshAccumulator brickAccents,
            MeshAccumulator roofTiles, MeshAccumulator timberScreens, MeshAccumulator entranceGlass,
            Vector3 center, float width, float depth, float height,
            Vector3 roadDirection, Vector3 streetDirection,
            string areaType, int style, int seed, bool simplified = false)
        {
            roadDirection.y = 0f;
            if (roadDirection.sqrMagnitude < 0.001f) roadDirection = Vector3.right;
            roadDirection.Normalize();
            streetDirection.y = 0f;
            streetDirection -= roadDirection * Vector3.Dot(streetDirection, roadDirection);
            if (streetDirection.sqrMagnitude < 0.001f)
                streetDirection = Vector3.Cross(Vector3.up, roadDirection);
            streetDirection.Normalize();

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
            else if (style == 7 && width > 27f && depth > 17f)
            {
                volumes.Add((center - streetDirection * depth * 0.31f,
                    width, depth * 0.3f, height, roadDirection));
                volumes.Add((center - roadDirection * width * 0.39f + streetDirection * depth * 0.08f,
                    width * 0.22f, depth * 0.62f, height * 0.96f, roadDirection));
                volumes.Add((center + roadDirection * width * 0.39f + streetDirection * depth * 0.08f,
                    width * 0.22f, depth * 0.62f, height * 0.92f, roadDirection));
            }
            else if (style == 8 && width > 31f && depth > 18f)
            {
                // Campus/civic prototype: two calm bars and a lower glazed link.
                volumes.Add((center - streetDirection * depth * 0.23f,
                    width, depth * 0.36f, height, roadDirection));
                volumes.Add((center + streetDirection * depth * 0.25f,
                    width * 0.82f, depth * 0.3f, height * 0.82f, roadDirection));
                volumes.Add((center,
                    depth * 0.45f, width * 0.18f, height * 0.42f, normal));
            }
            else if (style == 9 && width > 29f && depth > 18f)
            {
                // Stepped office/residential prototype with a readable skyline.
                volumes.Add((center + streetDirection * depth * 0.08f,
                    width, depth * 0.78f, height * 0.62f, roadDirection));
                volumes.Add((center - streetDirection * depth * 0.12f - roadDirection * width * 0.11f,
                    width * 0.68f, depth * 0.58f, height, roadDirection));
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
                var baseFootprint = OrientedRectangle(
                    volume.Center, volume.Width + 0.24f, volume.Depth + 0.24f, volume.Direction);
                architecturalBases.AddFacadeWalls(baseFootprint, 0.078f, 1.32f, 6f);
                var eaveOverhang = style switch
                {
                    7 => 1.15f,
                    8 => 1.85f,
                    5 => 0.9f,
                    4 or 9 => 0.7f,
                    _ => 0.55f + seed % 4 * 0.12f,
                };
                var eaveThickness = style is 7 or 8 ? 0.3f : 0.2f;
                var eaveFootprint = OrientedRectangle(
                    volume.Center,
                    volume.Width + eaveOverhang * 2f,
                    volume.Depth + eaveOverhang * 2f,
                    volume.Direction);
                roofTiles.AddExtrudedPolygon(
                    eaveFootprint,
                    volume.Height + 0.05f,
                    volume.Height + 0.05f + eaveThickness);
                if (style is 3 or 4 or 6 or 9)
                    parapets.AddFacadeWalls(footprint, volume.Height + 0.43f, volume.Height + 0.8f, 4f);
                AddCitywideFacadeBands(
                    glazing, frames, footprint, volume.Height, seed + index * 31, style, simplified);
            }

            var frontEdge = center + streetDirection * (depth * 0.5f + 0.13f);
            var entranceWidth = Mathf.Clamp(width * 0.2f, 4.8f, 7.4f);
            var civicFrontage = areaType is "commercial" or "exhibition_centre" or "industrial";
            AddFacadeStrip(entranceGlass, frontEdge, roadDirection, streetDirection,
                civicFrontage ? width * 0.72f : entranceWidth, 0.28f, 3.72f, 0.08f);

            if (civicFrontage && !simplified)
            {
                const int columnCount = 6;
                for (var column = 0; column < columnCount; column++)
                {
                    var along = Mathf.Lerp(-width * 0.38f, width * 0.38f,
                        column / (float)(columnCount - 1));
                    architecturalBases.AddExtrudedPolygon(
                        OrientedRectangle(
                            frontEdge + roadDirection * along + streetDirection * 0.72f,
                            0.36f, 0.36f, roadDirection),
                        0.08f, 4.08f);
                }
            }

            var canopy = OrientedRectangle(
                frontEdge + streetDirection * 1.05f,
                entranceWidth + 1.4f, 2.35f, roadDirection);
            timberScreens.AddExtrudedPolygon(canopy, 3.76f, 4.04f);
            var slatCount = simplified ? 4 : 6;
            for (var slat = 0; slat < slatCount; slat++)
            {
                var along = Mathf.Lerp(-entranceWidth * 0.42f, entranceWidth * 0.42f,
                    slatCount == 1 ? 0.5f : slat / (float)(slatCount - 1));
                var slatFootprint = OrientedRectangle(
                    frontEdge + roadDirection * along + streetDirection * 0.22f,
                    0.16f, 0.2f, roadDirection);
                timberScreens.AddExtrudedPolygon(slatFootprint, 0.34f, 3.78f);
            }

            var useBrickAccent = areaType is "residential" or "school" or "kindergarten" or "exhibition_centre"
                                 && seed % 5 == 0;
            if (useBrickAccent)
            {
                var accentHeight = Mathf.Max(4.2f, height - 0.75f);
                var offset = width * 0.38f;
                AddFacadeStrip(brickAccents, frontEdge + roadDirection * offset,
                    roadDirection, streetDirection, 0.95f, 1.32f, accentHeight, 0.12f);
                AddFacadeStrip(brickAccents, frontEdge - roadDirection * offset,
                    roadDirection, streetDirection, 0.95f, 1.32f, accentHeight, 0.12f);
            }

            if (style == 7)
            {
                var entranceGap = Mathf.Clamp(width * 0.2f, 5.2f, 7.5f);
                var wallWidth = Mathf.Max(2.5f, (width - entranceGap) * 0.5f);
                var wallOffset = entranceGap * 0.5f + wallWidth * 0.5f;
                foreach (var sign in new[] { -1f, 1f })
                {
                    var wallCenter = center + streetDirection * (depth * 0.49f) +
                                     roadDirection * wallOffset * sign;
                    architecturalBases.AddExtrudedPolygon(
                        OrientedRectangle(wallCenter, wallWidth, 0.34f, roadDirection),
                        0.09f, 1.48f);
                }
            }

            AddFacadeIdentityFeatures(
                frames, brickAccents, roofTiles, timberScreens, glazing,
                center, width, depth, height, roadDirection, streetDirection,
                areaType, style, seed, simplified);

            if (style is 3 or 4 or 6 || seed % 5 == 0)
            {
                var tallest = volumes.Max(volume => volume.Height);
                var equipmentCenter = center + roadDirection * width * 0.12f - normal * depth * 0.08f;
                var equipment = OrientedRectangle(
                    equipmentCenter,
                    Mathf.Clamp(width * 0.22f, 3.2f, 8f),
                    Mathf.Clamp(depth * 0.2f, 2.8f, 6.5f),
                    roadDirection);
                roofEquipment.AddExtrudedPolygon(
                    equipment, tallest + 0.3f, tallest + 1.35f + style * 0.06f);
            }
        }

        private static void AddCitywideFacadeBands(
            MeshAccumulator glazing, MeshAccumulator frames,
            IReadOnlyList<Vector3> footprint, float height, int seed, int style, bool simplified)
        {
            if (footprint.Count < 3 || height < 7f) return;
            var center = footprint.Aggregate(Vector3.zero, (sum, point) => sum + point) / footprint.Count;
            var floorHeight = 3.18f + seed % 4 * 0.08f;
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
                    var targetBayWidth = style switch
                    {
                        3 or 6 => 4.7f,
                        5 => 3.1f,
                        7 => 4.15f,
                        8 => 3.3f,
                        9 => 3.8f,
                        _ => 3.55f,
                    };
                    var bayCount = Mathf.Clamp(
                        Mathf.FloorToInt(length / (simplified ? 5.8f : targetBayWidth)),
                        3,
                        simplified ? 8 : 14);
                    var usableWidth = length * (style is 3 or 6 or 8 ? 0.88f : 0.82f);
                    var bayPitch = usableWidth / bayCount;
                    var windowRatio = style switch
                    {
                        3 or 6 => 0.76f,
                        5 => 0.68f,
                        7 => 0.48f,
                        8 => 0.7f,
                        _ => 0.62f,
                    };
                    var windowWidth = Mathf.Clamp(bayPitch * windowRatio, 1.05f, 2.65f);
                    var rowStep = simplified ? 2 : 1;
                    var floorCount = Mathf.Max(1, Mathf.FloorToInt((height - 1.4f) / floorHeight));
                    for (var floor = 1; floor < floorCount; floor += rowStep)
                    {
                        var windowCenterY = 1.3f + floor * floorHeight + floorHeight * 0.5f;
                        if (windowCenterY + 0.92f >= height) continue;
                        var windowHeight = simplified
                            ? 1.35f
                            : style switch
                            {
                                3 or 6 => 2.08f,
                                5 => 1.78f,
                                7 => 1.48f,
                                8 => 1.92f,
                                _ => 1.62f,
                            };
                        for (var bay = 0; bay < bayCount; bay++)
                        {
                            if (!simplified && (bay * 7 + floor * 5 + edgeIndex + seed) % 29 == 0) continue;
                            var along = -usableWidth * 0.5f + bayPitch * (bay + 0.5f);
                            var windowCenter = edgeCenter + direction * along;
                            var bottom = windowCenterY - windowHeight * 0.5f;
                            var top = windowCenterY + windowHeight * 0.5f;
                            AddFacadeStrip(glazing, windowCenter, direction, outward,
                                windowWidth, bottom, top, 0.085f);
                            AddFacadeStrip(frames, windowCenter, direction, outward,
                                windowWidth + 0.18f, bottom - 0.09f, bottom + 0.025f, 0.13f);
                            if (!simplified)
                            {
                                // Real window openings read as four-sided frames instead of
                                // flat dark stickers. Keep the extra geometry on foreground
                                // buildings only so the city-wide WebGL budget stays bounded.
                                AddFacadeStrip(frames, windowCenter, direction, outward,
                                    windowWidth + 0.18f, top - 0.025f, top + 0.09f, 0.13f);
                                AddFacadeStrip(frames,
                                    windowCenter - direction * (windowWidth * 0.5f + 0.06f),
                                    direction, outward, 0.12f, bottom, top, 0.13f);
                                AddFacadeStrip(frames,
                                    windowCenter + direction * (windowWidth * 0.5f + 0.06f),
                                    direction, outward, 0.12f, bottom, top, 0.13f);
                            }
                            if (!simplified && (bay + floor + seed) % 4 == 0)
                                AddFacadeStrip(frames, windowCenter, direction, outward,
                                    0.075f, bottom, top, 0.135f);
                        }

                        if (!simplified && style is 3 or 6 && floor == 1)
                        {
                            for (var bay = 0; bay <= bayCount; bay += 2)
                            {
                                var along = -usableWidth * 0.5f + bayPitch * bay;
                                AddFacadeStrip(frames, edgeCenter + direction * along,
                                    direction, outward, 0.16f, 1.45f, height - 0.75f, 0.18f);
                            }
                        }
                    }
                }
            }
        }

        private static void AddFacadeIdentityFeatures(
            MeshAccumulator frames,
            MeshAccumulator brickAccents,
            MeshAccumulator roofTiles,
            MeshAccumulator timberScreens,
            MeshAccumulator glazing,
            Vector3 center,
            float width,
            float depth,
            float height,
            Vector3 roadDirection,
            Vector3 streetDirection,
            string areaType,
            int style,
            int seed,
            bool simplified)
        {
            if (simplified || height < 9f) return;
            roadDirection = Vector3.ProjectOnPlane(roadDirection, Vector3.up).normalized;
            streetDirection = Vector3.ProjectOnPlane(streetDirection, Vector3.up).normalized;
            if (roadDirection.sqrMagnitude < 0.5f || streetDirection.sqrMagnitude < 0.5f) return;

            var front = center + streetDirection * (depth * 0.5f + 0.14f);

            void AddSlab(MeshAccumulator target, float y, float span, float projection, float thickness)
            {
                var slabCenter = front + streetDirection * (projection * 0.5f);
                target.AddExtrudedPolygon(
                    OrientedRectangle(slabCenter, span, projection, roadDirection),
                    y, y + thickness);
            }

            void AddFin(MeshAccumulator target, float along, float bottom, float top, float finWidth, float projection)
            {
                var finCenter = front + roadDirection * along + streetDirection * (projection * 0.5f);
                target.AddExtrudedPolygon(
                    OrientedRectangle(finCenter, finWidth, projection, roadDirection),
                    bottom, top);
            }

            if (style is 5 or 7)
            {
                var span = width * (style == 7 ? 0.78f : 0.86f);
                var projection = style == 7 ? 1.35f : 1.05f;
                var floors = Mathf.Max(2, Mathf.FloorToInt((height - 3.7f) / 3.22f));
                for (var floor = 1; floor < floors; floor += 2)
                {
                    var slabY = 3.72f + floor * 3.22f;
                    if (slabY + 1.3f >= height) break;
                    AddSlab(roofTiles, slabY, span, projection, 0.16f);
                    AddFacadeStrip(
                        glazing,
                        front,
                        roadDirection,
                        streetDirection,
                        span * 0.94f,
                        slabY + 0.2f,
                        slabY + 1.12f,
                        projection + 0.08f);
                }
                AddFin(timberScreens, -span * 0.51f, 1.25f, height - 0.5f, 0.22f, 0.74f);
                AddFin(timberScreens, span * 0.51f, 1.25f, height - 0.5f, 0.22f, 0.74f);
            }
            else if (style is 3 or 6 or 9)
            {
                var finCount = style == 9 ? 4 : 5;
                var span = width * 0.78f;
                for (var index = 0; index < finCount; index++)
                {
                    var along = Mathf.Lerp(-span * 0.5f, span * 0.5f,
                        finCount == 1 ? 0.5f : index / (float)(finCount - 1));
                    AddFin(index % 2 == 0 ? brickAccents : frames,
                        along, 1.35f, height - 0.62f, index % 2 == 0 ? 0.28f : 0.16f, 0.82f);
                }
                AddSlab(frames, Mathf.Min(height * 0.58f, height - 4.2f), width * 0.88f, 0.66f, 0.2f);
            }
            else if (style == 8)
            {
                var span = width * 0.9f;
                for (var y = 4.25f; y < height - 1.25f; y += 3.35f)
                    AddSlab(roofTiles, y, span, 0.78f, 0.14f);
                foreach (var along in new[] { -span * 0.38f, 0f, span * 0.38f })
                    AddFin(frames, along, 0.16f, Mathf.Min(height - 0.45f, 6.2f), 0.28f, 1.15f);
            }
            else
            {
                var accent = (seed & 1) == 0 ? brickAccents : timberScreens;
                var span = width * 0.72f;
                AddFin(accent, -span * 0.5f, 1.3f, height - 0.58f, 0.32f, 0.68f);
                AddFin(accent, span * 0.5f, 1.3f, height - 0.58f, 0.32f, 0.68f);
                AddSlab(frames, height - 0.92f, width * 0.86f, 0.62f, 0.22f);
            }

            if (areaType is "commercial" or "exhibition_centre")
                AddSlab(timberScreens, 4.18f, width * 0.78f, 2.15f, 0.26f);
        }

        private static void AddPlotGroundTreatment(
            MeshAccumulator paving,
            MeshAccumulator planting,
            Vector3 center,
            float width,
            float depth,
            Vector3 roadDirection,
            Vector3 streetDirection,
            string areaType,
            float margin)
        {
            var landscaped = areaType is "residential" or "school" or "kindergarten";
            if (!landscaped)
            {
                paving.AddPolygon(
                    OrientedRectangle(center, width + margin, depth + margin, roadDirection), 0.082f);
                return;
            }

            // New-area residential and education plots read as planted courtyards,
            // with a compact entrance walk instead of a building-sized grey slab.
            planting.AddPolygon(
                OrientedRectangle(center, width + margin, depth + margin, roadDirection), 0.083f);
            var walkCenter = center + streetDirection * (depth * 0.5f + margin * 0.24f);
            paving.AddPolygon(
                OrientedRectangle(
                    walkCenter,
                    Mathf.Clamp(width * 0.18f, 4.2f, 7f),
                    margin * 0.9f,
                    roadDirection),
                0.093f);
        }

        private static void AddDistrictPlotTrees(
            MeshAccumulator trunks,
            MeshAccumulator crowns,
            Vector3 center,
            float width,
            float depth,
            Vector3 roadDirection,
            Vector3 streetDirection,
            string areaType,
            int seed)
        {
            var count = areaType is "residential" or "school" or "kindergarten"
                ? 4
                : areaType is "commercial" or "exhibition_centre" ? 2 : 1;
            for (var index = 0; index < count; index++)
            {
                var treeSeed = StableHash($"plot-tree:{seed}:{index}");
                var sideSign = (treeSeed & 1) == 0 ? -1f : 1f;
                var frontSign = index < 2 ? 1f : -1f;
                var point = center +
                            streetDirection * (depth * 0.5f + 2.35f) * frontSign +
                            roadDirection * (width * (0.26f + index % 2 * 0.12f) * sideSign);
                var height = 5.8f + treeSeed % 13 * 0.16f;
                AddPlanningTree(trunks, crowns, point, height, treeSeed);
            }
        }

        private static void AddPlanningTree(
            MeshAccumulator trunks, MeshAccumulator crowns,
            Vector3 point, float height, int seed)
        {
            trunks.AddCylinder(
                point + Vector3.up * height * 0.27f,
                height * 0.042f,
                height * 0.54f,
                5);
            var crownCenter = point + Vector3.up * height * 0.7f;
            var crownWidth = height * (0.23f + seed / 17 % 5 * 0.012f);
            crowns.AddEllipsoid(
                crownCenter,
                new Vector3(crownWidth, height * 0.25f, crownWidth * 0.84f),
                5,
                7);
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

        private static void ApplyGroupMemberVariation(
            string areaType, int memberSeed,
            ref float width, ref float depth, ref float height)
        {
            // Members of a planning group share the same base style and floor
            // band. Small dimensional changes prevent repetition without turning
            // the district back into a collection of unrelated random boxes.
            var widthFactor = 0.96f + memberSeed % 9 / 100f;
            var depthFactor = 0.96f + memberSeed / 11 % 9 / 100f;
            var heightStep = memberSeed / 101 % 3 - 1;
            width *= widthFactor;
            depth *= depthFactor;
            height += heightStep * (areaType is "kindergarten" or "industrial" ? 0.35f : 0.52f);
            height = Mathf.Max(8.5f, height);
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
                    width = 32f + seed % 17;
                    depth = 20f + seed / 7 % 9;
                    style = seed % 13 == 0 ? 4 : seed % 5 == 0 ? 9 : seed % 3 == 0 ? 6 : 3;
                    var commercialFloors = style == 4
                        ? 12 + seed / 13 % 4
                        : 7 + seed / 13 % 5;
                    height = commercialFloors * 3.28f;
                    break;
                case "school":
                    width = 40f + seed % 18;
                    depth = 18f + seed / 7 % 7;
                    height = (4 + seed / 13 % 3) * 3.25f;
                    style = seed % 3 == 0 ? 8 : seed % 4 == 0 ? 6 : seed % 5 == 0 ? 7 : 5;
                    break;
                case "kindergarten":
                    width = 25f + seed % 13;
                    depth = 17f + seed / 7 % 6;
                    height = (3 + seed / 13 % 2) * 3.18f;
                    style = seed % 3 == 0 ? 8 : seed % 2 == 0 ? 7 : 5;
                    break;
                case "industrial":
                    width = 42f + seed % 19;
                    depth = 23f + seed / 7 % 11;
                    height = (3 + seed / 13 % 3) * 3.2f;
                    style = 3;
                    break;
                case "exhibition_centre":
                    width = 46f + seed % 15;
                    depth = 24f + seed / 7 % 9;
                    height = (4 + seed / 13 % 4) * 3.35f;
                    style = seed % 2 == 0 ? 8 : 6;
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
                    width = 34f + seed % 14;
                    depth = 20f + seed / 7 % 7;
                    height = (6 + seed / 13 % 6) * 3.18f;
                    var residentialVariant = seed % 10;
                    style = residentialVariant < 3 ? 7 : residentialVariant < 5 ? 9 : residentialVariant < 8 ? 5 : 1;
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
                         new Vector3(-57f, 0f, -57f), new Vector3(57f, 0f, -57f),
                         new Vector3(-57f, 0f, 57f), new Vector3(57f, 0f, 57f),
                     })
            {
                paving.AddPolygon(Rectangle(center + offset, 86f, 86f), 0.082f);
                pocketGreen.AddPolygon(Rectangle(center + offset, 80f, 80f), 0.094f);
                var signX = Mathf.Sign(offset.x);
                var signZ = Mathf.Sign(offset.z);
                planterEdges.AddBox(center + offset + new Vector3(-signX * 35f, 0.17f, 0f), new Vector3(0.44f, 0.34f, 58f));
                planterEdges.AddBox(center + offset + new Vector3(0f, 0.17f, -signZ * 35f), new Vector3(58f, 0.34f, 0.44f));
                for (var segment = -5; segment <= 5; segment++)
                {
                    var heightVariation = 0.68f + (segment + 6) % 3 * 0.08f;
                    shrubMasses.AddEllipsoid(
                        center + offset + new Vector3(-signX * 33.5f, heightVariation, segment * 5.15f),
                        new Vector3(1.05f, heightVariation, 1.35f), 12, 18);
                    shrubMasses.AddEllipsoid(
                        center + offset + new Vector3(segment * 5.15f, heightVariation, -signZ * 33.5f),
                        new Vector3(1.35f, heightVariation, 1.05f), 12, 18);
                }
            }
            paving.Build("Showcase corner paving", scene.Materials.HeroSidewalk, parent, false);
            pocketGreen.Build("Showcase corner planting", scene.Materials.HeroGrass, parent, false);
            planterEdges.Build("Showcase stone planter edges", scene.Materials.Curb, parent);
            shrubMasses.Build("Showcase clipped evergreen hedge masses", scene.Materials.ShrubLeaves, parent);
        }

        private static void CreateShowcaseBoulevardMedians(
            SceneBuilder scene, Transform parent, Vector3 center)
        {
            // The screenshot junction gets complete physical median islands.
            // Every curb, planting bed, shrub and tree is mesh geometry.
            var planting = new MeshAccumulator();
            var curb = new MeshAccumulator();
            var shrubs = new MeshAccumulator();
            var trunks = new MeshAccumulator();
            var crowns = new MeshAccumulator();
            foreach (var direction in new[]
                     {
                         Vector3.forward, Vector3.back, Vector3.right, Vector3.left,
                     })
            {
                const float islandLength = 66f;
                const float islandWidth = 5.8f;
                var islandCenter = center + direction * 57f;
                var alongZ = Mathf.Abs(direction.z) > 0.5f;
                var width = alongZ ? islandWidth : islandLength;
                var depth = alongZ ? islandLength : islandWidth;
                planting.AddPolygon(
                    Rectangle(islandCenter, width - 0.8f, depth - 0.8f), 0.112f);

                if (alongZ)
                {
                    curb.AddBox(islandCenter + Vector3.right * (islandWidth * 0.5f),
                        new Vector3(0.42f, 0.34f, islandLength));
                    curb.AddBox(islandCenter - Vector3.right * (islandWidth * 0.5f),
                        new Vector3(0.42f, 0.34f, islandLength));
                    curb.AddBox(islandCenter + Vector3.forward * (islandLength * 0.5f),
                        new Vector3(islandWidth, 0.34f, 0.42f));
                    curb.AddBox(islandCenter - Vector3.forward * (islandLength * 0.5f),
                        new Vector3(islandWidth, 0.34f, 0.42f));
                }
                else
                {
                    curb.AddBox(islandCenter + Vector3.forward * (islandWidth * 0.5f),
                        new Vector3(islandLength, 0.34f, 0.42f));
                    curb.AddBox(islandCenter - Vector3.forward * (islandWidth * 0.5f),
                        new Vector3(islandLength, 0.34f, 0.42f));
                    curb.AddBox(islandCenter + Vector3.right * (islandLength * 0.5f),
                        new Vector3(0.42f, 0.34f, islandWidth));
                    curb.AddBox(islandCenter - Vector3.right * (islandLength * 0.5f),
                        new Vector3(0.42f, 0.34f, islandWidth));
                }

                for (var index = -3; index <= 3; index++)
                {
                    var point = islandCenter + direction * index * 8.1f;
                    var radius = index % 2 == 0
                        ? new Vector3(1.15f, 0.72f, 1f)
                        : new Vector3(0.95f, 0.64f, 1.15f);
                    shrubs.AddEllipsoid(point + Vector3.up * radius.y, radius, 6, 10);
                }

                foreach (var offset in new[] { -21f, 0f, 21f })
                {
                    var point = islandCenter + direction * offset;
                    var height = 5.6f + Mathf.Abs(offset) * 0.018f;
                    trunks.AddCylinder(point + Vector3.up * height * 0.3f,
                        0.16f, height * 0.6f, 10);
                    crowns.AddEllipsoid(point + Vector3.up * height * 0.76f,
                        new Vector3(1.75f, height * 0.28f, 1.55f), 8, 12);
                    crowns.AddEllipsoid(
                        point + Vector3.up * height * 0.9f + direction * 0.25f,
                        new Vector3(1.32f, height * 0.22f, 1.42f), 7, 11);
                }
            }
            planting.Build("K08 四向实体中央绿化岛", scene.Materials.HeroGrass, parent, false);
            curb.Build("K08 四向花岗岩中央分隔缘石", scene.Materials.Curb, parent, true);
            shrubs.Build("K08 中央分隔带常绿灌木", scene.Materials.ShrubLeaves, parent, true);
            trunks.Build("K08 中央分隔带乔木树干", scene.Materials.FormalTreeBranches, parent, true);
            crowns.Build("K08 中央分隔带多层乔木树冠", scene.Materials.FormalTreeLeaves, parent, true);
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
                new Vector3(49f, 0f, 48f), new Vector3(37f, 0f, 54f),
                new Vector3(-64f, 0f, -63f), new Vector3(64f, 0f, -63f),
                new Vector3(-64f, 0f, 63f), new Vector3(64f, 0f, 63f),
            });
            foreach (var offset in offsets.Distinct())
            {
                var seed = StableHash(offset.ToString());
                var height = 10.6f + seed % 17 * 0.15f;
                if (treeSource != null)
                    CreatePbrBoulevardTree(
                        scene, treeSource,
                        center + offset,
                        height, seed);
                else
                    CreateBoulevardTree(scene, center + offset, height, seed);
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
                renderer.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
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
            foreach (var renderer in root.GetComponentsInChildren<Renderer>(true))
                renderer.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
        }

        private static void CreateRoadsideDevice(
            string id, string type, string provenance,
            Vector3 position, Vector3 facingTarget, SceneBuilder scene)
        {
            var root = new GameObject(id);
            root.transform.SetParent(scene.transform, false);
            var forward = Vector3.ProjectOnPlane(facingTarget - position, Vector3.up).normalized;
            if (forward.sqrMagnitude < 0.5f) forward = Vector3.forward;
            root.transform.SetPositionAndRotation(position, Quaternion.LookRotation(forward, Vector3.up));
            var selectable = root.AddComponent<SelectableObject>();
            selectable.Identifier = id;
            selectable.Kind = type;
            selectable.Provenance = provenance;
            CreatePrimitive(PrimitiveType.Cylinder, "设备杆", root.transform,
                new Vector3(0f, 2.55f, 0f), new Vector3(0.1f, 2.55f, 0.1f), scene.Materials.Metal);
            CreatePrimitive(PrimitiveType.Cube, "设备安装臂", root.transform,
                new Vector3(0f, 5.02f, 0.22f), new Vector3(0.08f, 0.08f, 0.52f), scene.Materials.Metal);
            if (type == "camera")
            {
                CreatePrimitive(PrimitiveType.Cube, "道路摄像机", root.transform,
                    new Vector3(0f, 5.12f, 0.53f), new Vector3(0.42f, 0.28f, 0.72f), scene.Materials.Metal);
                CreatePrimitive(PrimitiveType.Sphere, "摄像机镜头", root.transform,
                    new Vector3(0f, 5.12f, 0.91f), new Vector3(0.13f, 0.13f, 0.08f), scene.Materials.BuildingGlass);
            }
            else
            {
                CreatePrimitive(PrimitiveType.Cube, "C-V2X RSU", root.transform,
                    new Vector3(0f, 5.18f, 0.43f), new Vector3(0.54f, 0.68f, 0.28f), scene.Materials.Metal);
                CreatePrimitive(PrimitiveType.Sphere, "RSU状态灯", root.transform,
                    new Vector3(0f, 5.18f, 0.59f), Vector3.one * 0.075f, scene.Materials.BuildingGlass);
            }
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
