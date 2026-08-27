using System.IO;
using System.Linq;
using NUnit.Framework;
using UnityEngine;
using Xiongan.DigitalTwin.Browser;
using Xiongan.DigitalTwin.CameraSystem;
using Xiongan.DigitalTwin.Data;
using Xiongan.DigitalTwin.Entities;
using Xiongan.DigitalTwin.Scene;
using Xiongan.DigitalTwin.Traffic;

namespace Xiongan.DigitalTwin.Tests
{
    public sealed class DynamicSceneTests
    {
        [Test]
        public void LoaderAcceptsAValidGeneratedScenario()
        {
            var document = CreateDocument("generated-osm");

            Assert.That(SceneLoader.Validate(document, "generated-osm"), Is.Null);
            Assert.That(SceneLoader.Validate(document, "different-scene"), Does.Contain("身份"));
        }

        [Test]
        public void BuilderDoesNotRequireTheReferenceB01Junction()
        {
            var root = new GameObject("dynamic-scene-test");
            try
            {
                var builder = root.AddComponent<SceneBuilder>();
                var build = builder.Build(CreateDocument("generated-osm"), (_, _) => { });
                while (build.MoveNext()) { }

                Assert.That(builder.Junctions.ContainsKey("generated-junction"), Is.True);
                Assert.That(builder.Lanes.ContainsKey("generated-lane_0"), Is.True);
            }
            finally
            {
                Object.DestroyImmediate(root);
            }
        }

        [Test]
        public void ModeledUrbanContextDoesNotRequireTheReferenceB01Junction()
        {
            var root = new GameObject("dynamic-urban-context-test");
            try
            {
                var builder = root.AddComponent<SceneBuilder>();
                var sceneBuild = builder.Build(CreateDocument("generated-osm"), (_, _) => { });
                while (sceneBuild.MoveNext()) { }
                var contextRoot = new GameObject("dynamic-urban-context");
                contextRoot.transform.SetParent(root.transform, false);
                var urbanContext = contextRoot.AddComponent<UrbanContextBuilder>();
                var contextBuild = urbanContext.Build(builder, (_, _) => { }, includeModeledInfill: true);

                Assert.DoesNotThrow(() =>
                {
                    while (contextBuild.MoveNext()) { }
                });
            }
            finally
            {
                Object.DestroyImmediate(root);
            }
        }

        [Test]
        public void OverviewDistanceAdaptsToSmallAndLargeScenes()
        {
            Assert.That(CameraDirector.CalculateOverviewDistance(new Vector3(120f, 0f, 80f)), Is.EqualTo(148f).Within(0.001f));
            Assert.That(CameraDirector.CalculateOverviewDistance(new Vector3(1200f, 0f, 900f)), Is.EqualTo(1120f).Within(0.001f));
        }

        [Test]
        public void LatestGeneratedOsmSceneBuildsItsTrafficLights()
        {
            var sceneDirectory = Path.GetFullPath(Path.Combine(
                Application.dataPath, "..", "..", "..", "generated", "scenes"));
            var scenePath = Directory.EnumerateFiles(sceneDirectory, "xiongan-*.scene.json")
                .Where(path => !path.EndsWith("xiongan_rongdong_20.scene.json"))
                .OrderByDescending(File.GetLastWriteTimeUtc)
                .FirstOrDefault();
            if (scenePath == null) Assert.Ignore("No generated OSM scene is available for runtime integration testing.");
            var document = SceneLoader.Deserialize(File.ReadAllText(scenePath!));
            Assert.That(document, Is.Not.Null);

            var root = new GameObject("generated-runtime-test");
            try
            {
                var builder = root.AddComponent<SceneBuilder>();
                var build = builder.Build(document!, (_, _) => { });
                while (build.MoveNext()) { }
                var trafficLights = new GameObject("generated-signals").AddComponent<TrafficLightManager>();
                trafficLights.transform.SetParent(root.transform, false);

                Assert.DoesNotThrow(() => trafficLights.Build(builder));
                var entities = new GameObject("generated-entities").AddComponent<EntityManager>();
                entities.transform.SetParent(root.transform, false);
                entities.Initialise(builder);
                var bridge = root.AddComponent<BrowserBridge>();
                var camera = new GameObject("generated-camera").AddComponent<CameraDirector>();
                camera.transform.SetParent(root.transform, false);

                Assert.DoesNotThrow(() => camera.Initialise(builder, entities, bridge));
            }
            finally
            {
                Object.DestroyImmediate(root);
            }
        }

        private static SceneDocument CreateDocument(string scenarioId)
        {
            var document = new SceneDocument();
            document.Metadata.SceneId = scenarioId;
            document.Metadata.ScenarioId = scenarioId;
            document.CoordinateSystem.WorldOriginSumo = new Point2 { X = 50f, Y = 50f };
            document.Junctions.Add(new JunctionRecord
            {
                SumoJunctionId = "generated-junction",
                Position = new Point2 { X = 50f, Y = 50f },
                Controlled = true,
            });
            document.Lanes.Add(new LaneRecord
            {
                SumoLaneId = "generated-lane_0",
                SumoEdgeId = "generated-edge",
                LaneKind = "motor",
                WidthM = 3.2f,
                Shape =
                {
                    new Point2 { X = 0f, Y = 50f },
                    new Point2 { X = 100f, Y = 50f },
                },
            });
            return document;
        }
    }
}
