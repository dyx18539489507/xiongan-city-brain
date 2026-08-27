using UnityEngine;
using UnityEngine.Rendering.Universal;

namespace Xiongan.DigitalTwin.CameraSystem
{
    public static class StableCameraRendering
    {
        public const float FarClipPlane = 6200f;
        private const float NearClipDistanceRatio = 0.025f;
        private const float MinimumNearClipPlane = 0.3f;
        private const float MaximumNearClipPlane = 96f;
        private const float CameraResponseRate = 28f;

        public static float CalculateNearClipPlane(float viewDistance)
        {
            return Mathf.Clamp(
                Mathf.Max(0f, viewDistance) * NearClipDistanceRatio,
                MinimumNearClipPlane,
                MaximumNearClipPlane);
        }

        public static float CalculateMotionBlend(float unscaledDeltaTime)
        {
            var frameTime = Mathf.Clamp(unscaledDeltaTime, 0f, 0.1f);
            return 1f - Mathf.Exp(-frameTime * CameraResponseRate);
        }

        public static void ConfigureCamera(
            Camera cameraComponent,
            UniversalAdditionalCameraData cameraData,
            float viewDistance)
        {
            ConfigureTemporalAntialiasing(cameraComponent, cameraData);
            UpdateClipPlanes(cameraComponent, viewDistance);
        }

        public static void ConfigureTemporalAntialiasing(
            Camera cameraComponent,
            UniversalAdditionalCameraData cameraData)
        {
            cameraComponent.allowHDR = false;
            cameraComponent.allowMSAA = false;
            cameraComponent.allowDynamicResolution = false;
            cameraComponent.depthTextureMode = DepthTextureMode.Depth;
            cameraData.requiresDepthTexture = true;
            cameraData.renderPostProcessing = true;
            cameraData.renderShadows = true;
            // Frame-varying dithering becomes visible as noise while the camera
            // moves over large uniform roofs and road surfaces.
            cameraData.dithering = false;
            cameraData.stopNaN = true;
            cameraData.antialiasing = AntialiasingMode.TemporalAntiAliasing;

            ref var taa = ref cameraData.taaSettings;
            taa.quality = TemporalAAQuality.High;
            taa.baseBlendFactor = 0.88f;
            taa.jitterScale = 0.65f;
            taa.mipBias = 0f;
            taa.varianceClampScale = 0.9f;
            taa.contrastAdaptiveSharpening = 0.12f;
        }

        public static void UpdateClipPlanes(Camera cameraComponent, float viewDistance)
        {
            cameraComponent.nearClipPlane = CalculateNearClipPlane(viewDistance);
            cameraComponent.farClipPlane = FarClipPlane;
        }
    }
}
