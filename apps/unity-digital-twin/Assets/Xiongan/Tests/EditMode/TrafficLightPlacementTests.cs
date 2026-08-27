using System.Collections.Generic;
using System.Linq;
using NUnit.Framework;
using UnityEngine;
using Xiongan.DigitalTwin.Scene;
using Xiongan.DigitalTwin.Traffic;

namespace Xiongan.DigitalTwin.Tests
{
    public sealed class TrafficLightPlacementTests
    {
        [Test]
        public void NorthboundApproachPlacesPoleBeyondRightmostLane()
        {
            var lanes = new List<SignalApproachLane>
            {
                new("north-0", 0, new Vector3(0f, 0f, 0f), Vector3.back, 3.2f),
                new("north-1", 1, new Vector3(3.2f, 0f, 0f), Vector3.back, 3.2f),
            };

            var placement = TrafficLightPlacementRules.Resolve(lanes);

            Assert.That(placement.TrafficRight.x, Is.GreaterThan(0.99f));
            Assert.That(placement.PolePosition.x, Is.GreaterThan(4.8f));
            Assert.That(placement.PolePosition.z, Is.GreaterThan(0f));
        }

        [Test]
        public void PlacementSearchMovesPastBlockedRoadShoulder()
        {
            var lanes = new List<SignalApproachLane>
            {
                new("north-0", 0, Vector3.zero, Vector3.back, 3.2f),
            };

            var placement = TrafficLightPlacementRules.Resolve(lanes, candidate => candidate.x < 5f);

            Assert.That(placement.PolePosition.x, Is.GreaterThanOrEqualTo(5f));
        }

        [Test]
        public void PolygonCheckHandlesBothWindingDirections()
        {
            var clockwise = new[]
            {
                new Vector3(-2f, 0f, -2f), new Vector3(-2f, 0f, 2f),
                new Vector3(2f, 0f, 2f), new Vector3(2f, 0f, -2f),
            };
            var counterClockwise = new[]
            {
                new Vector3(-2f, 0f, -2f), new Vector3(2f, 0f, -2f),
                new Vector3(2f, 0f, 2f), new Vector3(-2f, 0f, 2f),
            };

            Assert.That(TrafficLightPlacementRules.PointInPolygonXZ(Vector3.zero, clockwise), Is.True);
            Assert.That(TrafficLightPlacementRules.PointInPolygonXZ(Vector3.zero, counterClockwise), Is.True);
            Assert.That(TrafficLightPlacementRules.PointInPolygonXZ(new Vector3(4f, 0f, 0f), clockwise), Is.False);
        }

        [Test]
        public void ShowcaseNorthApproachUsesFarSideFootwayCorner()
        {
            var frame = new ReferenceShowcaseFrame(Vector3.zero, Vector3.forward);
            var lanes = new List<SignalApproachLane>
            {
                new("showcase-0", 0, new Vector3(6f, 0f, -33f), Vector3.forward, 3.2f),
                new("showcase-1", 1, new Vector3(12f, 0f, -33f), Vector3.forward, 3.2f),
            };

            var placement = TrafficLightPlacementRules.ResolveShowcase(frame, lanes);

            Assert.That(placement.PolePosition.x, Is.EqualTo(27.35f).Within(0.001f));
            Assert.That(placement.PolePosition.z, Is.EqualTo(36.5f).Within(0.001f));
            Assert.That(placement.TrafficRight.x, Is.GreaterThan(0.99f));
            var headOffset = TrafficLightPlacementRules.ResolveHeadOffset(
                lanes, placement.PolePosition, placement.Forward, 6.2f, 9.6f);
            Assert.That(headOffset, Is.EqualTo(-9.6f).Within(0.001f));
            Assert.That(placement.PolePosition.x + headOffset, Is.EqualTo(17.75f).Within(0.001f));
            Assert.That(ReferenceShowcaseLayout.IsSignalPoleOnInnerFootwayEdge(
                frame, placement.PolePosition), Is.True);
            Assert.That(ReferenceShowcaseLayout.IsSignalPoleOnFarSide(
                frame, placement.PolePosition, placement.Forward), Is.True);
        }

        [Test]
        public void ShowcaseCrossApproachUsesDifferentFarSideCorner()
        {
            var frame = new ReferenceShowcaseFrame(Vector3.zero, Vector3.forward);
            var lanes = new List<SignalApproachLane>
            {
                new("showcase-cross", 0, new Vector3(-34f, 0f, -12f), Vector3.right, 3.2f),
            };

            var placement = TrafficLightPlacementRules.ResolveShowcase(frame, lanes);

            Assert.That(placement.PolePosition.x, Is.EqualTo(37.5f).Within(0.001f));
            Assert.That(placement.PolePosition.z, Is.EqualTo(-26.35f).Within(0.001f));
            Assert.That(ReferenceShowcaseLayout.IsSignalPoleOnInnerFootwayEdge(
                frame, placement.PolePosition), Is.True);
            Assert.That(ReferenceShowcaseLayout.IsSignalPoleOnFarSide(
                frame, placement.PolePosition, placement.Forward), Is.True);
        }

        [TestCase("rsu", 118f)]
        [TestCase("camera", -118f)]
        public void ShowcaseRoadsideDevicesUseFarOuterFootway(string type, float expectedAcross)
        {
            var frame = new ReferenceShowcaseFrame(Vector3.zero, Vector3.forward);

            var position = ReferenceShowcaseLayout.ResolveRoadsideDevicePosition(frame, type);

            Assert.That(position.x, Is.EqualTo(expectedAcross).Within(0.001f));
            Assert.That(position.z, Is.EqualTo(29.4f).Within(0.001f));
            Assert.That(ReferenceShowcaseLayout.IsRoadsideDeviceOnOuterFootway(frame, position), Is.True);
        }

        [Test]
        public void ShowcaseRoadsideDeviceRejectsRoadAndHeroSightline()
        {
            var frame = new ReferenceShowcaseFrame(Vector3.zero, Vector3.forward);

            Assert.That(ReferenceShowcaseLayout.IsRoadsideDeviceOnOuterFootway(
                frame, frame.Point(0f, 0f, 29.4f)), Is.False);
            Assert.That(ReferenceShowcaseLayout.IsRoadsideDeviceOnOuterFootway(
                frame, frame.Point(24f, 0f, 0f)), Is.False);
        }

        [Test]
        public void ShowcaseFourApproachesUseFourUniqueFarSideFootwayCorners()
        {
            var frame = new ReferenceShowcaseFrame(Vector3.zero, Vector3.forward);
            var cases = new[]
            {
                (Forward: Vector3.forward, Expected: new Vector2(27.35f, 36.5f)),
                (Forward: Vector3.back, Expected: new Vector2(-27.35f, -36.5f)),
                (Forward: Vector3.right, Expected: new Vector2(37.5f, -26.35f)),
                (Forward: Vector3.left, Expected: new Vector2(-37.5f, 26.35f)),
            };

            foreach (var item in cases)
            {
                var lanes = new List<SignalApproachLane>
                {
                    new("showcase", 0, Vector3.zero, item.Forward, 3.2f),
                };
                var position = TrafficLightPlacementRules.ResolveShowcase(frame, lanes).PolePosition;
                Assert.That(position.x, Is.EqualTo(item.Expected.x).Within(0.001f));
                Assert.That(position.z, Is.EqualTo(item.Expected.y).Within(0.001f));
                Assert.That(ReferenceShowcaseLayout.IsSignalPoleOnFarSide(
                    frame, position, item.Forward), Is.True);
            }
        }

        [Test]
        public void ShowcasePedestrianFacesLookBackAcrossBothAdjacentCrossings()
        {
            var frame = new ReferenceShowcaseFrame(Vector3.zero, Vector3.forward);
            var cases = new[]
            {
                Vector3.forward,
                Vector3.back,
                Vector3.right,
                Vector3.left,
            };

            foreach (var forward in cases)
            {
                var lanes = new List<SignalApproachLane>
                {
                    new("showcase", 0, Vector3.zero, forward, 3.2f),
                };
                var placement = TrafficLightPlacementRules.ResolveShowcase(frame, lanes);
                var directions = TrafficLightPlacementRules.ResolvePedestrianFaceDirections(placement);
                var towardJunction = Vector3.ProjectOnPlane(
                    frame.Center - placement.PolePosition, Vector3.up).normalized;

                Assert.That(Vector3.Dot(directions.AcrossCrossing, towardJunction), Is.GreaterThan(0.45f));
                Assert.That(Vector3.Dot(directions.AlongCrossing, towardJunction), Is.GreaterThan(0.45f));
                Assert.That(Vector3.Dot(
                    directions.AcrossCrossing, directions.AlongCrossing), Is.EqualTo(0f).Within(0.001f));
            }
        }

        [Test]
        public void ShowcaseSurfaceOverrideIsSingleCrossNotCornerRectangle()
        {
            var frame = new ReferenceShowcaseFrame(Vector3.zero, Vector3.forward);

            Assert.That(ReferenceShowcaseLayout.CoversRoadSurfaceOverride(
                frame, frame.Point(20f, 0f, 120f)), Is.True);
            Assert.That(ReferenceShowcaseLayout.CoversRoadSurfaceOverride(
                frame, frame.Point(120f, 0f, 20f)), Is.True);
            Assert.That(ReferenceShowcaseLayout.CoversRoadSurfaceOverride(
                frame, frame.Point(60f, 0f, 60f)), Is.False);
        }

        [Test]
        public void CivicHallStopsBeforeMainFacadeInsteadOfIntersectingIt()
        {
            var frame = new ReferenceShowcaseFrame(Vector3.zero, Vector3.forward);
            const float mainFrontAlong = 68f;
            var hall = ReferenceShowcaseBuilder.CreateCivicHallFootprint(
                frame, 61.8f, 69.4f, mainFrontAlong,
                11.8f, 12.8f, 0.18f, 18);

            Assert.That(hall, Has.Count.EqualTo(19));
            foreach (var point in hall)
            {
                var local = ReferenceShowcaseLayout.ToLocal(frame, point);
                Assert.That(local.y, Is.LessThanOrEqualTo(mainFrontAlong - 0.179f));
            }
            Assert.That(hall.Min(point => ReferenceShowcaseLayout.ToLocal(frame, point).y),
                Is.LessThan(57f));
        }
    }
}
