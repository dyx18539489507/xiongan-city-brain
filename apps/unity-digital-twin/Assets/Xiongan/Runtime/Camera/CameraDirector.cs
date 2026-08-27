using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;
using UnityEngine.Rendering.Universal;
using Xiongan.DigitalTwin.Browser;
using Xiongan.DigitalTwin.Entities;
using Xiongan.DigitalTwin.Interaction;
using Xiongan.DigitalTwin.Scene;

namespace Xiongan.DigitalTwin.CameraSystem
{
    public sealed class CameraDirector : MonoBehaviour
    {
        private const float ZoomWheelSensitivity = 0.095f;
        private const float MaximumZoomWheelDelta = 2.5f;
        private const string ShowcaseJunctionId = ReferenceShowcaseLayout.JunctionId;
        private const string TrafficShowcaseJunctionId = ReferenceShowcaseLayout.JunctionId;
        private const string ShowcaseVisualAnchorJunctionId = ShowcaseJunctionId;
        private Camera cameraComponent = null!;
        private SceneBuilder scene = null!;
        private EntityManager entities = null!;
        private BrowserBridge bridge = null!;
        private Vector3 target;
        private Vector3 desiredTarget;
        private float yaw = 26f;
        private float pitch = 48f;
        private float distance = 750f;
        private float desiredDistance = 750f;
        private bool dragging;
        private bool panning;
        private bool followTrafficCluster;
        private Vector3 pointerDown;
        private float lastClickTime = -10f;
        private Vector3 lastClickPosition;
        private float zoomIdleDeadline = -10f;
        private EntityActor? followActor;
        private string currentViewMode = "hero";
        private string? currentViewIdentifier;
        private string viewBeforeVehicleLocate = "hero";
        private string? identifierBeforeVehicleLocate;
        private string currentVehicleId = string.Empty;
        private bool vehicleLocatorActive;
        private bool previewCaptureRunning;
        private bool renderingActive = true;
        private List<PreviewPose> previewPoses = new();
        private GameObject? previewObject;
        private Camera? previewCamera;
        private RenderTexture? previewTarget;
        private Texture2D? previewPixels;

        private readonly struct PreviewPose
        {
            public PreviewPose(string mode, Vector3 lookTarget, float viewDistance, float viewPitch, float viewYaw, float fieldOfView)
            {
                Mode = mode;
                LookTarget = lookTarget;
                ViewDistance = viewDistance;
                ViewPitch = viewPitch;
                ViewYaw = viewYaw;
                FieldOfView = fieldOfView;
            }

            public string Mode { get; }
            public Vector3 LookTarget { get; }
            public float ViewDistance { get; }
            public float ViewPitch { get; }
            public float ViewYaw { get; }
            public float FieldOfView { get; }
        }

        public UnityEngine.Camera ViewCamera => cameraComponent;
        public bool IsZooming => Time.unscaledTime < zoomIdleDeadline ||
                                 Mathf.Abs(distance - desiredDistance) >
                                 Mathf.Max(0.5f, desiredDistance * 0.008f);

        public void Initialise(SceneBuilder sceneBuilder, EntityManager entityManager, BrowserBridge browserBridge)
        {
            scene = sceneBuilder;
            entities = entityManager;
            bridge = browserBridge;
            var cameraObject = new GameObject("主三维摄像机");
            cameraObject.transform.SetParent(transform, false);
            cameraObject.tag = "MainCamera";
            cameraComponent = cameraObject.AddComponent<Camera>();
            cameraComponent.fieldOfView = 52f;
            var cameraData = cameraObject.GetComponent<UniversalAdditionalCameraData>();
            if (cameraData == null) cameraData = cameraObject.AddComponent<UniversalAdditionalCameraData>();
            StableCameraRendering.ConfigureCamera(cameraComponent, cameraData, distance);
            SetView("hero", HasReferenceShowcase ? ShowcaseJunctionId : ResolvePrimaryJunctionId());
            SnapToCurrentView();
        }

        public void SetView(string mode, string? identifier = null)
        {
            followActor = null;
            followTrafficCluster = false;
            vehicleLocatorActive = false;
            currentViewMode = mode;
            currentViewIdentifier = identifier;
            switch (mode)
            {
                case "hero":
                    if (HasReferenceShowcase)
                    {
                        var heroShowcase = ReferenceShowcaseLayout.Resolve(scene);
                        desiredTarget = heroShowcase.Center + heroShowcase.Forward * 14f + Vector3.up * 1.5f;
                        desiredDistance = 225f;
                        pitch = 34f;
                        yaw = heroShowcase.CameraYaw;
                        cameraComponent.fieldOfView = 43f;
                    }
                    else
                    {
                        var bounds = ResolveSceneBounds();
                        desiredTarget = ResolveTarget(identifier);
                        desiredDistance = Mathf.Clamp(Mathf.Max(bounds.size.x, bounds.size.z) * 0.3f, 110f, 320f);
                        pitch = 38f;
                        yaw = 145f;
                        cameraComponent.fieldOfView = 46f;
                    }
                    break;
                case "traffic":
                    var trafficTarget = identifier == ShowcaseJunctionId || string.IsNullOrWhiteSpace(identifier)
                        ? ShowcaseVisualAnchorJunctionId
                        : identifier ?? TrafficShowcaseJunctionId;
                    desiredTarget = ResolveTarget(trafficTarget);
                    if (trafficTarget == ShowcaseVisualAnchorJunctionId)
                    {
                        var trafficShowcase = ReferenceShowcaseLayout.Resolve(scene);
                        cameraComponent.fieldOfView = 42f;
                        desiredDistance = 118f;
                        pitch = 18f;
                        yaw = trafficShowcase.CameraYaw;
                        desiredTarget = trafficShowcase.Center + trafficShowcase.Forward * 18f + Vector3.up * 2.5f;
                    }
                    else
                    {
                        cameraComponent.fieldOfView = 50f;
                        desiredDistance = 100f;
                        pitch = 27f;
                        yaw = 160f;
                        desiredTarget += Vector3.up * 1.2f;
                    }
                    break;
                case "overview":
                    cameraComponent.fieldOfView = 45f;
                    var sceneBounds = ResolveSceneBounds();
                    desiredTarget = sceneBounds.center;
                    desiredDistance = CalculateOverviewDistance(sceneBounds.size) * 1.08f;
                    pitch = 72f;
                    yaw = 28f;
                    break;
                case "corridor":
                    cameraComponent.fieldOfView = 49f;
                    if (HasReferenceShowcase)
                    {
                        desiredTarget = new Vector3(155f, 0f, 555f);
                        desiredDistance = 1180f;
                    }
                    else
                    {
                        var corridorBounds = ResolveSceneBounds();
                        desiredTarget = corridorBounds.center;
                        desiredDistance = CalculateOverviewDistance(corridorBounds.size) * 0.72f;
                    }
                    pitch = 48f;
                    yaw = 34f;
                    break;
                case "driver":
                    cameraComponent.fieldOfView = 58f;
                    if (!string.IsNullOrWhiteSpace(identifier)) followActor = entities.Find(identifier);
                    desiredDistance = 8f;
                    pitch = 10f;
                    yaw = 180f;
                    break;
                case "monitor":
                    desiredTarget = ResolveTarget(identifier);
                    if (HasReferenceShowcase && identifier == ShowcaseJunctionId)
                    {
                        var monitorShowcase = ReferenceShowcaseLayout.Resolve(scene);
                        desiredTarget = monitorShowcase.Center + Vector3.up * 1.5f;
                        desiredDistance = 138f;
                        pitch = 38f;
                        yaw = monitorShowcase.CameraYaw;
                        cameraComponent.fieldOfView = 40f;
                    }
                    else
                    {
                        if (identifier == "K06")
                        {
                            desiredDistance = 158f;
                            pitch = 40f;
                            yaw = 106f;
                            cameraComponent.fieldOfView = 49f;
                        }
                        else
                        {
                            desiredDistance = 138f;
                            pitch = 38f;
                            yaw = 160f;
                            cameraComponent.fieldOfView = 48f;
                        }
                    }
                    break;
                default:
                    cameraComponent.fieldOfView = 50f;
                    desiredTarget = ResolveTarget(identifier ?? ShowcaseJunctionId);
                    desiredDistance = 235f;
                    pitch = 45f;
                    yaw = 32f;
                    break;
            }
        }

        public void Focus(string identifier)
        {
            var actor = entities.Find(identifier);
            if (actor != null)
            {
                desiredTarget = actor.transform.position;
                desiredDistance = 42f;
                pitch = 26f;
                followActor = actor;
                currentVehicleId = actor.Identifier;
                return;
            }
            desiredTarget = ResolveTarget(identifier);
            desiredDistance = 180f;
        }

        public void SetVehicleLocatorsVisible(bool visible)
        {
            entities.SetVehicleLocatorsVisible(visible);
        }

        public void SetRenderingActive(bool visible)
        {
            renderingActive = visible;
            cameraComponent.enabled = visible;
            Application.targetFrameRate = visible ? 60 : 10;
        }

        public void CaptureViewPreviews(string? identifier = null)
        {
            previewPoses = ResolvePreviewPoses(identifier);
            if (previewCaptureRunning) return;
            StartCoroutine(CaptureViewPreviewsRoutine());
        }

        private List<PreviewPose> ResolvePreviewPoses(string? identifier)
        {
            var savedViewMode = currentViewMode;
            var savedViewIdentifier = currentViewIdentifier;
            var savedTarget = target;
            var savedDesiredTarget = desiredTarget;
            var savedDistance = distance;
            var savedDesiredDistance = desiredDistance;
            var savedPitch = pitch;
            var savedYaw = yaw;
            var savedFov = cameraComponent.fieldOfView;
            var savedFollowActor = followActor;
            var savedFollowCluster = followTrafficCluster;
            var savedLocatorActive = vehicleLocatorActive;
            var poses = new List<PreviewPose>(3);
            foreach (var mode in new[] { "hero", "monitor", "overview" })
            {
                SetView(mode, identifier);
                poses.Add(new PreviewPose(mode, desiredTarget, desiredDistance, pitch, yaw, cameraComponent.fieldOfView));
            }
            currentViewMode = savedViewMode;
            currentViewIdentifier = savedViewIdentifier;
            target = savedTarget;
            desiredTarget = savedDesiredTarget;
            distance = savedDistance;
            desiredDistance = savedDesiredDistance;
            pitch = savedPitch;
            yaw = savedYaw;
            cameraComponent.fieldOfView = savedFov;
            followActor = savedFollowActor;
            followTrafficCluster = savedFollowCluster;
            vehicleLocatorActive = savedLocatorActive;
            return poses;
        }

        private void EnsurePreviewResources()
        {
            if (previewCamera != null && previewTarget != null && previewPixels != null) return;
            const int width = 240;
            const int height = 135;
            previewObject = new GameObject("三镜头实时监控");
            previewObject.transform.SetParent(transform, false);
            previewCamera = previewObject.AddComponent<Camera>();
            previewCamera.CopyFrom(cameraComponent);
            previewCamera.enabled = false;
            var previewData = previewObject.AddComponent<UniversalAdditionalCameraData>();
            StableCameraRendering.ConfigureCamera(previewCamera, previewData, distance);
            previewTarget = new RenderTexture(width, height, 16, RenderTextureFormat.ARGB32)
            {
                name = "三镜头实时监控画布",
            };
            previewTarget.Create();
            previewPixels = new Texture2D(width, height, TextureFormat.RGB24, false);
            previewCamera.targetTexture = previewTarget;
        }

        private IEnumerator CaptureViewPreviewsRoutine()
        {
            previewCaptureRunning = true;
            EnsurePreviewResources();
            var previewIndex = 0;
            var nextCaptureAt = 0f;
            try
            {
                while (true)
                {
                    if (!renderingActive || previewCamera == null || previewTarget == null ||
                        previewPixels == null || previewPoses.Count == 0 ||
                        Time.realtimeSinceStartup < nextCaptureAt)
                    {
                        yield return null;
                        continue;
                    }

                    var pose = previewPoses[previewIndex % previewPoses.Count];
                    previewCamera.fieldOfView = pose.FieldOfView;
                    var orbit = Quaternion.Euler(pose.ViewPitch, pose.ViewYaw, 0f) * Vector3.back * pose.ViewDistance;
                    previewCamera.transform.position = pose.LookTarget + orbit;
                    previewCamera.transform.LookAt(pose.LookTarget + Vector3.up * 1.5f);
                    StableCameraRendering.UpdateClipPlanes(previewCamera, pose.ViewDistance);

                    var previousActive = RenderTexture.active;
                    var previousFog = RenderSettings.fog;
                    try
                    {
                        RenderSettings.fog = pose.Mode != "overview";
                        previewCamera.Render();
                        RenderTexture.active = previewTarget;
                        previewPixels.ReadPixels(
                            new Rect(0, 0, previewTarget.width, previewTarget.height), 0, 0, false);
                        previewPixels.Apply(false, false);
                        bridge.Emit("camera-preview", new
                        {
                            mode = pose.Mode,
                            image = $"data:image/jpeg;base64,{Convert.ToBase64String(previewPixels.EncodeToJPG(62))}",
                            frame = Time.frameCount,
                        });
                    }
                    finally
                    {
                        RenderSettings.fog = previousFog;
                        RenderTexture.active = previousActive;
                    }

                    previewIndex = (previewIndex + 1) % previewPoses.Count;
                    nextCaptureAt = Time.realtimeSinceStartup + 0.27f;
                    yield return null;
                }
            }
            finally
            {
                ReleasePreviewResources();
                previewCaptureRunning = false;
            }
        }

        private void ReleasePreviewResources()
        {
            if (previewCamera != null) previewCamera.targetTexture = null;
            if (previewTarget != null)
            {
                previewTarget.Release();
                Destroy(previewTarget);
            }
            if (previewPixels != null) Destroy(previewPixels);
            if (previewObject != null) Destroy(previewObject);
            previewCamera = null;
            previewTarget = null;
            previewPixels = null;
            previewObject = null;
        }

        private void OnDestroy()
        {
            ReleasePreviewResources();
        }

        public void ResetRuntime()
        {
            followActor = null;
            followTrafficCluster = false;
            currentVehicleId = string.Empty;
            vehicleLocatorActive = false;
            entities.SetVehicleLocatorsVisible(false);
            SetView("hero", HasReferenceShowcase ? ShowcaseJunctionId : ResolvePrimaryJunctionId());
            SnapToCurrentView();
        }

        public void LocateVehicle(string mode, string? identifier = null)
        {
            if (mode == "restore")
            {
                followActor = null;
                followTrafficCluster = false;
                vehicleLocatorActive = false;
                entities.SetVehicleLocatorsVisible(false);
                SetView(viewBeforeVehicleLocate, identifierBeforeVehicleLocate);
                bridge.Emit("vehicle-locator", new { found = true, mode, count = 0, id = string.Empty });
                return;
            }

            if (!vehicleLocatorActive)
            {
                viewBeforeVehicleLocate = currentViewMode;
                identifierBeforeVehicleLocate = currentViewIdentifier;
                vehicleLocatorActive = true;
            }
            entities.SetVehicleLocatorsVisible(true);

            if (mode == "cluster")
            {
                followActor = null;
                if (!entities.TryGetVehicleClusterCenter(out var center, out var count, out _))
                {
                    bridge.Emit("vehicle-locator", new { found = false, mode, count = 0, id = string.Empty });
                    return;
                }
                desiredTarget = center;
                desiredDistance = Mathf.Clamp(105f + count * 2.5f, 120f, 230f);
                pitch = 52f;
                followTrafficCluster = false;
                currentVehicleId = string.Empty;
                bridge.Emit("vehicle-locator", new { found = true, mode, count, id = string.Empty });
                return;
            }

            EntityActor actor = null!;
            var found = mode switch
            {
                "nearest" => entities.TryGetNearestVehicle(desiredTarget, out actor),
                "previous" => entities.TryGetVehicleByOffset(currentVehicleId, -1, out actor),
                "next" => entities.TryGetVehicleByOffset(currentVehicleId, 1, out actor),
                "follow" when !string.IsNullOrWhiteSpace(identifier) && entities.Find(identifier) is { } selected => AssignActor(selected, out actor),
                "follow" => false,
                _ => entities.TryGetNearestVehicle(desiredTarget, out actor),
            };
            if (!found)
            {
                bridge.Emit("vehicle-locator", new { found = false, mode, count = 0, id = string.Empty });
                return;
            }
            FocusLocatedActor(actor, mode == "follow");
            bridge.Emit("vehicle-locator", new { found = true, mode, count = 1, id = actor.Identifier });
        }

        private static bool AssignActor(EntityActor source, out EntityActor actor)
        {
            actor = source;
            return true;
        }

        private void FocusLocatedActor(EntityActor actor, bool follow)
        {
            followTrafficCluster = false;
            followActor = follow ? actor : null;
            currentVehicleId = actor.Identifier;
            desiredTarget = actor.transform.position;
            desiredDistance = follow ? 8f : 48f;
            pitch = follow ? 10f : 30f;
        }

        private Vector3 ResolveTarget(string? identifier)
        {
            if (!string.IsNullOrWhiteSpace(identifier) && scene.Junctions.TryGetValue(identifier, out var junction))
                return scene.Coordinates.ToWorld(junction.Position);
            var display = scene.Document.Junctions.FirstOrDefault(item => item.DisplayId == identifier);
            if (display != null) return scene.Coordinates.ToWorld(display.Position);
            var primary = ResolvePrimaryJunctionId();
            return scene.Junctions.TryGetValue(primary, out junction)
                ? scene.Coordinates.ToWorld(junction.Position)
                : ResolveSceneBounds().center;
        }

        private bool HasReferenceShowcase => scene.Junctions.ContainsKey(ShowcaseJunctionId);

        private string ResolvePrimaryJunctionId()
        {
            var controlled = scene.Document.TrafficLights.FirstOrDefault()?.ControlledJunctionId;
            if (!string.IsNullOrWhiteSpace(controlled)) return controlled;
            return scene.Document.Junctions.FirstOrDefault(item => item.Controlled)?.SumoJunctionId
                   ?? scene.Document.Junctions.FirstOrDefault()?.SumoJunctionId
                   ?? string.Empty;
        }

        private Bounds ResolveSceneBounds()
        {
            var positions = scene.Document.Lanes
                .SelectMany(item => item.Shape)
                .Select(point => scene.Coordinates.ToWorld(point))
                .ToList();
            if (positions.Count == 0)
                positions = scene.Document.Junctions.Select(item => scene.Coordinates.ToWorld(item.Position)).ToList();
            if (positions.Count == 0) return new Bounds(Vector3.zero, new Vector3(120f, 0f, 120f));
            var bounds = new Bounds(positions[0], Vector3.zero);
            foreach (var position in positions.Skip(1)) bounds.Encapsulate(position);
            bounds.Expand(new Vector3(24f, 0f, 24f));
            return bounds;
        }

        public static float CalculateOverviewDistance(Vector3 sceneSize)
        {
            var span = Mathf.Max(sceneSize.x, sceneSize.z);
            return Mathf.Clamp(span * 0.9f + 40f, 140f, 3400f);
        }

        private void LateUpdate()
        {
            if (cameraComponent == null) return;
            // Preserve real-time input response during a slow WebGL frame. The old
            // 50 ms cap made the camera physically slow down below 20 FPS, which
            // compounded rendering stutter with sluggish controls.
            var frameTime = Mathf.Min(Time.unscaledDeltaTime, 0.1f);
            HandleInput(frameTime);
            if (followActor != null)
            {
                if (!followActor.gameObject.activeInHierarchy || followActor.Identifier != currentVehicleId)
                {
                    var departedId = currentVehicleId;
                    followActor = null;
                    currentVehicleId = string.Empty;
                    vehicleLocatorActive = false;
                    entities.SetVehicleLocatorsVisible(false);
                    bridge.Emit("vehicle-locator", new
                    {
                        found = false,
                        mode = "follow",
                        count = 0,
                        id = departedId,
                        reason = "departed",
                    });
                    return;
                }
                var forward = Vector3.ProjectOnPlane(followActor.transform.forward, Vector3.up).normalized;
                if (forward.sqrMagnitude < 0.1f) forward = Vector3.forward;
                var lookTarget = followActor.transform.position + Vector3.up * 1.25f + forward * 4.2f;
                var chasePosition = followActor.transform.position - forward * 8.5f + Vector3.up * 3.4f;
                var smoothing = 1f - Mathf.Exp(-frameTime * 5.5f);
                cameraComponent.transform.position = Vector3.Lerp(
                    cameraComponent.transform.position,
                    chasePosition,
                    smoothing);
                var lookRotation = Quaternion.LookRotation(
                    lookTarget - cameraComponent.transform.position,
                    Vector3.up);
                cameraComponent.transform.rotation = Quaternion.Slerp(
                    cameraComponent.transform.rotation,
                    lookRotation,
                    smoothing);
                target = desiredTarget = followActor.transform.position;
                StableCameraRendering.UpdateClipPlanes(
                    cameraComponent,
                    Vector3.Distance(cameraComponent.transform.position, lookTarget));
                return;
            }
            if (followTrafficCluster && entities.TryGetVehicleClusterCenter(out var clusterCenter))
                desiredTarget = clusterCenter;
            var cameraBlend = StableCameraRendering.CalculateMotionBlend(frameTime);
            target = Vector3.Lerp(target, desiredTarget, cameraBlend);
            distance = Mathf.Lerp(distance, desiredDistance, cameraBlend);
            if (Vector3.SqrMagnitude(target - desiredTarget) < 0.0004f) target = desiredTarget;
            if (Mathf.Abs(distance - desiredDistance) < Mathf.Max(0.01f, desiredDistance * 0.0001f))
                distance = desiredDistance;
            var orbit = Quaternion.Euler(pitch, yaw, 0f) * Vector3.back * distance;
            cameraComponent.transform.position = target + orbit;
            cameraComponent.transform.LookAt(target + Vector3.up * 1.5f);
            StableCameraRendering.UpdateClipPlanes(cameraComponent, distance);
        }

        private void HandleInput(float frameTime)
        {
            if (Input.GetMouseButtonDown(0))
            {
                pointerDown = Input.mousePosition;
                dragging = false;
            }
            if (Input.GetMouseButton(0))
            {
                var delta = (Vector3)Input.mousePosition - pointerDown;
                if (delta.sqrMagnitude > 12f) dragging = true;
                var mouseX = Mathf.Clamp(Input.GetAxis("Mouse X"), -8f, 8f);
                var mouseY = Mathf.Clamp(Input.GetAxis("Mouse Y"), -8f, 8f);
                yaw += mouseX * 2.8f;
                pitch = Mathf.Clamp(pitch - mouseY * 2.2f, 8f, 82f);
            }
            if (Input.GetMouseButtonUp(0) && !dragging)
            {
                var isDoubleClick = Time.unscaledTime - lastClickTime < 0.34f &&
                                    Vector3.SqrMagnitude(Input.mousePosition - lastClickPosition) < 144f;
                if (isDoubleClick) FocusGroundAtPointer();
                else SelectAtPointer();
                lastClickTime = Time.unscaledTime;
                lastClickPosition = Input.mousePosition;
            }

            if (Input.GetMouseButtonDown(1) || Input.GetMouseButtonDown(2))
            {
                panning = true;
                CancelFollowing();
            }
            if (Input.GetMouseButton(1) || Input.GetMouseButton(2))
            {
                Pan(
                    Mathf.Clamp(Input.GetAxis("Mouse X"), -8f, 8f),
                    Mathf.Clamp(Input.GetAxis("Mouse Y"), -8f, 8f));
            }
            if (Input.GetMouseButtonUp(1) || Input.GetMouseButtonUp(2)) panning = false;

            var keyboard = new Vector2(
                (Input.GetKey(KeyCode.D) ? 1f : 0f) - (Input.GetKey(KeyCode.A) ? 1f : 0f),
                (Input.GetKey(KeyCode.W) ? 1f : 0f) - (Input.GetKey(KeyCode.S) ? 1f : 0f));
            var vertical = (Input.GetKey(KeyCode.E) ? 1f : 0f) - (Input.GetKey(KeyCode.Q) ? 1f : 0f);
            if (keyboard.sqrMagnitude > 0.01f || Mathf.Abs(vertical) > 0.01f)
            {
                CancelFollowing();
                var flatForward = Vector3.ProjectOnPlane(cameraComponent.transform.forward, Vector3.up).normalized;
                var flatRight = Vector3.ProjectOnPlane(cameraComponent.transform.right, Vector3.up).normalized;
                var speed = Mathf.Clamp(desiredDistance * 0.48f, 12f, 420f);
                if (Input.GetKey(KeyCode.LeftShift) || Input.GetKey(KeyCode.RightShift)) speed *= 2.4f;
                desiredTarget += (flatRight * keyboard.x + flatForward * keyboard.y).normalized *
                                 speed * frameTime;
                desiredTarget.y = Mathf.Clamp(desiredTarget.y + vertical * speed * 0.45f * frameTime, 0f, 350f);
            }
            var scroll = Input.mouseScrollDelta.y;
            if (Mathf.Abs(scroll) > 0.001f)
            {
                desiredDistance = CalculateZoomDistance(desiredDistance, scroll);
                zoomIdleDeadline = Time.unscaledTime + 0.32f;
            }
        }

        public static float CalculateZoomDistance(float currentDistance, float wheelDelta)
        {
            var stableDelta = Mathf.Clamp(
                wheelDelta,
                -MaximumZoomWheelDelta,
                MaximumZoomWheelDelta);
            return Mathf.Clamp(
                currentDistance * Mathf.Exp(-stableDelta * ZoomWheelSensitivity),
                4f,
                3500f);
        }

        private void Pan(float horizontal, float vertical)
        {
            if (!panning) return;
            var flatForward = Vector3.ProjectOnPlane(cameraComponent.transform.forward, Vector3.up).normalized;
            var flatRight = Vector3.ProjectOnPlane(cameraComponent.transform.right, Vector3.up).normalized;
            var scale = Mathf.Clamp(desiredDistance * 0.0042f, 0.08f, 11f);
            desiredTarget += (-flatRight * horizontal - flatForward * vertical) * scale;
        }

        private void FocusGroundAtPointer()
        {
            CancelFollowing();
            var ray = cameraComponent.ScreenPointToRay(Input.mousePosition);
            var ground = new Plane(Vector3.up, Vector3.zero);
            if (!ground.Raycast(ray, out var distanceToGround)) return;
            desiredTarget = ray.GetPoint(distanceToGround);
            desiredTarget.y = 0f;
        }

        private void CancelFollowing()
        {
            followActor = null;
            followTrafficCluster = false;
        }

        private void SelectAtPointer()
        {
            var ray = cameraComponent.ScreenPointToRay(Input.mousePosition);
            if (!Physics.Raycast(ray, out var hit, 8000f)) return;
            var selectable = hit.collider.GetComponentInParent<SelectableObject>();
            if (selectable == null) return;
            bridge.Emit("selection", new
            {
                id = selectable.Identifier,
                kind = selectable.Kind,
                provenance = selectable.Provenance,
            });
            Focus(selectable.Identifier);
        }

        public void SnapToCurrentView()
        {
            target = desiredTarget;
            distance = desiredDistance;
            var orbit = Quaternion.Euler(pitch, yaw, 0f) * Vector3.back * distance;
            cameraComponent.transform.position = target + orbit;
            cameraComponent.transform.LookAt(target);
            StableCameraRendering.UpdateClipPlanes(cameraComponent, distance);
        }
    }
}
