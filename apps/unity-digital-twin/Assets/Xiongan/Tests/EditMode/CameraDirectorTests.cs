using NUnit.Framework;
using UnityEngine;
using UnityEngine.Rendering.Universal;
using Xiongan.DigitalTwin.CameraSystem;

namespace Xiongan.DigitalTwin.Tests
{
    public sealed class CameraDirectorTests
    {
        [Test]
        public void ZoomDistanceClampsLargeWheelBursts()
        {
            var clamped = CameraDirector.CalculateZoomDistance(1000f, 2.5f);

            Assert.That(
                CameraDirector.CalculateZoomDistance(1000f, 250f),
                Is.EqualTo(clamped).Within(0.001f));
        }

        [Test]
        public void ZoomDistanceIsSymmetricAndRespectsLimits()
        {
            var zoomedIn = CameraDirector.CalculateZoomDistance(1000f, 1f);
            var restored = CameraDirector.CalculateZoomDistance(zoomedIn, -1f);

            Assert.That(restored, Is.EqualTo(1000f).Within(0.001f));
            Assert.That(CameraDirector.CalculateZoomDistance(4f, 2f), Is.EqualTo(4f));
            Assert.That(CameraDirector.CalculateZoomDistance(3500f, -2f), Is.EqualTo(3500f));
        }

        [TestCase(4f, 0.3f)]
        [TestCase(160f, 4f)]
        [TestCase(1180f, 29.5f)]
        [TestCase(2750f, 68.75f)]
        [TestCase(10000f, 96f)]
        public void NearClipPlaneExpandsWithViewDistance(float distance, float expected)
        {
            Assert.That(
                StableCameraRendering.CalculateNearClipPlane(distance),
                Is.EqualTo(expected).Within(0.001f));
        }

        [Test]
        public void CameraMotionConvergesWithinAQuarterSecond()
        {
            var retainedError = 1f;
            for (var frame = 0; frame < 15; frame++)
                retainedError *= 1f - StableCameraRendering.CalculateMotionBlend(1f / 60f);

            Assert.That(retainedError, Is.LessThan(0.001f));
        }

        [Test]
        public void StableCameraUsesTemporalAntialiasingAndDepth()
        {
            var cameraObject = new GameObject("stable-camera-test");
            try
            {
                var cameraComponent = cameraObject.AddComponent<Camera>();
                var cameraData = cameraObject.AddComponent<UniversalAdditionalCameraData>();

                StableCameraRendering.ConfigureCamera(cameraComponent, cameraData, 2750f);

                Assert.That(cameraComponent.allowMSAA, Is.False);
                Assert.That(cameraComponent.allowDynamicResolution, Is.False);
                Assert.That(cameraComponent.nearClipPlane, Is.EqualTo(68.75f).Within(0.001f));
                Assert.That(cameraComponent.farClipPlane, Is.EqualTo(6200f));
                Assert.That(cameraData.requiresDepthTexture, Is.True);
                Assert.That(cameraData.antialiasing, Is.EqualTo(AntialiasingMode.TemporalAntiAliasing));
                Assert.That(cameraData.dithering, Is.False);
            }
            finally
            {
                Object.DestroyImmediate(cameraObject);
            }
        }
    }
}
