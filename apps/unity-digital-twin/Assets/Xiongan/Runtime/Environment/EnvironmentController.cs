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
            lightObject.transform.rotation = Quaternion.Euler(43f, -126f, 0f);
            sun = lightObject.AddComponent<Light>();
            sun.type = LightType.Directional;
            sun.intensity = 1.38f;
            sun.color = new Color(1f, 0.955f, 0.89f);
            sun.shadows = LightShadows.Soft;
            sun.shadowStrength = 0.72f;
            sun.shadowBias = 0.024f;
            sun.shadowNormalBias = 0.24f;

            var fillObject = new GameObject("天空柔光");
            fillObject.transform.SetParent(transform, false);
            fillObject.transform.rotation = Quaternion.Euler(58f, 145f, 0f);
            var fill = fillObject.AddComponent<Light>();
            fill.type = LightType.Directional;
            fill.intensity = 0.24f;
            fill.color = new Color(0.86f, 0.9f, 0.96f);
            fill.shadows = LightShadows.None;

            var skyShader = Shader.Find("Skybox/Procedural");
            if (skyShader != null)
            {
                var sky = new Material(skyShader);
                sky.SetFloat("_SunSize", 0.018f);
                sky.SetFloat("_SunSizeConvergence", 8.5f);
                sky.SetFloat("_AtmosphereThickness", 0.78f);
                sky.SetColor("_SkyTint", new Color(0.3f, 0.52f, 0.78f));
                sky.SetColor("_GroundColor", new Color(0.44f, 0.46f, 0.44f));
                sky.SetFloat("_Exposure", 1.05f);
                RenderSettings.skybox = sky;
            }
            RenderSettings.sun = sun;
            RenderSettings.fog = true;
            RenderSettings.fogMode = FogMode.Linear;
            RenderSettings.fogStartDistance = 280f;
            RenderSettings.fogEndDistance = 1900f;
            RenderSettings.ambientMode = AmbientMode.Trilight;
            RenderSettings.ambientIntensity = 0.88f;
            RenderSettings.ambientSkyColor = new Color(0.65f, 0.69f, 0.77f);
            RenderSettings.ambientEquatorColor = new Color(0.5f, 0.52f, 0.53f);
            RenderSettings.ambientGroundColor = new Color(0.4f, 0.41f, 0.4f);
            RenderSettings.reflectionIntensity = 1f;
            RenderSettings.defaultReflectionMode = DefaultReflectionMode.Skybox;

            CreatePostProcessing();
            SetMode("clear");
            DynamicGI.UpdateEnvironment();
        }

        public void SetMode(string mode)
        {
            if (sun == null) return;
            color.postExposure.value = 0.3f;
            color.saturation.value = 0f;
            color.contrast.value = 5f;
            whiteBalance.temperature.value = 0f;
            sun.intensity = 1.38f;
            sun.color = new Color(1f, 0.955f, 0.89f);
            sun.transform.rotation = Quaternion.Euler(43f, -126f, 0f);
            RenderSettings.fogColor = new Color(0.7f, 0.8f, 0.89f);
            RenderSettings.ambientSkyColor = new Color(0.68f, 0.73f, 0.8f);
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
            color.postExposure.Override(0.3f);
            color.contrast.Override(5f);
            color.saturation.Override(0f);
            whiteBalance = profile.Add<WhiteBalance>(true);
            whiteBalance.temperature.Override(0f);
            var bloom = profile.Add<Bloom>(true);
            bloom.threshold.Override(1.35f);
            bloom.intensity.Override(0.04f);
            bloom.scatter.Override(0.42f);
            // At this intensity Bloom is visually imperceptible in the sunny
            // scene, but still allocates and samples a downsample pyramid.
            bloom.active = false;
            var vignette = profile.Add<Vignette>(true);
            vignette.intensity.Override(0f);
            vignette.smoothness.Override(0.32f);
        }

    }
}
