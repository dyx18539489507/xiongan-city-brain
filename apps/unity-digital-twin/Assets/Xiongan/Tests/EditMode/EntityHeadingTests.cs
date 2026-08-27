using NUnit.Framework;
using UnityEngine;
using Xiongan.DigitalTwin.Entities;

namespace Xiongan.DigitalTwin.Tests
{
    public sealed class EntityHeadingTests
    {
        [Test]
        public void MovingActorFacesItsMeasuredTravelDirection()
        {
            var reported = Quaternion.LookRotation(Vector3.left, Vector3.up);
            var resolved = EntityActor.ResolveFacingRotation(
                Vector3.zero,
                Vector3.right * 4f,
                reported,
                8f,
                true,
                20f);

            Assert.That(Vector3.Angle(resolved * Vector3.forward, Vector3.right), Is.LessThan(0.001f));
        }

        [Test]
        public void StationaryActorKeepsItsReportedHeading()
        {
            var reported = Quaternion.Euler(0f, 37f, 0f);
            var resolved = EntityActor.ResolveFacingRotation(
                Vector3.zero,
                Vector3.right * 0.1f,
                reported,
                0f,
                true,
                5f);

            Assert.That(Quaternion.Angle(resolved, reported), Is.LessThan(0.001f));
        }

        [Test]
        public void TeleportDoesNotCreateAFalseHeading()
        {
            var reported = Quaternion.Euler(0f, 82f, 0f);
            var resolved = EntityActor.ResolveFacingRotation(
                Vector3.zero,
                Vector3.forward * 200f,
                reported,
                5f,
                true,
                18f);

            Assert.That(Quaternion.Angle(resolved, reported), Is.LessThan(0.001f));
        }
    }
}
