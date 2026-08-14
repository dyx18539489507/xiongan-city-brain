using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using Newtonsoft.Json;
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.Build.Reporting;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;
using Xiongan.DigitalTwin.Data;
using Xiongan.DigitalTwin.Scene;
using Xiongan.DigitalTwin.Traffic;

namespace Xiongan.DigitalTwin.Editor
{
    public static class XionganBuildPipeline
    {
        private const string ScenePath = "Assets/Xiongan/Scenes/XionganDigitalTwin.unity";
        private const string PipelineAssetPath = "Assets/Xiongan/Settings/XionganURP.asset";
        private const string BakedAssetFolder = "Assets/Xiongan/Baked";

        [MenuItem("Xiongan/Configure project")]
        public static void ConfigureProject()
        {
            EnsureFolder("Assets/Xiongan/Scenes");
            EnsureFolder("Assets/Xiongan/Settings");
            ConfigureRenderPipeline();
            ConfigurePlayer();
            AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
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

        private static void ConfigureRenderPipeline()
        {
            var asset = AssetDatabase.LoadAssetAtPath<UniversalRenderPipelineAsset>(PipelineAssetPath);
            if (asset == null)
            {
                asset = ScriptableObject.CreateInstance<UniversalRenderPipelineAsset>();
                AssetDatabase.CreateAsset(asset, PipelineAssetPath);
                var rendererData = asset.LoadBuiltinRendererData(RendererType.UniversalRenderer);
                if (rendererData != null && !AssetDatabase.Contains(rendererData)) AssetDatabase.AddObjectToAsset(rendererData, asset);
            }
            asset.renderScale = 1f;
            asset.msaaSampleCount = 4;
            asset.supportsHDR = true;
            asset.shadowDistance = 420f;
            asset.useSRPBatcher = true;
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
