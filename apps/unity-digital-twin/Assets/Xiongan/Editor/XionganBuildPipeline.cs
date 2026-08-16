using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Newtonsoft.Json;
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.Build.Reporting;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;
using Xiongan.DigitalTwin.Browser;
using Xiongan.DigitalTwin.CameraSystem;
using Xiongan.DigitalTwin.Data;
using Xiongan.DigitalTwin.Entities;
using Xiongan.DigitalTwin.Environment;
using Xiongan.DigitalTwin.Scene;
using Xiongan.DigitalTwin.Traffic;

namespace Xiongan.DigitalTwin.Editor
{
    public static class XionganBuildPipeline
    {
        private const string ScenePath = "Assets/Xiongan/Scenes/XionganDigitalTwin.unity";
        private const string PipelineAssetPath = "Assets/Xiongan/Settings/XionganURP.asset";
        private const string RendererDataPath = "Assets/UniversalRenderer.asset";
        private const string BakedAssetFolder = "Assets/Xiongan/Baked";

        [MenuItem("Xiongan/Configure project")]
        public static void ConfigureProject()
        {
            EnsureFolder("Assets/Xiongan/Scenes");
            EnsureFolder("Assets/Xiongan/Settings");
            ConfigureRenderPipeline();
            ConfigurePlayer();
            AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
            ConfigurePhotorealPropTextures();
            CreateBootstrapScene();
            AssetDatabase.SaveAssets();
            AssetDatabase.Refresh();
            Debug.Log("Xiongan Unity project configured.");
        }

        [MenuItem("Xiongan/Build WebGL")]
        public static void BuildWebGL()
        {
            ConfigureProject();
            var dashboard = Path.GetFullPath(Path.Combine(Application.dataPath, "..", "..", "web-dashboard"));
            var output = Path.Combine(dashboard, "public", "unity");
            Directory.CreateDirectory(output);
            var options = new BuildPlayerOptions
            {
                scenes = new[] { ScenePath },
                locationPathName = output,
                target = BuildTarget.WebGL,
                options = BuildOptions.None,
            };
            var report = BuildPipeline.BuildPlayer(options);
            if (report.summary.result != BuildResult.Succeeded)
                throw new BuildFailedException($"Unity WebGL build failed: {report.summary.result}");
            Debug.Log($"Unity WebGL build complete: {output} ({report.summary.totalSize} bytes)");
        }

        public static void ConfigureAndBuild()
        {
            BuildWebGL();
        }

        [MenuItem("Xiongan/Capture hero preview")]
        public static void CaptureHeroPreview()
        {
            ConfigureProject();
            EditorSceneManager.OpenScene(ScenePath, OpenSceneMode.Single);
            var sceneBuilder = UnityEngine.Object.FindFirstObjectByType<SceneBuilder>();
            if (sceneBuilder == null) throw new BuildFailedException("Baked SceneBuilder is missing.");
            sceneBuilder.RestoreBaked();

            var previewRoot = new GameObject("固定镜头三维验收环境");
            previewRoot.AddComponent<EnvironmentController>().Initialise(sceneBuilder.Materials);
            var entities = new GameObject("固定镜头实体管理器").AddComponent<EntityManager>();
            entities.Initialise(sceneBuilder.Coordinates, sceneBuilder.Materials);
            PopulateHeroPreviewTraffic(sceneBuilder, entities);
            PopulateHeroPreviewSignals(sceneBuilder);
            var bridge = new GameObject("固定镜头浏览器桥").AddComponent<BrowserBridge>();
            var director = previewRoot.AddComponent<CameraDirector>();
            director.Initialise(sceneBuilder, entities, bridge);
            director.SetView("monitor", "cluster_11122023464_11122023574");
            director.SnapToCurrentView();

            var camera = UnityEngine.Camera.main;
            if (camera == null) throw new BuildFailedException("Hero preview camera was not created.");
            const int width = 1920;
            const int height = 1080;
            var target = new RenderTexture(
                width, height, 24, RenderTextureFormat.ARGB32, RenderTextureReadWrite.sRGB)
            {
                antiAliasing = 4,
                name = "HeroPreviewTarget",
            };
            var pixels = new Texture2D(width, height, TextureFormat.RGB24, false, false);
            camera.aspect = width / (float)height;
            camera.targetTexture = target;
            camera.Render();
            RenderTexture.active = target;
            pixels.ReadPixels(new Rect(0f, 0f, width, height), 0, 0);
            pixels.Apply(false, false);

            var output = Path.GetFullPath(Path.Combine(
                Application.dataPath, "..", "..", "..", "outputs", "3d", "audit", "latest-hero-preview.png"));
            Directory.CreateDirectory(Path.GetDirectoryName(output)!);
            File.WriteAllBytes(output, pixels.EncodeToPNG());

            director.SetView("overview");
            director.SnapToCurrentView();
            camera.Render();
            RenderTexture.active = target;
            pixels.ReadPixels(new Rect(0f, 0f, width, height), 0, 0);
            pixels.Apply(false, false);
            var overviewOutput = Path.GetFullPath(Path.Combine(
                Application.dataPath, "..", "..", "..", "outputs", "3d", "audit", "latest-city-overview.png"));
            File.WriteAllBytes(overviewOutput, pixels.EncodeToPNG());
            foreach (var auditView in new[]
                     {
                         (Id: "B03", File: "latest-b03-monitor.png"),
                         (Id: "K06", File: "latest-k06-monitor.png"),
                     })
            {
                director.SetView("monitor", auditView.Id);
                director.SnapToCurrentView();
                camera.Render();
                RenderTexture.active = target;
                pixels.ReadPixels(new Rect(0f, 0f, width, height), 0, 0);
                pixels.Apply(false, false);
                var auditOutput = Path.GetFullPath(Path.Combine(
                    Application.dataPath, "..", "..", "..", "outputs", "3d", "audit", auditView.File));
                File.WriteAllBytes(auditOutput, pixels.EncodeToPNG());
                Debug.Log($"Junction audit captured: {auditView.Id} -> {auditOutput}");
            }
            camera.targetTexture = null;
            RenderTexture.active = null;
            UnityEngine.Object.DestroyImmediate(target);
            UnityEngine.Object.DestroyImmediate(pixels);
            Debug.Log($"Hero preview captured: {output}");
            Debug.Log($"City overview captured: {overviewOutput}");
        }

        private static void PopulateHeroPreviewTraffic(SceneBuilder scene, EntityManager entities)
        {
            const string heroId = "cluster_11122023464_11122023574";
            var junction = scene.Document.Junctions.First(item => item.SumoJunctionId == heroId);
            var center = junction.Position;
            var candidates = new List<(LaneRecord Lane, Point2 Point, float Angle, float Distance)>();
            foreach (var lane in scene.Document.Lanes.Where(item =>
                         item.EdgeFunction != "internal" && item.LaneKind is "motor" or "mixed" && item.Shape.Count >= 2))
            {
                (Point2 Point, float Angle, float Distance)? best = null;
                for (var segment = 0; segment < lane.Shape.Count - 1; segment++)
                {
                    var from = lane.Shape[segment];
                    var to = lane.Shape[segment + 1];
                    var point = new Point2 { X = (from.X + to.X) * 0.5f, Y = (from.Y + to.Y) * 0.5f };
                    var dx = point.X - center.X;
                    var dy = point.Y - center.Y;
                    var distance = Mathf.Sqrt(dx * dx + dy * dy);
                    if (distance < 15f || distance > 74f) continue;
                    var heading = Mathf.Repeat(Mathf.Atan2(to.X - from.X, to.Y - from.Y) * Mathf.Rad2Deg, 360f);
                    if (best == null || Mathf.Abs(distance - 29f) < Mathf.Abs(best.Value.Distance - 29f))
                        best = (point, heading, distance);
                }
                if (best.HasValue) candidates.Add((lane, best.Value.Point, best.Value.Angle, best.Value.Distance));
            }

            var selected = candidates
                .GroupBy(item => Mathf.FloorToInt(item.Angle / 90f) % 4)
                .SelectMany(group => group.OrderBy(item => item.Distance).Take(4))
                .Take(16)
                .ToList();
            var init = new DigitalTwinInit { ProtocolVersion = "audit", TickHz = 10f };
            for (var index = 0; index < selected.Count; index++)
            {
                var item = selected[index];
                for (var queueIndex = 0; queueIndex < 3; queueIndex++)
                {
                    var angleRadians = item.Angle * Mathf.Deg2Rad;
                    var queueOffset = queueIndex * 7.2f;
                    init.Entities.Vehicles.Add(new VehicleEntity
                    {
                        Id = $"hero-audit-{index:00}-{queueIndex}",
                        Type = "passenger",
                        VehicleClass = "passenger",
                        X = item.Point.X - Mathf.Sin(angleRadians) * queueOffset,
                        Y = item.Point.Y - Mathf.Cos(angleRadians) * queueOffset,
                        Angle = item.Angle,
                        Speed = queueIndex == 0 && item.Distance < 34f ? 0f : 5.5f + index % 5,
                        Acceleration = 0f,
                        LaneId = item.Lane.SumoLaneId,
                        EdgeId = item.Lane.SumoEdgeId,
                        Brake = queueIndex == 0 && item.Distance < 34f,
                        Status = "editor-audit-on-sumo-lane",
                    });
                }
            }

            var foregroundCandidates = new List<(LaneRecord Lane, Point2 Point, float Angle, float Score)>();
            foreach (var lane in scene.Document.Lanes.Where(item =>
                         item.EdgeFunction != "internal" && item.LaneKind is "motor" or "mixed" &&
                         item.Shape.Count >= 2))
            {
                for (var segment = 0; segment < lane.Shape.Count - 1; segment++)
                {
                    var from = lane.Shape[segment];
                    var to = lane.Shape[segment + 1];
                    var point = new Point2 { X = (from.X + to.X) * 0.5f, Y = (from.Y + to.Y) * 0.5f };
                    var dx = point.X - center.X;
                    var dy = point.Y - center.Y;
                    var distance = Mathf.Sqrt(dx * dx + dy * dy);
                    if (dx < 5f || dy > -5f || distance < 30f || distance > 58f) continue;
                    var angle = Mathf.Repeat(Mathf.Atan2(to.X - from.X, to.Y - from.Y) * Mathf.Rad2Deg, 360f);
                    foregroundCandidates.Add((lane, point, angle, Mathf.Abs(distance - 40f)));
                }
            }
            var orderedForeground = foregroundCandidates
                .GroupBy(item => item.Lane.SumoLaneId)
                .Select(group => group.OrderBy(item => item.Score).First())
                .OrderBy(item => item.Score)
                .ToList();
            var foreground = new List<(LaneRecord Lane, Point2 Point, float Angle, float Score)>();
            foreach (var candidate in orderedForeground)
            {
                var overlaps = init.Entities.Vehicles.Any(vehicle =>
                {
                    var dx = vehicle.X - candidate.Point.X;
                    var dy = vehicle.Y - candidate.Point.Y;
                    return dx * dx + dy * dy < 56.25f;
                });
                if (overlaps) continue;
                foreground.Add(candidate);
                if (foreground.Count == 2) break;
            }
            for (var index = 0; index < foreground.Count; index++)
            {
                var item = foreground[index];
                init.Entities.Vehicles.Add(new VehicleEntity
                {
                    Id = $"hero-foreground-{index:00}",
                    Type = "passenger",
                    VehicleClass = "passenger",
                    X = item.Point.X,
                    Y = item.Point.Y,
                    Angle = item.Angle,
                    Speed = 8.8f + index,
                    Acceleration = 0.1f,
                    LaneId = item.Lane.SumoLaneId,
                    EdgeId = item.Lane.SumoEdgeId,
                    Brake = false,
                    Status = "editor-audit-on-foreground-sumo-lane",
                });
            }

            var throughCandidates = new List<(LaneRecord Lane, Point2 Point, float Angle, float Distance)>();
            foreach (var lane in scene.Document.Lanes
                         .Where(item => item.EdgeFunction == "internal" && item.LaneKind is "motor" or "mixed" && item.Shape.Count >= 2)
                         .OrderBy(item => item.SumoLaneId))
            {
                Point2? bestPoint = null;
                var bestDistance = float.MaxValue;
                var bestScore = float.MaxValue;
                var bestAngle = 0f;
                for (var segment = 0; segment < lane.Shape.Count - 1; segment++)
                {
                    var from = lane.Shape[segment];
                    var to = lane.Shape[segment + 1];
                    var point = new Point2 { X = (from.X + to.X) * 0.5f, Y = (from.Y + to.Y) * 0.5f };
                    var dx = point.X - center.X;
                    var dy = point.Y - center.Y;
                    var distance = Mathf.Sqrt(dx * dx + dy * dy);
                    var score = Mathf.Abs(distance - 9f);
                    if (score >= bestScore) continue;
                    bestPoint = point;
                    bestDistance = distance;
                    bestScore = score;
                    bestAngle = Mathf.Repeat(Mathf.Atan2(to.X - from.X, to.Y - from.Y) * Mathf.Rad2Deg, 360f);
                }
                if (bestPoint != null && bestDistance <= 24f)
                    throughCandidates.Add((lane, bestPoint, bestAngle, bestDistance));
            }

            var throughSelected = throughCandidates
                .GroupBy(item => Mathf.RoundToInt(item.Angle / 90f) % 4)
                .Select(group => group.OrderBy(item => Mathf.Abs(item.Distance - 9f)).ThenBy(item => item.Lane.SumoLaneId).First())
                .OrderBy(item => item.Angle)
                .Where((_, index) => index % 2 == 0)
                .Take(2)
                .ToList();
            for (var throughIndex = 0; throughIndex < throughSelected.Count; throughIndex++)
            {
                var item = throughSelected[throughIndex];
                init.Entities.Vehicles.Add(new VehicleEntity
                {
                    Id = $"hero-through-{throughIndex:00}",
                    Type = "passenger",
                    VehicleClass = "passenger",
                    X = item.Point.X,
                    Y = item.Point.Y,
                    Angle = item.Angle,
                    Speed = 7.5f + throughIndex % 4,
                    Acceleration = 0.2f,
                    LaneId = item.Lane.SumoLaneId,
                    EdgeId = item.Lane.SumoEdgeId,
                    Brake = false,
                    Status = "editor-audit-on-sumo-internal-lane",
                });
            }

            var mobilityCandidates = new List<(LaneRecord Lane, Point2 Point, float Angle, float Score)>();
            foreach (var lane in scene.Document.Lanes.Where(item =>
                         item.EdgeFunction != "internal" && item.LaneKind is "bicycle" or "pedestrian" && item.Shape.Count >= 2))
            {
                for (var segment = 0; segment < lane.Shape.Count - 1; segment++)
                {
                    var from = lane.Shape[segment];
                    var to = lane.Shape[segment + 1];
                    for (var sample = 1; sample < 20; sample++)
                    {
                        var t = sample / 20f;
                        var point = new Point2 { X = Mathf.Lerp(from.X, to.X, t), Y = Mathf.Lerp(from.Y, to.Y, t) };
                        var dx = point.X - center.X;
                        var dy = point.Y - center.Y;
                        var distance = Mathf.Sqrt(dx * dx + dy * dy);
                        // This quadrant sits between the fixed audit camera and
                        // the junction, so detailed meshes remain legible.
                        if (dx < 3f || dy > -3f || distance < 18f || distance > 43f) continue;
                        var angle = Mathf.Repeat(Mathf.Atan2(to.X - from.X, to.Y - from.Y) * Mathf.Rad2Deg, 360f);
                        var score = Mathf.Abs(distance - 29f) + Mathf.Abs(dx - 18f) * 0.08f;
                        mobilityCandidates.Add((lane, point, angle, score));
                    }
                }
            }

            var bicycleSelected = mobilityCandidates
                .Where(item => item.Lane.LaneKind == "bicycle")
                .GroupBy(item => (Mathf.RoundToInt(item.Point.X / 5f), Mathf.RoundToInt(item.Point.Y / 5f)))
                .Select(group => group.OrderBy(item => item.Score).First())
                .OrderBy(item => item.Score)
                .Take(4)
                .ToList();
            for (var index = 0; index < bicycleSelected.Count; index++)
            {
                var item = bicycleSelected[index];
                init.Entities.Bicycles.Add(new VehicleEntity
                {
                    Id = $"hero-bicycle-{index:00}",
                    Type = "bicycle",
                    VehicleClass = "bicycle",
                    X = item.Point.X,
                    Y = item.Point.Y,
                    Angle = item.Angle,
                    Speed = 3.2f + index * 0.35f,
                    LaneId = item.Lane.SumoLaneId,
                    EdgeId = item.Lane.SumoEdgeId,
                    Status = "editor-audit-on-sumo-bicycle-lane",
                });
            }

            var pedestrianSelected = mobilityCandidates
                .Where(item => item.Lane.LaneKind == "pedestrian")
                .GroupBy(item => (Mathf.RoundToInt(item.Point.X / 4f), Mathf.RoundToInt(item.Point.Y / 4f)))
                .Select(group => group.OrderBy(item => item.Score).First())
                .OrderBy(item => item.Score)
                .Take(6)
                .ToList();
            for (var index = 0; index < pedestrianSelected.Count; index++)
            {
                var item = pedestrianSelected[index];
                var heading = item.Angle * Mathf.Deg2Rad;
                var stagger = index % 2 == 0 ? 2.4f : -2.4f;
                init.Entities.Pedestrians.Add(new PedestrianEntity
                {
                    Id = $"hero-pedestrian-{index:00}",
                    X = item.Point.X + Mathf.Sin(heading) * stagger,
                    Y = item.Point.Y + Mathf.Cos(heading) * stagger,
                    Angle = item.Angle,
                    Speed = 1.05f + index * 0.08f,
                    LaneId = item.Lane.SumoLaneId,
                    EdgeId = item.Lane.SumoEdgeId,
                    Status = "editor-audit-on-sumo-pedestrian-lane",
                });
            }
            entities.ApplyInit(init);
        }

        private static void PopulateHeroPreviewSignals(SceneBuilder scene)
        {
            const string heroId = "cluster_11122023464_11122023574";
            var manager = UnityEngine.Object.FindFirstObjectByType<TrafficLightManager>();
            var record = scene.Document.TrafficLights.FirstOrDefault(item => item.SumoTlsId == heroId);
            if (manager == null || record == null || record.Links.Count == 0) return;
            manager.RestoreBaked(scene);
            var stateLength = record.Links.Max(item => item.LinkIndex) + 1;
            var state = new string(Enumerable.Range(0, stateLength)
                .Select(index => index % 8 < 4 ? 'G' : 'r')
                .ToArray());
            manager.Apply(new[]
            {
                new TrafficLightEntity { Id = heroId, PhaseIndex = 0, State = state, RemainingS = 18f },
            });
        }

        private static void ConfigureRenderPipeline()
        {
            var asset = AssetDatabase.LoadAssetAtPath<UniversalRenderPipelineAsset>(PipelineAssetPath);
            UniversalRendererData rendererData = null;
            if (asset == null)
            {
                asset = ScriptableObject.CreateInstance<UniversalRenderPipelineAsset>();
                AssetDatabase.CreateAsset(asset, PipelineAssetPath);
                rendererData = asset.LoadBuiltinRendererData(RendererType.UniversalRenderer) as UniversalRendererData;
                if (rendererData != null && !AssetDatabase.Contains(rendererData)) AssetDatabase.AddObjectToAsset(rendererData, asset);
            }
            rendererData ??= AssetDatabase.LoadAllAssetsAtPath(PipelineAssetPath).OfType<UniversalRendererData>().FirstOrDefault();
            rendererData ??= AssetDatabase.LoadAssetAtPath<UniversalRendererData>(RendererDataPath);
            asset.renderScale = 1f;
            asset.msaaSampleCount = 4;
            asset.supportsHDR = true;
            asset.supportsCameraDepthTexture = true;
            asset.mainLightShadowmapResolution = 4096;
            asset.shadowCascadeCount = 4;
            asset.shadowDistance = 420f;
            asset.useSRPBatcher = true;
            QualitySettings.shadows = UnityEngine.ShadowQuality.All;
            QualitySettings.shadowResolution = UnityEngine.ShadowResolution.VeryHigh;
            QualitySettings.shadowProjection = ShadowProjection.StableFit;
            QualitySettings.shadowDistance = 420f;
            QualitySettings.shadowCascades = 4;
            QualitySettings.softParticles = true;
            if (rendererData != null)
            {
                var ambientOcclusion = rendererData.rendererFeatures.OfType<ScreenSpaceAmbientOcclusion>().FirstOrDefault();
                if (ambientOcclusion == null)
                {
                    ambientOcclusion = ScriptableObject.CreateInstance<ScreenSpaceAmbientOcclusion>();
                    ambientOcclusion.name = "Xiongan Contact Ambient Occlusion";
                    ambientOcclusion.Create();
                    rendererData.rendererFeatures.Add(ambientOcclusion);
                    AssetDatabase.AddObjectToAsset(ambientOcclusion, rendererData);
                }
                var serializedOcclusion = new SerializedObject(ambientOcclusion);
                serializedOcclusion.FindProperty("m_Settings.Intensity").floatValue = 1.45f;
                serializedOcclusion.FindProperty("m_Settings.DirectLightingStrength").floatValue = 0.38f;
                serializedOcclusion.FindProperty("m_Settings.Radius").floatValue = 0.055f;
                serializedOcclusion.FindProperty("m_Settings.Downsample").boolValue = false;
                serializedOcclusion.FindProperty("m_Settings.Source").enumValueIndex = 1;
                serializedOcclusion.FindProperty("m_Settings.NormalSamples").enumValueIndex = 2;
                serializedOcclusion.FindProperty("m_Settings.Samples").enumValueIndex = 0;
                serializedOcclusion.FindProperty("m_Settings.BlurQuality").enumValueIndex = 0;
                serializedOcclusion.ApplyModifiedPropertiesWithoutUndo();
                EditorUtility.SetDirty(rendererData);
            }
            GraphicsSettings.defaultRenderPipeline = asset;
            QualitySettings.renderPipeline = asset;
            // Every baked road/wall/landscape material keeps a serialized
            // reference to this shader in the generated scene.  That is the
            // Unity 6 supported retention path and prevents player stripping.
            if (AssetDatabase.LoadAssetAtPath<Shader>("Assets/Xiongan/Shaders/ProceduralSurface.shader") == null)
                throw new BuildFailedException("Required texture-free procedural surface shader is missing.");
            EditorUtility.SetDirty(asset);
        }

        private static void ConfigurePlayer()
        {
            PlayerSettings.companyName = "Xiongan Traffic Brain";
            PlayerSettings.productName = "雄安交通协同控制数字孪生";
            PlayerSettings.colorSpace = ColorSpace.Linear;
            PlayerSettings.runInBackground = true;
            // Local competition delivery is served on loopback.  Uncompressed
            // artifacts preserve identical rendering quality while avoiding a
            // second long Brotli pass whenever the hero art is updated.
            PlayerSettings.WebGL.compressionFormat = WebGLCompressionFormat.Disabled;
            PlayerSettings.WebGL.decompressionFallback = false;
            PlayerSettings.WebGL.exceptionSupport = WebGLExceptionSupport.ExplicitlyThrownExceptionsOnly;
            PlayerSettings.WebGL.template = "PROJECT:Xiongan";
            PlayerSettings.SetScriptingBackend(NamedBuildTarget.WebGL, ScriptingImplementation.IL2CPP);
            PlayerSettings.SetApiCompatibilityLevel(NamedBuildTarget.WebGL, ApiCompatibilityLevel.NET_Standard);
            PlayerSettings.SetManagedStrippingLevel(NamedBuildTarget.WebGL, ManagedStrippingLevel.High);
            PlayerSettings.SetIl2CppCodeGeneration(NamedBuildTarget.WebGL, Il2CppCodeGeneration.OptimizeSize);
        }

        private static void ConfigurePhotorealPropTextures()
        {
            var normalMaps = new[]
            {
                "Assets/Xiongan/Resources/Art/Models/island_tree_02/Textures/island_tree_02_branches_nor_gl_1k.png",
                "Assets/Xiongan/Resources/Art/Models/island_tree_02/Textures/island_tree_02_leaves_nor_gl_1k.png",
            };
            foreach (var path in normalMaps)
            {
                if (AssetImporter.GetAtPath(path) is not TextureImporter importer) continue;
                var changed = importer.textureType != TextureImporterType.NormalMap || importer.maxTextureSize != 1024;
                importer.textureType = TextureImporterType.NormalMap;
                importer.maxTextureSize = 1024;
                importer.textureCompression = TextureImporterCompression.CompressedHQ;
                if (changed) importer.SaveAndReimport();
            }

            var foliagePath = "Assets/Xiongan/Resources/Art/Models/island_tree_02/Textures/island_tree_02_leaves_diff_1k.png";
            if (AssetImporter.GetAtPath(foliagePath) is TextureImporter foliage)
            {
                var changed = !foliage.alphaIsTransparency || foliage.maxTextureSize != 1024;
                foliage.alphaSource = TextureImporterAlphaSource.FromInput;
                foliage.alphaIsTransparency = true;
                foliage.mipmapEnabled = true;
                foliage.maxTextureSize = 1024;
                foliage.textureCompression = TextureImporterCompression.CompressedHQ;
                if (changed) foliage.SaveAndReimport();
            }
        }

        private static void CreateBootstrapScene()
        {
            var source = Path.GetFullPath(Path.Combine(Application.dataPath, "..", "..", "..", "generated", "scenes", "xiongan_rongdong_20.scene.json"));
            if (!File.Exists(source)) throw new BuildFailedException($"Static scene source is missing: {source}");
            var document = JsonConvert.DeserializeObject<SceneDocument>(File.ReadAllText(source));
            if (document == null || document.Metadata.SceneId != "xiongan_rongdong_20" || document.TrafficLights.Count != 20)
                throw new BuildFailedException("Static scene source failed identity or 20-signal-junction validation.");

            if (AssetDatabase.IsValidFolder(BakedAssetFolder)) AssetDatabase.DeleteAsset(BakedAssetFolder);
            EnsureFolder(BakedAssetFolder);
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            var root = new GameObject("XionganBootstrap");
            root.AddComponent<XionganBootstrap>();

            var staticRoot = new GameObject("完整SUMO静态场景");
            staticRoot.transform.SetParent(root.transform, false);
            var sceneBuilder = staticRoot.AddComponent<SceneBuilder>();
            Exhaust(sceneBuilder.Build(document, (_, _) => { }));

            var urbanRoot = new GameObject("雄安城市环境");
            urbanRoot.transform.SetParent(root.transform, false);
            Exhaust(urbanRoot.AddComponent<UrbanContextBuilder>().Build(sceneBuilder, (_, _) => { }));

            var signalRoot = new GameObject("20路口信号灯");
            signalRoot.transform.SetParent(root.transform, false);
            signalRoot.AddComponent<TrafficLightManager>().Build(sceneBuilder);

            ValidatePureThreeDimensionalScene(root, sceneBuilder);

            PersistGeneratedAssets(root);
            sceneBuilder.CompactForRuntime();
            sceneBuilder.ReleaseBakedMaterialOwnership();
            EditorSceneManager.SaveScene(scene, ScenePath);
            EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene(ScenePath, true) };
            Debug.Log($"Baked complete SUMO scene into player: {document.Lanes.Count} lanes, {document.Junctions.Count} junctions, {document.TrafficLights.Count} signal controllers.");
        }

        private static void ValidatePureThreeDimensionalScene(GameObject root, SceneBuilder sceneBuilder)
        {
            foreach (var item in root.GetComponentsInChildren<Transform>(true))
            {
                var lower = item.name.ToLowerInvariant();
                if (lower.Contains("backdrop") || lower.Contains("background plate") ||
                    lower.Contains("照片级") || lower.Contains("远景板"))
                    throw new BuildFailedException($"Image plate object is forbidden in the pure 3D scene: {item.name}");
            }

            var noImageMaterials = new HashSet<Material>
            {
                sceneBuilder.Materials.Asphalt, sceneBuilder.Materials.HeroAsphalt,
                sceneBuilder.Materials.Junction, sceneBuilder.Materials.Sidewalk,
                sceneBuilder.Materials.HeroSidewalk, sceneBuilder.Materials.Curb,
                sceneBuilder.Materials.Building, sceneBuilder.Materials.BuildingRoof,
                sceneBuilder.Materials.BuildingGlass, sceneBuilder.Materials.BuildingGlassWarm,
                sceneBuilder.Materials.FacadeFrame,
            };
            foreach (var facade in sceneBuilder.Materials.Facades) noImageMaterials.Add(facade);
            foreach (var material in noImageMaterials)
            {
                if (material == null) continue;
                foreach (var property in material.GetTexturePropertyNames())
                {
                    if (material.GetTexture(property) != null)
                        throw new BuildFailedException($"Image texture is forbidden on road/wall material {material.name}: {property}");
                }
            }

            // PBR maps are permitted only for genuine mesh props.  This guard
            // prevents a future contributor from quietly introducing a road,
            // wall, facade, backdrop or terrain photograph into Resources.
            foreach (var guid in AssetDatabase.FindAssets("t:Texture2D", new[] { "Assets/Xiongan/Resources/Art" }))
            {
                var path = AssetDatabase.GUIDToAssetPath(guid);
                var lower = path.ToLowerInvariant();
                if (lower.Contains("asphalt") || lower.Contains("road_") || lower.Contains("road-") ||
                    lower.Contains("wall") || lower.Contains("facade") || lower.Contains("building") ||
                    lower.Contains("terrain") || lower.Contains("backdrop") || lower.Contains("background"))
                    throw new BuildFailedException($"Road/wall/background raster image is forbidden: {path}");
            }

            var forbiddenFolders = new[]
            {
                "Assets/Xiongan/Resources/Art/Backgrounds",
                "Assets/Xiongan/Resources/Art/Textures/PBR",
                "Assets/Xiongan/Resources/Art/Textures/Facades",
                "Assets/Xiongan/Resources/Art/HDRI",
            };
            foreach (var folder in forbiddenFolders)
                if (AssetDatabase.IsValidFolder(folder))
                    throw new BuildFailedException($"Forbidden runtime image folder still exists: {folder}");
        }

        private static void Exhaust(IEnumerator routine)
        {
            while (routine.MoveNext()) { }
        }

        private static void PersistGeneratedAssets(GameObject root)
        {
            var materialPaths = new Dictionary<Material, string>();
            var materialIndex = 0;
            foreach (var renderer in root.GetComponentsInChildren<Renderer>(true))
            {
                var materials = renderer.sharedMaterials;
                for (var index = 0; index < materials.Length; index++)
                {
                    var material = materials[index];
                    if (material == null || AssetDatabase.Contains(material)) continue;
                    if (!materialPaths.TryGetValue(material, out var path))
                    {
                        path = $"{BakedAssetFolder}/material-{materialIndex++:D3}.mat";
                        AssetDatabase.CreateAsset(material, path);
                        materialPaths[material] = path;
                    }
                    materials[index] = AssetDatabase.LoadAssetAtPath<Material>(path);
                }
                renderer.sharedMaterials = materials;
            }

            var meshIndex = 0;
            foreach (var filter in root.GetComponentsInChildren<MeshFilter>(true))
            {
                var mesh = filter.sharedMesh;
                if (mesh == null || AssetDatabase.Contains(mesh)) continue;
                var path = $"{BakedAssetFolder}/mesh-{meshIndex++:D3}.asset";
                AssetDatabase.CreateAsset(mesh, path);
                filter.sharedMesh = AssetDatabase.LoadAssetAtPath<Mesh>(path);
            }
            AssetDatabase.SaveAssets();
        }

        private static void EnsureFolder(string path)
        {
            var segments = path.Split('/');
            var current = segments[0];
            for (var index = 1; index < segments.Length; index++)
            {
                var next = $"{current}/{segments[index]}";
                if (!AssetDatabase.IsValidFolder(next)) AssetDatabase.CreateFolder(current, segments[index]);
                current = next;
            }
        }
    }
}
