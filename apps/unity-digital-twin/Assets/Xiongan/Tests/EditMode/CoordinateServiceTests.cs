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
            Assert.That(Quaternion.Angle(service.ToWorldRotation(90f), Quaternion.Euler(0f, -90f, 0f)), Is.LessThan(0.001f));
        }
    }
}
