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
        private const string ShowcaseJunctionId = "cluster_11122023464_11122023574";
        private const string TrafficShowcaseJunctionId = "cluster_11122023464_11122023574";
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
        private EntityActor? followActor;

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
            cameraComponent.nearClipPlane = 0.15f;
            cameraComponent.farClipPlane = 8000f;
            cameraComponent.allowHDR = true;
            cameraComponent.depthTextureMode = DepthTextureMode.Depth;
            var cameraData = cameraObject.GetComponent<UniversalAdditionalCameraData>();
            if (cameraData == null) cameraData = cameraObject.AddComponent<UniversalAdditionalCameraData>();
            cameraData.renderPostProcessing = true;
            cameraData.renderShadows = true;
            cameraData.stopNaN = true;
            cameraData.dithering = true;
            cameraData.antialiasing = AntialiasingMode.SubpixelMorphologicalAntiAliasing;
            cameraData.antialiasingQuality = AntialiasingQuality.High;
            SetView("monitor", ShowcaseJunctionId);
            SnapToCurrentView();
        }

        public void SetView(string mode, string? identifier = null)
        {
            followActor = null;
            followTrafficCluster = false;
            switch (mode)
            {
                case "traffic":
                    var trafficTarget = identifier == ShowcaseJunctionId || string.IsNullOrWhiteSpace(identifier)
                        ? ShowcaseVisualAnchorJunctionId
                        : identifier ?? TrafficShowcaseJunctionId;
                    desiredTarget = ResolveTarget(trafficTarget);
                    if (trafficTarget == ShowcaseVisualAnchorJunctionId)
                    {
                        cameraComponent.fieldOfView = 44f;
                        desiredDistance = 64f;
                        pitch = 14.8f;
                        yaw = 182f;
                        desiredTarget += new Vector3(0f, 1.1f, -4f);
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
                    cameraComponent.fieldOfView = 52f;
                    desiredTarget = Vector3.zero;
                    desiredDistance = 2750f;
                    pitch = 58f;
                    yaw = 15f;
                    break;
                case "corridor":
                    cameraComponent.fieldOfView = 49f;
                    desiredTarget = new Vector3(155f, 0f, 555f);
                    desiredDistance = 1180f;
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
                    if (identifier == ShowcaseJunctionId)
                    {
                        desiredTarget = ResolveTarget(ShowcaseVisualAnchorJunctionId) + new Vector3(0f, 1.4f, -5f);
                        desiredDistance = 64f;
                        pitch = 14.8f;
                        yaw = 182f;
                        cameraComponent.fieldOfView = 44f;
                    }
                    else
                    {
                        if (identifier == "K06")
                        {
                            desiredDistance = 148f;
                            pitch = 34f;
                            yaw = 106f;
                            cameraComponent.fieldOfView = 49f;
                        }
                        else
                        {
                            desiredDistance = 116f;
                            pitch = 29f;
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
                return;
            }
            desiredTarget = ResolveTarget(identifier);
            desiredDistance = 180f;
        }

        private Vector3 ResolveTarget(string? identifier)
        {
            if (!string.IsNullOrWhiteSpace(identifier) && scene.Junctions.TryGetValue(identifier, out var junction))
                return scene.Coordinates.ToWorld(junction.Position);
            var display = scene.Document.Junctions.FirstOrDefault(item => item.DisplayId == identifier);
            return display == null ? Vector3.zero : scene.Coordinates.ToWorld(display.Position);
        }

        private void LateUpdate()
        {
            if (cameraComponent == null) return;
            HandleInput();
            if (followActor != null)
            {
                var forward = Vector3.ProjectOnPlane(followActor.transform.forward, Vector3.up).normalized;
                if (forward.sqrMagnitude < 0.1f) forward = Vector3.forward;
                var lookTarget = followActor.transform.position + Vector3.up * 1.25f + forward * 4.2f;
                var chasePosition = followActor.transform.position - forward * 8.5f + Vector3.up * 3.4f;
                var smoothing = 1f - Mathf.Exp(-Time.unscaledDeltaTime * 5.5f);
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
                return;
            }
            if (followTrafficCluster && entities.TryGetVehicleClusterCenter(out var clusterCenter))
                desiredTarget = clusterCenter;
            target = Vector3.Lerp(target, desiredTarget, 1f - Mathf.Exp(-Time.unscaledDeltaTime * 4.5f));
            distance = Mathf.Lerp(distance, desiredDistance, 1f - Mathf.Exp(-Time.unscaledDeltaTime * 4.5f));
            var orbit = Quaternion.Euler(pitch, yaw, 0f) * Vector3.back * distance;
            cameraComponent.transform.position = target + orbit;
            cameraComponent.transform.LookAt(target + Vector3.up * 1.5f);
        }

        private void HandleInput()
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
                yaw += Input.GetAxis("Mouse X") * 2.8f;
                pitch = Mathf.Clamp(pitch - Input.GetAxis("Mouse Y") * 2.2f, 8f, 82f);
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
                Pan(Input.GetAxis("Mouse X"), Input.GetAxis("Mouse Y"));
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
                                 speed * Time.unscaledDeltaTime;
                desiredTarget.y = Mathf.Clamp(desiredTarget.y + vertical * speed * 0.45f * Time.unscaledDeltaTime, 0f, 350f);
            }
            desiredDistance = Mathf.Clamp(desiredDistance * Mathf.Exp(-Input.mouseScrollDelta.y * 0.12f), 4f, 3500f);
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
        }
    }
}
