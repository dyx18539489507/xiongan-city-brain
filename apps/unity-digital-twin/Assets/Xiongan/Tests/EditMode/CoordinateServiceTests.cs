using NUnit.Framework;
using UnityEngine;
using Xiongan.DigitalTwin.Core;
using Xiongan.DigitalTwin.Data;

namespace Xiongan.DigitalTwin.Tests
{
    public sealed class CoordinateServiceTests
    {
        [Test]
        public void K06UsesTheSharedFloatingOrigin()
        {
            var service = new CoordinateService(new Point2 { X = 3691.65f, Y = 6515.815f });
            var world = service.ToWorld(4005.52f, 5451.76f);
            Assert.That(world.x, Is.EqualTo(313.87f).Within(0.002f));
            Assert.That(world.y, Is.EqualTo(0f).Within(0.001f));
            Assert.That(world.z, Is.EqualTo(1064.055f).Within(0.002f));
        }

        [Test]
        public void SumoHeadingMapsToUnityYaw()
        {
            var service = new CoordinateService(new Point2());
            AssertHeading(service, 0f, Vector3.back);
            AssertHeading(service, 90f, Vector3.right);
            AssertHeading(service, 180f, Vector3.forward);
            AssertHeading(service, 270f, Vector3.left);
        }

        private static void AssertHeading(CoordinateService service, float sumoHeading, Vector3 expected)
        {
            var actual = service.ToWorldRotation(sumoHeading) * Vector3.forward;
            Assert.That(Vector3.Angle(actual, expected), Is.LessThan(0.001f));
        }
    }
}
