using System.Collections.Generic;
using System.Linq;
using UnityEngine;
using Xiongan.DigitalTwin.Core;

namespace Xiongan.DigitalTwin.Scene
{
    public static class ReferenceShowcaseBuilder
    {
        private readonly struct BuildingSpec
        {
            public BuildingSpec(
                float across, float along, float width, float depth,
                float height, int material, bool civic = false)
            {
                Across = across;
                Along = along;
                Width = width;
                Depth = depth;
                Height = height;
                Material = material;
                Civic = civic;
            }

            public float Across { get; }
            public float Along { get; }
            public float Width { get; }
            public float Depth { get; }
            public float Height { get; }
            public int Material { get; }
            public bool Civic { get; }
        }

        public static void Build(SceneBuilder scene, Transform parent)
        {
            var frame = ReferenceShowcaseLayout.Resolve(scene);
            var root = new GameObject("B01参考图真三维展示区");
            root.transform.SetParent(parent, false);
            BuildGroundAndBoulevards(scene, root.transform, frame);
            BuildRoadMarkings(scene, root.transform, frame);
            BuildArchitecture(scene, root.transform, frame);
            BuildPlantingAndStreetFurniture(scene, root.transform, frame);
        }

        private static void BuildGroundAndBoulevards(
            SceneBuilder scene, Transform parent, ReferenceShowcaseFrame frame)
        {
            var ground = new MeshAccumulator();
            var asphalt = new MeshAccumulator();
            var sidewalk = new MeshAccumulator();
            var planting = new MeshAccumulator();
            var curb = new MeshAccumulator();
            var shrubs = new MeshAccumulator();

            foreach (var across in new[] { -88f, 88f })
            foreach (var along in new[] { -88f, 88f })
                ground.AddPolygon(frame.Rectangle(across, along, 124f, 124f), 0.018f);

            // One concave polygon owns the complete B01 carriageway. Separate
            // crossing rectangles produced overlapping top faces and zoom-time
            // depth fighting at every road seam.
            asphalt.AddPolygon(new[]
            {
                frame.Point(-26f, 0f, -180f), frame.Point(26f, 0f, -180f),
                frame.Point(26f, 0f, -25f), frame.Point(147f, 0f, -25f),
                frame.Point(147f, 0f, 25f), frame.Point(26f, 0f, 25f),
                frame.Point(26f, 0f, 180f), frame.Point(-26f, 0f, 180f),
                frame.Point(-26f, 0f, 25f), frame.Point(-147f, 0f, 25f),
                frame.Point(-147f, 0f, -25f), frame.Point(-26f, 0f, -25f),
            }, 0.09f);

            foreach (var across in new[] { -30.4f, 30.4f })
                sidewalk.AddPolygon(frame.Rectangle(across, 0f, 7.8f, 360f), 0.105f);
            foreach (var along in new[] { -29.4f, 29.4f })
                sidewalk.AddPolygon(frame.Rectangle(0f, along, 294f, 7.8f), 0.106f);

            AddMedian(frame, planting, curb, shrubs, 0f, -108f, 5.8f, 138f, true);
            AddMedian(frame, planting, curb, shrubs, 0f, 108f, 5.8f, 138f, true);
            AddMedian(frame, planting, curb, shrubs, -96f, 0f, 118f, 5.2f, false);
            AddMedian(frame, planting, curb, shrubs, 96f, 0f, 118f, 5.2f, false);

            foreach (var across in new[] { -26.2f, 26.2f })
                curb.AddExtrudedRibbon(
                    new[] { frame.Point(across, 0f, -180f), frame.Point(across, 0f, 180f) },
                    0.38f, 0.09f, 0.27f);
            foreach (var along in new[] { -25.2f, 25.2f })
                curb.AddExtrudedRibbon(
                    new[] { frame.Point(-147f, 0f, along), frame.Point(147f, 0f, along) },
                    0.38f, 0.091f, 0.27f);

            ground.Build("B01四角连续城市绿地", scene.Materials.HeroGrass, parent, false);
            asphalt.Build("B01宽幅连续程序化沥青", scene.Materials.HeroAsphalt, parent);
            sidewalk.Build("B01宽幅实体人行道", scene.Materials.HeroSidewalk, parent, false);
            planting.Build("B01中央林荫隔离带", scene.Materials.HeroGrass, parent, false);
            curb.Build("B01花岗岩实体路缘", scene.Materials.Curb, parent, true);
            shrubs.Build("B01中央隔离带灌木", scene.Materials.ShrubLeaves, parent, true);
        }

        private static void AddMedian(
            ReferenceShowcaseFrame frame, MeshAccumulator planting, MeshAccumulator curb,
            MeshAccumulator shrubs, float across, float along, float width, float depth, bool longitudinal)
        {
            planting.AddPolygon(frame.Rectangle(across, along, width - 0.7f, depth - 0.7f), 0.14f);
            var polygon = frame.Rectangle(across, along, width, depth);
            for (var index = 0; index < polygon.Count; index++)
                curb.AddExtrudedRibbon(
                    new[] { polygon[index], polygon[(index + 1) % polygon.Count] },
                    0.34f, 0.09f, 0.31f);
            var count = longitudinal ? 39 : 31;
            for (var index = 0; index < count; index++)
            {
                var offset = Mathf.Lerp(-0.445f, 0.445f, index / (float)(count - 1));
                var lateral = (index % 2 == 0 ? -1f : 1f) * (0.5f + index % 3 * 0.18f);
                var shrubHeight = 0.43f + index % 4 * 0.055f;
                var point = longitudinal
                    ? frame.Point(across + lateral, shrubHeight, along + depth * offset)
                    : frame.Point(across + width * offset, shrubHeight, along + lateral);
                shrubs.AddEllipsoid(point,
                    longitudinal
                        ? new Vector3(1.02f + index % 3 * 0.13f, shrubHeight, 1.28f + index % 5 * 0.08f)
                        : new Vector3(1.28f + index % 5 * 0.08f, shrubHeight, 1.02f + index % 3 * 0.13f),
                    7, 10);
            }
        }

        private static void BuildRoadMarkings(
            SceneBuilder scene, Transform parent, ReferenceShowcaseFrame frame)
        {
            var markings = new MeshAccumulator();
            const float paintHeight = 0.108f;

            foreach (var sign in new[] { -1f, 1f })
            foreach (var offset in new[] { 8.6f, 14.4f, 20.2f })
            {
                AddDashedLine(markings, frame.Point(sign * offset, 0f, -176f),
                    frame.Point(sign * offset, 0f, -34f), paintHeight);
                AddDashedLine(markings, frame.Point(sign * offset, 0f, 34f),
                    frame.Point(sign * offset, 0f, 176f), paintHeight);
            }
            foreach (var sign in new[] { -1f, 1f })
            foreach (var offset in new[] { 8.1f, 13.75f, 19.4f })
            {
                AddDashedLine(markings, frame.Point(-144f, 0f, sign * offset),
                    frame.Point(-34f, 0f, sign * offset), paintHeight);
                AddDashedLine(markings, frame.Point(34f, 0f, sign * offset),
                    frame.Point(144f, 0f, sign * offset), paintHeight);
            }

            AddCrosswalk(markings, frame, true, -29.1f, paintHeight);
            AddCrosswalk(markings, frame, true, 29.1f, paintHeight);
            AddCrosswalk(markings, frame, false, -30.1f, paintHeight);
            AddCrosswalk(markings, frame, false, 30.1f, paintHeight);

            AddStopLine(markings, frame, true, -33.2f, 1f, paintHeight);
            AddStopLine(markings, frame, true, 33.2f, -1f, paintHeight);
            AddStopLine(markings, frame, false, -34.2f, 1f, paintHeight);
            AddStopLine(markings, frame, false, 34.2f, -1f, paintHeight);

            var laneCenters = new[] { 5.7f, 11.5f, 17.3f, 23.1f };
            // The reference view uses three through arrows and a curb-side
            // through/right arrow. The scene frame is mirrored from SUMO, so
            // the visual curb-side branch is represented by the local "l" head.
            var directions = new[] { "s", "s", "s", "sl" };
            for (var lane = 0; lane < laneCenters.Length; lane++)
            {
                foreach (var along in new[] { -47f, -64f })
                {
                    markings.AddArrow(frame.Point(laneCenters[lane], 0f, along),
                        frame.Forward, directions[lane], paintHeight, 1.08f);
                }
                foreach (var along in new[] { 47f, 64f })
                {
                    markings.AddArrow(frame.Point(-laneCenters[lane], 0f, along),
                        -frame.Forward, directions[lane], paintHeight, 1.08f);
                }
                foreach (var across in new[] { -48f, -66f })
                {
                    markings.AddArrow(frame.Point(across, 0f, -laneCenters[lane]),
                        frame.Right, directions[lane], paintHeight, 1.06f);
                }
                foreach (var across in new[] { 48f, 66f })
                {
                    markings.AddArrow(frame.Point(across, 0f, laneCenters[lane]),
                        -frame.Right, directions[lane], paintHeight, 1.06f);
                }
            }
            markings.Build("B01对称车道线导向箭头与斑马线", scene.Materials.Marking,
                parent, false, SceneDetailClass.Fine);
        }

        private static void AddDashedLine(
            MeshAccumulator target, Vector3 from, Vector3 to, float height)
        {
            var direction = to - from;
            direction.y = 0f;
            var length = direction.magnitude;
            if (length < 1f) return;
            direction /= length;
            const float cycle = 8.4f;
            const float dash = 4.7f;
            for (var start = 0.8f; start < length; start += cycle)
            {
                var end = Mathf.Min(start + dash, length);
                target.AddRibbon(new[] { from + direction * start, from + direction * end },
                    0.14f, height, 1f);
            }
        }

        private static void AddCrosswalk(
            MeshAccumulator target, ReferenceShowcaseFrame frame,
            bool longitudinalRoad, float position, float height)
        {
            for (var stripe = -5; stripe <= 5; stripe++)
            {
                var offset = stripe * 0.7f;
                if (longitudinalRoad)
                {
                    var center = frame.Point(0f, 0f, position + offset);
                    foreach (var sign in new[] { -1f, 1f })
                        target.AddRibbon(new[]
                        {
                            center + frame.Right * sign * 3.35f,
                            center + frame.Right * sign * 25.4f,
                        }, 0.34f, height, 1f);
                }
                else
                {
                    var center = frame.Point(position + offset, 0f, 0f);
                    foreach (var sign in new[] { -1f, 1f })
                        target.AddRibbon(new[]
                        {
                            center + frame.Forward * sign * 3.05f,
                            center + frame.Forward * sign * 24.4f,
                        }, 0.34f, height, 1f);
                }
            }
        }

        private static void AddStopLine(
            MeshAccumulator target, ReferenceShowcaseFrame frame,
            bool longitudinalRoad, float position, float sideSign, float height)
        {
            if (longitudinalRoad)
                target.AddRibbon(new[]
                {
                    frame.Point(sideSign * 3.4f, 0f, position),
                    frame.Point(sideSign * 25.2f, 0f, position),
                }, 0.42f, height, 1f);
            else
                target.AddRibbon(new[]
                {
                    frame.Point(position, 0f, sideSign * 3.2f),
                    frame.Point(position, 0f, sideSign * 24.2f),
                }, 0.42f, height, 1f);
        }

        private static void BuildArchitecture(
            SceneBuilder scene, Transform parent, ReferenceShowcaseFrame frame)
        {
            var specs = new[]
            {
                new BuildingSpec(-91f, 82f, 50f, 27f, 15.4f, 0),
                new BuildingSpec(-106f, 126f, 42f, 25f, 18.2f, 3),
                new BuildingSpec(-78f, 169f, 44f, 23f, 15.8f, 6),
                new BuildingSpec(87f, 82f, 60f, 28f, 15.8f, 1, true),
                new BuildingSpec(108f, 132f, 42f, 25f, 18.6f, 4),
                new BuildingSpec(78f, 174f, 44f, 23f, 16.2f, 7),
            };
            var facades = Enumerable.Range(0, scene.Materials.Facades.Count)
                .Select(_ => new MeshAccumulator()).ToArray();
            var roofs = new MeshAccumulator();
            var parapets = new MeshAccumulator();
            var glazing = new MeshAccumulator();
            var frames = new MeshAccumulator();
            var stone = new MeshAccumulator();
            var civicPanels = new MeshAccumulator();
            var metal = new MeshAccumulator();

            foreach (var spec in specs)
            {
                AddBuilding(frame, spec, facades[spec.Material % facades.Length], roofs,
                    parapets, glazing, frames, stone, civicPanels, metal);
            }

            for (var index = 0; index < facades.Length; index++)
                facades[index].Build($"B01定制建筑立面-{index + 1}", scene.Materials.Facades[index], parent);
            roofs.Build("B01定制建筑屋面", scene.Materials.BuildingRoof, parent);
            parapets.Build("B01定制建筑女儿墙", scene.Materials.GreyRoofTile, parent, true, SceneDetailClass.Fine);
            glazing.Build("B01定制建筑实体窗格", scene.Materials.BuildingGlass, parent, false, SceneDetailClass.Fine);
            frames.Build("B01定制建筑窗框和层间线", scene.Materials.FacadeFrame, parent, true, SceneDetailClass.Fine);
            stone.Build("B01定制建筑石材首层", scene.Materials.ArchitecturalStone, parent, true, SceneDetailClass.Context);
            civicPanels.Build("B01公共建筑浅色竖向肋片", scene.Materials.CivicCladding, parent, true, SceneDetailClass.Context);
            metal.Build("B01定制建筑雨棚和竖向构件", scene.Materials.Metal, parent, true, SceneDetailClass.Fine);
            scene.RegisterGeneratedBuildings(specs.Length);
        }

        private static void AddBuilding(
            ReferenceShowcaseFrame frame, BuildingSpec spec,
            MeshAccumulator facade, MeshAccumulator roofs, MeshAccumulator parapets,
            MeshAccumulator glazing, MeshAccumulator frames, MeshAccumulator stone,
            MeshAccumulator civicPanels, MeshAccumulator metal)
        {
            var footprint = frame.Rectangle(spec.Across, spec.Along, spec.Width, spec.Depth);
            facade.AddFacadeWalls(footprint, 0.09f, spec.Height, 8f);
            roofs.AddPolygon(footprint, spec.Height + 0.04f);
            parapets.AddFacadeWalls(footprint, spec.Height, spec.Height + 0.72f, 6f);
            stone.AddFacadeWalls(footprint, 0.1f, spec.Civic ? 5.2f : 3.8f, 6f);
            if (!spec.Civic)
                AddFacadeWindows(footprint, spec.Height, glazing, frames, false);

            if (spec.Civic)
            {
                // Keep the ceremonial curtain wall on the street-facing edge,
                // but give the other three elevations the same authored depth
                // as the surrounding district instead of leaving blank slabs.
                AddCivicSideWalls(footprint, spec.Height, facade, stone);
                AddFacadeWindows(footprint, spec.Height, glazing, frames, true, 0);
                AddCivicFacade(frame, spec, glazing, civicPanels, metal);
                var podium = frame.Rectangle(spec.Across, spec.Along - spec.Depth * 0.36f,
                    spec.Width * 0.84f, 8.5f);
                stone.AddExtrudedPolygon(podium, 0.1f, 5.4f);
                var canopy = frame.Rectangle(spec.Across, spec.Along - spec.Depth * 0.62f,
                    spec.Width * 0.55f, 5.4f);
                metal.AddExtrudedPolygon(canopy, 4.85f, 5.18f);
                var hallCenterAcross = spec.Across - spec.Width * 0.42f;
                var hallCenterAlong = spec.Along - spec.Depth * 0.45f;
                var mainFrontAlong = spec.Along - spec.Depth * 0.5f;
                const float hallReveal = 1.35f;
                var hall = CreateCivicHallFootprint(
                    frame, hallCenterAcross, hallCenterAlong, mainFrontAlong,
                    11.8f, 12.8f, hallReveal, 18);
                stone.AddFacadeWalls(hall, 0.1f, 9.2f, 3.8f);
                roofs.AddPolygon(hall, 9.24f);
                for (var segment = 0; segment < hall.Count; segment++)
                {
                    var from = hall[segment];
                    var to = hall[(segment + 1) % hall.Count];
                    var edgeCenter = (from + to) * 0.5f;
                    var outward = Vector3.ProjectOnPlane(
                        edgeCenter - frame.Point(hallCenterAcross, 0f, hallCenterAlong), Vector3.up).normalized;
                    AddOutwardQuad(glazing,
                        from + outward * 0.08f + Vector3.up * 1.8f,
                        to + outward * 0.08f + Vector3.up * 1.8f,
                        to + outward * 0.08f + Vector3.up * 7.55f,
                        from + outward * 0.08f + Vector3.up * 7.55f,
                        outward);
                    if (segment % 2 == 0)
                        civicPanels.AddCylinder(edgeCenter + Vector3.up * 5.05f,
                            0.18f, 7.1f, 8);
                }
                var hallCutAlong = mainFrontAlong - hallReveal;
                var connector = frame.Rectangle(
                    hallCenterAcross,
                    (hallCutAlong + mainFrontAlong) * 0.5f,
                    8.4f,
                    hallReveal + 0.24f);
                stone.AddExtrudedPolygon(connector, 0.08f, 1.05f);
                glazing.AddExtrudedPolygon(connector, 1.02f, 7.35f);
                metal.AddExtrudedPolygon(connector, 7.34f, 7.66f);
                for (var tier = 0; tier < 3; tier++)
                {
                    var tierCanopy = frame.Rectangle(
                        spec.Across - spec.Width * 0.18f,
                        spec.Along - spec.Depth * (0.55f + tier * 0.055f),
                        spec.Width * (0.62f - tier * 0.06f),
                        3.2f + tier * 0.65f);
                    metal.AddExtrudedPolygon(tierCanopy, 4.7f + tier * 0.22f, 4.88f + tier * 0.22f);
                }
            }
            else
            {
                var roofPlant = frame.Rectangle(
                    spec.Across + spec.Width * 0.16f,
                    spec.Along,
                    Mathf.Min(8f, spec.Width * 0.22f),
                    Mathf.Min(5f, spec.Depth * 0.24f));
                roofs.AddExtrudedPolygon(roofPlant, spec.Height + 0.05f, spec.Height + 2.1f);
            }
        }

        public static List<Vector3> CreateCivicHallFootprint(
            ReferenceShowcaseFrame frame,
            float centerAcross,
            float centerAlong,
            float mainFrontAlong,
            float acrossRadius,
            float alongRadius,
            float facadeReveal,
            int arcSegments)
        {
            acrossRadius = Mathf.Max(0.1f, acrossRadius);
            alongRadius = Mathf.Max(0.1f, alongRadius);
            arcSegments = Mathf.Max(6, arcSegments);
            var cutAlong = mainFrontAlong - Mathf.Max(0.05f, facadeReveal);
            var normalizedCut = Mathf.Clamp(
                (cutAlong - centerAlong) / alongRadius, -0.95f, 0.95f);
            var cutAngle = Mathf.Asin(normalizedCut);
            var startAngle = Mathf.PI - cutAngle;
            var endAngle = Mathf.PI * 2f + cutAngle;
            var hall = new List<Vector3>(arcSegments + 1);
            for (var segment = 0; segment <= arcSegments; segment++)
            {
                var angle = Mathf.Lerp(startAngle, endAngle, segment / (float)arcSegments);
                hall.Add(frame.Point(
                    centerAcross + Mathf.Cos(angle) * acrossRadius,
                    0f,
                    centerAlong + Mathf.Sin(angle) * alongRadius));
            }
            return hall;
        }

        private static void AddCivicFacade(
            ReferenceShowcaseFrame frame, BuildingSpec spec,
            MeshAccumulator glazing, MeshAccumulator lightPanels, MeshAccumulator metal)
        {
            var frontAlong = spec.Along - spec.Depth * 0.5f - 0.08f;
            var left = frame.Point(spec.Across - spec.Width * 0.47f, 0f, frontAlong);
            var right = frame.Point(spec.Across + spec.Width * 0.47f, 0f, frontAlong);
            AddOutwardQuad(glazing,
                left + Vector3.up * 4.2f,
                right + Vector3.up * 4.2f,
                right + Vector3.up * (spec.Height - 1.1f),
                left + Vector3.up * (spec.Height - 1.1f),
                -frame.Forward);

            for (var offset = -0.44f; offset <= 0.44f; offset += 0.088f)
            {
                var fin = frame.Rectangle(
                    spec.Across + spec.Width * offset,
                    frontAlong - 0.16f,
                    1.05f, 0.48f);
                lightPanels.AddExtrudedPolygon(fin, 4.05f, spec.Height + 0.32f);
            }

            foreach (var y in new[] { 4.05f, spec.Height - 0.92f })
            {
                var band = frame.Rectangle(spec.Across, frontAlong - 0.34f,
                    spec.Width * 0.96f, 0.42f);
                lightPanels.AddExtrudedPolygon(band, y - 0.18f, y + 0.18f);
            }

            var fascia = frame.Rectangle(spec.Across, frontAlong - 0.33f,
                spec.Width * 0.98f, 0.5f);
            lightPanels.AddExtrudedPolygon(fascia, spec.Height - 1.05f, spec.Height + 0.65f);

            var roofCrown = frame.Rectangle(spec.Across, spec.Along,
                spec.Width * 1.035f, spec.Depth * 1.04f);
            metal.AddExtrudedPolygon(roofCrown, spec.Height + 0.12f, spec.Height + 0.46f);
        }

        private static void AddCivicSideWalls(
            IReadOnlyList<Vector3> footprint,
            float height,
            MeshAccumulator facade,
            MeshAccumulator stone)
        {
            var center = footprint.Aggregate(Vector3.zero, (sum, point) => sum + point) /
                         footprint.Count;
            for (var edgeIndex = 1; edgeIndex < footprint.Count; edgeIndex++)
            {
                var from = footprint[edgeIndex];
                var to = footprint[(edgeIndex + 1) % footprint.Count];
                var edgeCenter = (from + to) * 0.5f;
                var outward = Vector3.ProjectOnPlane(edgeCenter - center, Vector3.up).normalized;
                AddOutwardQuad(
                    facade,
                    from + Vector3.up * 5.16f,
                    to + Vector3.up * 5.16f,
                    to + Vector3.up * height,
                    from + Vector3.up * height,
                    outward);
                AddOutwardQuad(
                    stone,
                    from + Vector3.up * 0.08f,
                    to + Vector3.up * 0.08f,
                    to + Vector3.up * 5.2f,
                    from + Vector3.up * 5.2f,
                    outward);
            }
        }

        private static void AddFacadeWindows(
            IReadOnlyList<Vector3> footprint, float height,
            MeshAccumulator glazing, MeshAccumulator frames, bool civic,
            int skippedEdge = -1)
        {
            var center = footprint.Aggregate(Vector3.zero, (sum, point) => sum + point) / footprint.Count;
            var floorHeight = civic ? 3.6f : 3.25f;
            for (var edgeIndex = 0; edgeIndex < footprint.Count; edgeIndex++)
            {
                if (edgeIndex == skippedEdge) continue;
                var from = footprint[edgeIndex];
                var to = footprint[(edgeIndex + 1) % footprint.Count];
                var direction = Vector3.ProjectOnPlane(to - from, Vector3.up);
                var length = direction.magnitude;
                if (length < 5f) continue;
                direction /= length;
                var edgeCenter = (from + to) * 0.5f;
                var outward = Vector3.ProjectOnPlane(edgeCenter - center, Vector3.up).normalized;
                var modules = Mathf.Max(2, Mathf.FloorToInt(length / (civic ? 4.1f : 3.4f)));
                var moduleWidth = length / modules;
                for (var floor = 1; ; floor++)
                {
                    var y = 2.25f + floor * floorHeight;
                    if (y + 0.95f >= height) break;
                    for (var module = 0; module < modules; module++)
                    {
                        var paneCenter = from + direction * (moduleWidth * (module + 0.5f)) +
                                         outward * 0.07f + Vector3.up * y;
                        AddOutwardQuad(glazing,
                            paneCenter - direction * moduleWidth * 0.32f - Vector3.up * 0.88f,
                            paneCenter + direction * moduleWidth * 0.32f - Vector3.up * 0.88f,
                            paneCenter + direction * moduleWidth * 0.32f + Vector3.up * 0.88f,
                            paneCenter - direction * moduleWidth * 0.32f + Vector3.up * 0.88f,
                            outward);
                    }
                    var bandCenter = edgeCenter + outward * 0.085f + Vector3.up * (y - 1.2f);
                    AddOutwardQuad(frames,
                        bandCenter - direction * length * 0.48f - Vector3.up * 0.07f,
                        bandCenter + direction * length * 0.48f - Vector3.up * 0.07f,
                        bandCenter + direction * length * 0.48f + Vector3.up * 0.07f,
                        bandCenter - direction * length * 0.48f + Vector3.up * 0.07f,
                        outward);
                }
            }
        }

        private static void AddOutwardQuad(
            MeshAccumulator target, Vector3 a, Vector3 b, Vector3 c, Vector3 d, Vector3 outward)
        {
            if (Vector3.Dot(Vector3.Cross(b - a, c - a), outward) >= 0f) target.AddQuad(a, b, c, d);
            else target.AddQuad(b, a, d, c);
        }

        private static void BuildPlantingAndStreetFurniture(
            SceneBuilder scene, Transform parent, ReferenceShowcaseFrame frame)
        {
            var trunks = new MeshAccumulator();
            var crowns = new MeshAccumulator();
            var shrubs = new MeshAccumulator();
            var lamps = new MeshAccumulator();
            var lampHeads = new MeshAccumulator();
            var seed = 0;

            foreach (var across in new[] { -37.2f, 37.2f })
            foreach (var along in new[] { -72f, -53f, 47f, 63f, 79f, 96f, 114f, 133f, 153f, 174f })
                AddTree(frame.Point(across, 0f, along), seed++, trunks, crowns);
            foreach (var along in new[] { -35.5f, 35.5f })
            foreach (var across in new[] { -132f, -108f, -84f, -58f, 58f, 84f, 108f, 132f })
                AddTree(frame.Point(across, 0f, along), seed++, trunks, crowns);
            foreach (var across in new[] { -32.2f, 32.2f })
            for (var along = -145f; along <= 145f; along += 18f)
            {
                if (Mathf.Abs(along) < 38f) continue;
                AddLamp(frame, across, along, lamps, lampHeads);
            }
            foreach (var along in new[] { -31.2f, 31.2f })
            for (var across = -125f; across <= 125f; across += 22f)
            {
                if (Mathf.Abs(across) < 38f) continue;
                AddLamp(frame, across, along, lamps, lampHeads);
            }
            foreach (var across in new[] { -41f, 41f })
            for (var along = -150f; along <= 150f; along += 7.5f)
            {
                if (Mathf.Abs(along) < 36f) continue;
                shrubs.AddEllipsoid(frame.Point(across, 0.58f, along),
                    new Vector3(0.92f, 0.58f, 1.42f), 7, 9);
            }

            foreach (var alongStart in new[] { -60f, 43f })
            for (var along = alongStart; along <= (alongStart < 0f ? -43f : 164f); along += 13.4f)
            {
                AddMedianTree(frame.Point(0f, 0f, along), seed++, trunks, crowns);
            }

            trunks.Build("B01多层行道树树干", scene.Materials.FormalTreeBranches, parent, true);
            crowns.Build("B01不规则多层行道树树冠", scene.Materials.FormalTreeLeaves, parent, true);
            shrubs.Build("B01道路连续绿篱", scene.Materials.ShrubLeaves, parent, true);
            lamps.Build("B01真实尺度路灯杆", scene.Materials.Metal, parent, false);
            lampHeads.Build("B01真实尺度路灯头", scene.Materials.SignalDark, parent, false);
        }

        private static void AddTree(
            Vector3 position, int seed, MeshAccumulator trunks, MeshAccumulator crowns)
        {
            var height = 8.8f + seed % 5 * 0.5f;
            trunks.AddCylinder(position + Vector3.up * height * 0.34f, 0.2f, height * 0.68f, 9);
            for (var cluster = 0; cluster < 10; cluster++)
            {
                var angle = (seed * 0.73f + cluster * 2.399f) % (Mathf.PI * 2f);
                var radius = 0.62f + (seed * 17 + cluster * 13) % 7 * 0.2f;
                var center = position + new Vector3(
                    Mathf.Cos(angle) * radius,
                    height * (0.62f + (cluster % 5) * 0.07f),
                    Mathf.Sin(angle) * radius);
                var width = 1.75f + (seed * 11 + cluster * 7) % 6 * 0.15f;
                crowns.AddEllipsoid(center,
                    new Vector3(width, height * (0.15f + cluster % 3 * 0.014f), width * (0.84f + cluster % 2 * 0.12f)),
                    7, 10);
            }
        }

        private static void AddMedianTree(
            Vector3 position, int seed, MeshAccumulator trunks, MeshAccumulator crowns)
        {
            var height = 6.8f + seed % 4 * 0.4f;
            trunks.AddCylinder(position + Vector3.up * height * 0.38f, 0.15f, height * 0.76f, 8);
            for (var cluster = 0; cluster < 6; cluster++)
            {
                var angle = cluster * 2.399f + seed * 0.41f;
                var center = position + new Vector3(Mathf.Cos(angle) * 0.55f,
                    height * (0.74f + cluster % 3 * 0.08f), Mathf.Sin(angle) * 0.55f);
                crowns.AddEllipsoid(center,
                    new Vector3(1.48f, height * 0.16f, 1.58f), 7, 10);
            }
        }

        private static void AddLamp(
            ReferenceShowcaseFrame frame, float across, float along,
            MeshAccumulator poles, MeshAccumulator heads)
        {
            var basePoint = frame.Point(across, 0f, along);
            poles.AddCylinder(basePoint + Vector3.up * 4.3f, 0.105f, 8.6f, 10);
            var towardRoad = across > 0f ? -frame.Right : frame.Right;
            poles.AddCylinderBetween(basePoint + Vector3.up * 8.35f,
                basePoint + Vector3.up * 8.35f + towardRoad * 2.1f, 0.085f, 9);
            heads.AddBox(basePoint + Vector3.up * 8.3f + towardRoad * 2.2f,
                new Vector3(0.62f, 0.22f, 0.34f));
        }
    }
}
