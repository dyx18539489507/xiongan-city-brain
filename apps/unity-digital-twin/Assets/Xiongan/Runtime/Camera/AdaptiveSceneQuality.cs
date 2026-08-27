using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;
using Xiongan.DigitalTwin.Scene;

namespace Xiongan.DigitalTwin.CameraSystem
{
    public enum SceneQualityProfile
    {
        Street,
        District,
        Overview,
    }

    public sealed class AdaptiveSceneQuality : MonoBehaviour
    {
        private sealed class ChunkEntry
        {
            public Renderer Renderer = null!;
            public SceneDetailClass DetailClass;
            public ShadowCastingMode OriginalShadowMode;
            public ShadowCastingMode CurrentShadowMode;
            public Bounds Bounds;
            public float EnterDistanceSquared;
            public float ExitDistanceSquared;
            public float ShadowEnterDistanceSquared;
            public float ShadowExitDistanceSquared;
            public bool AlwaysVisible;
            public bool Enabled = true;
        }

        private readonly List<ChunkEntry> chunks = new();
        private UnityEngine.Camera cameraComponent = null!;
        private UniversalAdditionalCameraData cameraData = null!;
        private UniversalRenderPipelineAsset? pipelineAsset;
        private CameraDirector? cameraDirector;
        private SceneQualityProfile profile = SceneQualityProfile.Street;
        private float nextVisibilityUpdate;
        private float nextShadowUpdate;
        private Vector3 lastChunkEvaluationPosition;
        private bool hasChunkEvaluationPosition;
        private bool zoomWasActive;
        private float zoomSettleUntil;

        public string ProfileName => profile.ToString().ToUpperInvariant();
        public int TotalChunkCount => chunks.Count;
        public int ActiveChunkCount { get; private set; }

        public void Initialise(UnityEngine.Camera targetCamera)
        {
            cameraComponent = targetCamera;
            cameraData = cameraComponent.GetUniversalAdditionalCameraData();
            pipelineAsset = UniversalRenderPipeline.asset;
            cameraDirector = cameraComponent.GetComponentInParent<CameraDirector>();
            chunks.Clear();
            foreach (var chunk in FindObjectsByType<SceneChunk>(FindObjectsInactive.Include, FindObjectsSortMode.None))
            {
                var renderer = chunk.Renderer;
                if (renderer == null) continue;
                AddRenderer(renderer, chunk.DetailClass);
            }

            // Baked signal heads, imported trees and street furniture predate
            // SceneChunk. They accounted for more than half of all renderers
            // and remained submitted at every camera distance. Treat them as
            // context geometry while preserving every object in the scene.
            foreach (var renderer in FindObjectsByType<MeshRenderer>(FindObjectsInactive.Include, FindObjectsSortMode.None))
            {
                if (renderer.GetComponent<SceneChunk>() != null) continue;
                AddRenderer(renderer, ResolveLooseRendererDetail(renderer));
            }

            QualitySettings.vSyncCount = 0;
            profile = ResolveProfile(cameraComponent.transform.position.y, true);
            ApplyProfile();
            ActiveChunkCount = chunks.Count;
            UpdateChunks(true, cameraComponent.transform.position);
        }

        private void LateUpdate()
        {
            if (cameraComponent == null) return;
            var cameraPosition = cameraComponent.transform.position;
            if (cameraDirector != null && cameraDirector.IsZooming)
            {
                zoomWasActive = true;
                zoomSettleUntil = Time.unscaledTime + 0.85f;
                return;
            }
            if (zoomWasActive && Time.unscaledTime < zoomSettleUntil) return;
            var nextProfile = ResolveProfile(cameraPosition.y, false);
            if (nextProfile != profile)
            {
                profile = nextProfile;
                ApplyProfile();
            }
            zoomWasActive = false;
            UpdateChunks(false, cameraPosition);
        }

        private SceneQualityProfile ResolveProfile(float cameraHeight, bool force)
        {
            if (force)
                return cameraHeight < 120f ? SceneQualityProfile.Street :
                    cameraHeight < 650f ? SceneQualityProfile.District : SceneQualityProfile.Overview;

            return profile switch
            {
                SceneQualityProfile.Street when cameraHeight < 150f => SceneQualityProfile.Street,
                SceneQualityProfile.Street => cameraHeight < 680f ? SceneQualityProfile.District : SceneQualityProfile.Overview,
                SceneQualityProfile.District when cameraHeight < 95f => SceneQualityProfile.Street,
                SceneQualityProfile.District when cameraHeight > 700f => SceneQualityProfile.Overview,
                SceneQualityProfile.District => SceneQualityProfile.District,
                SceneQualityProfile.Overview when cameraHeight > 570f => SceneQualityProfile.Overview,
                SceneQualityProfile.Overview => cameraHeight < 105f ? SceneQualityProfile.Street : SceneQualityProfile.District,
                _ => SceneQualityProfile.District,
            };
        }

        private void ApplyProfile()
        {
            if (pipelineAsset != null)
            {
                // Keep a stable one-to-one render scale while the camera moves.
                // Sub-native rendering made thin lane markings and facade edges
                // jump between pixels until the smoothed camera came to rest.
                pipelineAsset.renderScale = 1f;
                // URP TAA requires a single-sample camera target. Temporal
                // accumulation is what stabilises sub-pixel city geometry.
                pipelineAsset.msaaSampleCount = 1;
                pipelineAsset.shadowDistance = 96f;
                pipelineAsset.mainLightShadowmapResolution = 2048;
                pipelineAsset.shadowCascadeCount = 2;
            }
            // WebGL is driven by requestAnimationFrame. Matching a common display
            // cadence keeps camera interpolation from advancing in coarse 30 Hz
            // steps, which otherwise presents as edge shimmer during movement.
            Application.targetFrameRate = 60;

            // CameraDirector owns the dynamic clip planes because its orbit
            // target can be far from world zero after panning. Quality changes
            // only re-assert the stable temporal rendering configuration.
            StableCameraRendering.ConfigureTemporalAntialiasing(cameraComponent, cameraData);
            ConfigureChunkBudgets();
        }

        private void ConfigureChunkBudgets()
        {
            var fineDistance = profile switch
            {
                // The B01 hero camera sits 160 m from the junction. Keep its
                // facade glazing and other authored detail active across the
                // full first viewport, including after an orbit-and-return.
                SceneQualityProfile.Street => 260f,
                SceneQualityProfile.District => 290f,
                _ => 190f,
            };
            var contextDistance = profile switch
            {
                SceneQualityProfile.Street => 335f,
                SceneQualityProfile.District => 980f,
                _ => 1600f,
            };
            var essentialDistance = profile switch
            {
                SceneQualityProfile.Street => 1050f,
                SceneQualityProfile.District => 2850f,
                _ => 5200f,
            };
            var shadowDistance = profile switch
            {
                SceneQualityProfile.Street => 88f,
                SceneQualityProfile.District => 96f,
                _ => 64f,
            };

            var shadowExitDistance = shadowDistance * 1.18f;
            for (var index = 0; index < chunks.Count; index++)
            {
                var entry = chunks[index];
                var maximum = entry.DetailClass switch
                {
                    SceneDetailClass.Fine => fineDistance,
                    SceneDetailClass.Context => contextDistance,
                    _ => essentialDistance,
                };
                entry.EnterDistanceSquared = maximum * maximum;
                var exitDistance = maximum * 1.16f;
                entry.ExitDistanceSquared = exitDistance * exitDistance;
                entry.ShadowEnterDistanceSquared = shadowDistance * shadowDistance;
                entry.ShadowExitDistanceSquared = shadowExitDistance * shadowExitDistance;
            }
        }

        private void UpdateChunks(bool immediate, Vector3 cameraPosition)
        {
            if (chunks.Count == 0)
            {
                ActiveChunkCount = 0;
                return;
            }
            if (!immediate && Time.unscaledTime < nextVisibilityUpdate) return;
            var minimumMovement = profile switch
            {
                SceneQualityProfile.Street => 1.5f,
                SceneQualityProfile.District => 4f,
                _ => 10f,
            };
            if (!immediate && hasChunkEvaluationPosition &&
                (cameraPosition - lastChunkEvaluationPosition).sqrMagnitude < minimumMovement * minimumMovement)
            {
                nextVisibilityUpdate = Time.unscaledTime + 0.18f;
                return;
            }
            nextVisibilityUpdate = Time.unscaledTime + 0.22f;
            lastChunkEvaluationPosition = cameraPosition;
            hasChunkEvaluationPosition = true;

            var updateShadows = immediate || Time.unscaledTime >= nextShadowUpdate;
            if (updateShadows) nextShadowUpdate = Time.unscaledTime + 0.5f;
            for (var index = 0; index < chunks.Count; index++)
            {
                var entry = chunks[index];
                var distanceSquared = entry.Bounds.SqrDistance(cameraPosition);
                // Keep every authored renderer resident. Unity's native renderer
                // performs stable frustum culling; camera-distance state changes
                // here were the source of whole-chunk pop and delayed settling.
                var enabled = ShouldKeepRendererEnabled(
                    entry.DetailClass,
                    distanceSquared,
                    entry.EnterDistanceSquared,
                    entry.ExitDistanceSquared);
                if (enabled != entry.Enabled)
                {
                    entry.Enabled = enabled;
                    entry.Renderer.forceRenderingOff = !enabled;
                    ActiveChunkCount += enabled ? 1 : -1;
                }
                if (!updateShadows) continue;
                var shadowMode = ResolveStableShadowMode(entry.OriginalShadowMode);
                if (entry.CurrentShadowMode != shadowMode)
                {
                    entry.Renderer.shadowCastingMode = shadowMode;
                    entry.CurrentShadowMode = shadowMode;
                }
            }
        }

        public static bool ShouldKeepRendererEnabled(
            SceneDetailClass detailClass,
            float distanceSquared,
            float enterDistanceSquared,
            float exitDistanceSquared)
        {
            _ = detailClass;
            _ = distanceSquared;
            _ = enterDistanceSquared;
            _ = exitDistanceSquared;

            // Unity already performs stable frustum culling. Changing
            // Renderer.forceRenderingOff from camera-distance samples caused
            // whole city chunks to pop while orbiting or zooming, then settle a
            // moment after input stopped. Keep geometry resident and let the
            // renderer handle visibility without mutating scene state.
            return true;
        }

        public static ShadowCastingMode ResolveStableShadowMode(ShadowCastingMode originalMode)
        {
            // URP's shadow distance performs the required culling. Per-renderer
            // shadow mode changes introduce a second moving threshold and make
            // large surfaces flash as the camera crosses it.
            return originalMode;
        }

        private void AddRenderer(Renderer renderer, SceneDetailClass detailClass)
        {
            chunks.Add(new ChunkEntry
            {
                Renderer = renderer,
                DetailClass = detailClass,
                OriginalShadowMode = renderer.shadowCastingMode,
                CurrentShadowMode = renderer.shadowCastingMode,
                Bounds = renderer.bounds,
                AlwaysVisible = IsCriticalGeometry(renderer, detailClass),
            });
        }

        private static bool IsCriticalGeometry(Renderer renderer, SceneDetailClass detailClass)
        {
            if (detailClass == SceneDetailClass.Essential) return true;
            for (var current = renderer.transform; current != null; current = current.parent)
            {
                var objectName = current.name;
                if (objectName.Contains("B01") || objectName.Contains("信号") ||
                    objectName.Contains("机动车道") || objectName.Contains("非机动车道") ||
                    objectName.Contains("路口面") || objectName.Contains("斑马线") ||
                    objectName.Contains("车道线") || objectName.Contains("停止线") ||
                    objectName.Contains("导向箭头") || objectName.Contains("道路地面"))
                    return true;
            }
            return false;
        }

        private static SceneDetailClass ResolveLooseRendererDetail(Renderer renderer)
        {
            for (var current = renderer.transform; current != null; current = current.parent)
            {
                var objectName = current.name;
                if (objectName.Contains("信号") || objectName.Contains("路灯") ||
                    objectName.Contains("街道家具") || objectName.Contains("公交站") ||
                    objectName.Contains("长椅") || objectName.Contains("路侧"))
                    return SceneDetailClass.Fine;
            }
            return SceneDetailClass.Context;
        }
    }
}
