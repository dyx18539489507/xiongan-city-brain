using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;
using Xiongan.DigitalTwin.Core;

namespace Xiongan.DigitalTwin.Environment
{
    public sealed class EnvironmentController : MonoBehaviour
    {
        private Light sun = null!;
        private ColorAdjustments color = null!;
        private WhiteBalance whiteBalance = null!;

        public void Initialise(MaterialLibrary materials)
        {
            var lightObject = new GameObject("太阳主光");
            lightObject.transform.SetParent(transform, false);
            lightObject.transform.rotation = Quaternion.Euler(38f, -118f, 0f);
            sun = lightObject.AddComponent<Light>();
            sun.type = LightType.Directional;
            sun.intensity = 2.05f;
            sun.color = new Color(1f, 0.975f, 0.925f);
            sun.shadows = LightShadows.Soft;
            sun.shadowStrength = 0.9f;
            sun.shadowBias = 0.018f;
            sun.shadowNormalBias = 0.18f;

            var fillObject = new GameObject("天空柔光");
            fillObject.transform.SetParent(transform, false);
            fillObject.transform.rotation = Quaternion.Euler(58f, 145f, 0f);
            var fill = fillObject.AddComponent<Light>();
            fill.type = LightType.Directional;
            fill.intensity = 0.08f;
            fill.color = new Color(0.78f, 0.82f, 0.86f);
            fill.shadows = LightShadows.None;

            var skyShader = Shader.Find("Skybox/Procedural");
            if (skyShader != null)
            {
                var sky = new Material(skyShader);
                sky.SetFloat("_SunSize", 0.018f);
                sky.SetFloat("_SunSizeConvergence", 8.5f);
                sky.SetFloat("_AtmosphereThickness", 0.86f);
                sky.SetColor("_SkyTint", new Color(0.24f, 0.49f, 0.78f));
                sky.SetColor("_GroundColor", new Color(0.45f, 0.48f, 0.43f));
                sky.SetFloat("_Exposure", 1.02f);
                RenderSettings.skybox = sky;
            }
            RenderSettings.sun = sun;
            RenderSettings.fog = true;
            RenderSettings.fogMode = FogMode.Linear;
            RenderSettings.fogStartDistance = 1800f;
            RenderSettings.fogEndDistance = 8000f;
            RenderSettings.ambientMode = AmbientMode.Trilight;
            RenderSettings.ambientIntensity = 0.91f;
            RenderSettings.ambientSkyColor = new Color(0.68f, 0.7f, 0.69f);
            RenderSettings.ambientEquatorColor = new Color(0.49f, 0.5f, 0.46f);
            RenderSettings.ambientGroundColor = new Color(0.27f, 0.29f, 0.235f);
            RenderSettings.reflectionIntensity = 0.78f;
            RenderSettings.defaultReflectionMode = DefaultReflectionMode.Skybox;

            CreatePostProcessing();
            SetMode("clear");
            DynamicGI.UpdateEnvironment();
        }

        public void SetMode(string mode)
        {
            if (sun == null) return;
            color.postExposure.value = 1.05f;
            color.saturation.value = 1f;
            color.contrast.value = 10f;
            whiteBalance.temperature.value = 4f;
            sun.intensity = 2.05f;
            sun.color = new Color(1f, 0.975f, 0.925f);
            sun.transform.rotation = Quaternion.Euler(38f, -118f, 0f);
            RenderSettings.fogColor = new Color(0.61f, 0.74f, 0.85f);
            RenderSettings.ambientSkyColor = new Color(0.68f, 0.7f, 0.69f);
        }

        private void CreatePostProcessing()
        {
            var volumeObject = new GameObject("电影级全局后处理");
            volumeObject.transform.SetParent(transform, false);
            var volume = volumeObject.AddComponent<Volume>();
            volume.isGlobal = true;
            volume.priority = 100f;
            var profile = ScriptableObject.CreateInstance<VolumeProfile>();
            volume.profile = profile;
            var tonemapping = profile.Add<Tonemapping>(true);
            tonemapping.mode.Override(TonemappingMode.ACES);
            color = profile.Add<ColorAdjustments>(true);
            color.postExposure.Override(1.05f);
            color.contrast.Override(10f);
            color.saturation.Override(1f);
            whiteBalance = profile.Add<WhiteBalance>(true);
            whiteBalance.temperature.Override(4f);
            var bloom = profile.Add<Bloom>(true);
            bloom.threshold.Override(1.2f);
            bloom.intensity.Override(0.075f);
            bloom.scatter.Override(0.52f);
            var vignette = profile.Add<Vignette>(true);
            vignette.intensity.Override(0.015f);
            vignette.smoothness.Override(0.32f);
        }

    }
}
