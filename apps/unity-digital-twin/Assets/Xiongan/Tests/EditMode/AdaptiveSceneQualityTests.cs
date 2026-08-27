using NUnit.Framework;
using UnityEngine.Rendering;
using Xiongan.DigitalTwin.CameraSystem;
using Xiongan.DigitalTwin.Scene;

namespace Xiongan.DigitalTwin.Tests
{
    public sealed class AdaptiveSceneQualityTests
    {
        [TestCase(SceneDetailClass.Essential)]
        [TestCase(SceneDetailClass.Context)]
        [TestCase(SceneDetailClass.Fine)]
        public void CameraDistanceNeverForcesGeometryOff(SceneDetailClass detailClass)
        {
            Assert.That(
                AdaptiveSceneQuality.ShouldKeepRendererEnabled(
                    detailClass,
                    float.MaxValue,
                    1f,
                    1f),
                Is.True);
        }

        [TestCase(ShadowCastingMode.Off)]
        [TestCase(ShadowCastingMode.On)]
        [TestCase(ShadowCastingMode.TwoSided)]
        [TestCase(ShadowCastingMode.ShadowsOnly)]
        public void CameraMotionPreservesAuthoredShadowMode(ShadowCastingMode originalMode)
        {
            Assert.That(
                AdaptiveSceneQuality.ResolveStableShadowMode(originalMode),
                Is.EqualTo(originalMode));
        }
    }
}
