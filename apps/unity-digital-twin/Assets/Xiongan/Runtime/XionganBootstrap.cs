using System;
using System.Collections;
using Newtonsoft.Json.Linq;
using UnityEngine;
using Xiongan.DigitalTwin.Data;
using Xiongan.DigitalTwin.Browser;
using Xiongan.DigitalTwin.CameraSystem;
using Xiongan.DigitalTwin.Entities;
using Xiongan.DigitalTwin.Environment;
using Xiongan.DigitalTwin.Network;
using Xiongan.DigitalTwin.Scene;
using Xiongan.DigitalTwin.Traffic;

namespace Xiongan.DigitalTwin
{
    public sealed class XionganBootstrap : MonoBehaviour
    {
        private const string BakedScenarioId = "xiongan_rongdong_20";
        private const string SocketPath = "/ws/v1/digital-twin";
        private float progress;
        private string status = "初始化 Unity 数字孪生";
        private string? fatalError;
        private bool ready;
        private SceneBuilder sceneBuilder = null!;
        private EnvironmentController environmentController = null!;
        private CameraDirector cameraDirector = null!;
        private AlgorithmVisualManager algorithmVisuals = null!;
        private DigitalTwinClient digitalTwin = null!;
        private BrowserBridge bridge = null!;
        private EntityManager entityManager = null!;

        private IEnumerator Start()
        {
            Application.runInBackground = true;
            bridge = gameObject.AddComponent<BrowserBridge>();
            var requestedScenarioId = ResolveScenarioId();
            var useBakedScene = requestedScenarioId == BakedScenarioId;
            TrafficLightManager trafficLights;

            if (useBakedScene)
            {
                SetProgress(0.72f, "正在恢复预烘焙 SUMO 场景");
                sceneBuilder = GetComponentInChildren<SceneBuilder>(true);
                trafficLights = GetComponentInChildren<TrafficLightManager>(true);
                if (sceneBuilder == null || trafficLights == null)
                {
                    Fail("预烘焙场景索引缺失，请重新执行 WebGL 构建");
                    yield break;
                }
                sceneBuilder.RestoreBaked();
                trafficLights.RestoreBaked(sceneBuilder);
                yield return null;
            }
            else
            {
                foreach (Transform child in transform) child.gameObject.SetActive(false);
                sceneBuilder = CreateChild<SceneBuilder>("动态 SUMO 静态场景");
                var loader = CreateChild<SceneLoader>("动态场景加载器");
                SceneDocument? document = null;
                string? loadError = null;
                yield return loader.Load(
                    ResolveHttp($"/api/v1/scenes/{Uri.EscapeDataString(requestedScenarioId)}/3d"),
                    requestedScenarioId,
                    SetProgress,
                    value => document = value,
                    error => loadError = error);
                if (document == null)
                {
                    Fail(loadError ?? "动态场景加载失败");
                    yield break;
                }
                yield return sceneBuilder.Build(document, SetProgress);
                var urbanContext = CreateChild<UrbanContextBuilder>("动态 OSM 城市环境");
                // Prefer OSM buildings. Only a source area with no mapped buildings
                // receives the explicitly modeled, lane-aligned visual context.
                yield return urbanContext.Build(
                    sceneBuilder,
                    SetProgress,
                    includeModeledInfill: document.Buildings.Count == 0);
                trafficLights = CreateChild<TrafficLightManager>("动态场景信号灯");
                trafficLights.Build(sceneBuilder);
                Destroy(loader.gameObject);
            }

            entityManager = CreateChild<EntityManager>("SUMO动态交通主体");
            entityManager.Initialise(sceneBuilder);
            var conflicts = CreateChild<ConflictVisualManager>("安全冲突观测");
            conflicts.Initialise(sceneBuilder.Coordinates, sceneBuilder.Materials);
            var events = CreateChild<EventVisualManager>("交通扰动可视化");
            events.Initialise(sceneBuilder, entityManager);
            algorithmVisuals = CreateChild<AlgorithmVisualManager>("算法车道证据图层");
            algorithmVisuals.Initialise(sceneBuilder);
            environmentController = CreateChild<EnvironmentController>("天空天气与光照");
            environmentController.Initialise(sceneBuilder.Materials);
            cameraDirector = CreateChild<CameraDirector>("多视角导演");
            cameraDirector.Initialise(sceneBuilder, entityManager, bridge);
            var adaptiveQuality = CreateChild<AdaptiveSceneQuality>("自适应三维画质");
            adaptiveQuality.Initialise(cameraDirector.ViewCamera);
            CreateChild<PerformanceDiagnostics>("隐藏式帧时间诊断").Initialise(adaptiveQuality);

            digitalTwin = CreateChild<DigitalTwinClient>("DigitalTwinClient");
            digitalTwin.StateChanged += state => bridge.Emit("connection", new { state });
            digitalTwin.Initialise(ResolveWebSocket(SocketPath), entityManager, trafficLights, conflicts, events, algorithmVisuals);

            progress = 1f;
            status = useBakedScene ? "20 路口高保真场景已加载" : "当前 OSM 场景已加载";
            ready = true;
            bridge.Emit("scene-ready", new
            {
                sceneId = sceneBuilder.Document.Metadata.SceneId,
                schemaVersion = sceneBuilder.Document.Metadata.SchemaVersion,
                junctions = sceneBuilder.Document.TrafficLights.Count,
                lanes = sceneBuilder.Document.Lanes.Count,
                buildings = sceneBuilder.BakedBuildingCount,
                claimBoundary = sceneBuilder.Document.Metadata.ClaimBoundary,
            });
            cameraDirector.CaptureViewPreviews(
                useBakedScene ? ReferenceShowcaseLayout.JunctionId : null);
        }

        public void HandleBrowserCommand(string json)
        {
            if (!ready) return;
            try
            {
                var command = JObject.Parse(json);
                var action = command.Value<string>("action");
                switch (action)
                {
                    case "camera":
                        var cameraMode = command.Value<string>("mode") ?? "junction";
                        cameraDirector.SetView(cameraMode, command.Value<string>("id"));
                        environmentController.SetCameraMode(cameraMode);
                        break;
                    case "camera-previews":
                        cameraDirector.CaptureViewPreviews(command.Value<string>("id"));
                        break;
                    case "focus":
                        cameraDirector.Focus(command.Value<string>("id") ?? string.Empty);
                        break;
                    case "vehicle-locators":
                        cameraDirector.SetVehicleLocatorsVisible(command.Value<bool?>("visible") ?? false);
                        break;
                    case "vehicle-locate":
                        cameraDirector.LocateVehicle(
                            command.Value<string>("mode") ?? "cluster",
                            command.Value<string>("id"));
                        break;
                    case "weather":
                        environmentController.SetMode(command.Value<string>("mode") ?? "clear");
                        break;
                    case "source":
                        digitalTwin.SetExternalReplay(command.Value<string>("mode") == "replay");
                        break;
                    case "algorithm-visuals":
                        algorithmVisuals.SetVisible(command.Value<bool?>("visible") ?? false);
                        break;
                    case "runtime-reset":
                        digitalTwin.ResetRuntime();
                        cameraDirector.ResetRuntime();
                        environmentController.SetCameraMode("hero");
                        break;
                    case "visibility":
                        cameraDirector.SetRenderingActive(command.Value<bool?>("visible") ?? true);
                        break;
                }
                bridge.Emit("command-applied", new { action, mode = command.Value<string>("mode") ?? string.Empty });
            }
            catch (Exception error)
            {
                Debug.LogError($"Browser command rejected: {error.Message}");
            }
        }

        public void HandleBrowserSnapshot(string json)
        {
            if (!ready) return;
            digitalTwin.SetExternalReplay(true);
            digitalTwin.ApplyBrowserSnapshot(json);
        }

        private T CreateChild<T>(string objectName) where T : Component
        {
            var child = new GameObject(objectName);
            child.transform.SetParent(transform, false);
            return child.AddComponent<T>();
        }

        private void SetProgress(float value, string message)
        {
            progress = value;
            status = message;
            bridge?.Emit("loading", new { progress = value, message });
        }

        private void Fail(string error)
        {
            fatalError = error;
            status = error;
            bridge?.Emit("fatal", new { message = error });
            Debug.LogError(error);
        }

        private static string ResolveWebSocket(string path)
        {
#if UNITY_EDITOR
            return $"ws://127.0.0.1:8000{path}";
#else
            if (string.IsNullOrWhiteSpace(Application.absoluteURL)) return $"ws://127.0.0.1:8000{path}";
            var page = new Uri(Application.absoluteURL);
            return $"{(page.Scheme == "https" ? "wss" : "ws")}://{page.Authority}{path}";
#endif
        }

        private static string ResolveHttp(string path)
        {
#if UNITY_EDITOR
            return $"http://127.0.0.1:8000{path}";
#else
            if (string.IsNullOrWhiteSpace(Application.absoluteURL)) return $"http://127.0.0.1:8000{path}";
            return new Uri(new Uri(Application.absoluteURL), path).AbsoluteUri;
#endif
        }

        private static string ResolveScenarioId()
        {
            if (string.IsNullOrWhiteSpace(Application.absoluteURL)) return BakedScenarioId;
            try
            {
                var page = new Uri(Application.absoluteURL);
                foreach (var item in page.Query.TrimStart('?').Split('&'))
                {
                    var separator = item.IndexOf('=');
                    if (separator < 0) continue;
                    if (!string.Equals(Uri.UnescapeDataString(item[..separator]), "scenarioId", StringComparison.Ordinal)) continue;
                    var value = Uri.UnescapeDataString(item[(separator + 1)..]);
                    if (!string.IsNullOrWhiteSpace(value)) return value;
                }
            }
            catch (UriFormatException)
            {
                return BakedScenarioId;
            }
            return BakedScenarioId;
        }

        private void OnGUI()
        {
            if (ready && fatalError == null) return;
            var width = Mathf.Min(520f, Screen.width - 48f);
            var area = new Rect(24f, Screen.height - 112f, width, 80f);
            GUI.Box(area, GUIContent.none);
            GUI.Label(new Rect(area.x + 18f, area.y + 12f, area.width - 36f, 24f), fatalError ?? status);
            GUI.HorizontalScrollbar(new Rect(area.x + 18f, area.y + 50f, area.width - 36f, 14f), 0f, progress, 0f, 1f);
        }
    }
}
