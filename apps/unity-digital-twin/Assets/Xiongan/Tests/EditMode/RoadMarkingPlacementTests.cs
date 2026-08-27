using NUnit.Framework;
using UnityEngine;
using Xiongan.DigitalTwin.Scene;

namespace Xiongan.DigitalTwin.Tests
{
    public sealed class RoadMarkingPlacementTests
    {
        [Test]
        public void ArrowUsesTheTangentAtItsResolvedPosition()
        {
            var points = new[]
            {
                new Vector3(0f, 0f, 0f),
                new Vector3(0f, 0f, 30f),
                new Vector3(20f, 0f, 30f),
            };

            var resolved = RoadMarkingPlacementRules.TryResolveArrow(points, out var position, out var forward);

            Assert.That(resolved, Is.True);
            Assert.That(position.z, Is.EqualTo(30f).Within(0.001f));
            Assert.That(forward.x, Is.GreaterThan(0.99f));
        }

        [Test]
        public void DirectionSetKeepsEveryLegalSumoMovement()
        {
            var directions = RoadMarkingPlacementRules.NormaliseDirections(new[] { "r", "s", "l", "s" });
            Assert.That(directions, Is.EqualTo("lsr"));
        }

        [Test]
        public void DisplayDirectionAvoidsUnreadableThreeHeadedGlyph()
        {
            var directions = RoadMarkingPlacementRules.SelectDisplayDirections(new[] { "r", "s", "l" });
            Assert.That(directions, Is.EqualTo("s"));
        }

        [Test]
        public void VeryShortLaneDoesNotReceiveAnUnreadableArrow()
        {
            var points = new[] { Vector3.zero, new Vector3(0f, 0f, 5f) };
            Assert.That(RoadMarkingPlacementRules.TryResolveArrow(points, out _, out _), Is.False);
        }

        [Test]
        public void LaneShorterThanStandardSetbackDoesNotReceiveArrow()
        {
            var points = new[] { Vector3.zero, new Vector3(0f, 0f, 16f) };
            Assert.That(RoadMarkingPlacementRules.TryResolveArrow(points, out _, out _), Is.False);
        }

        [Test]
        public void ArrowTrianglesFaceUpForEveryRoadHeading()
        {
            var accumulator = new MeshAccumulator();
            accumulator.AddArrow(new Vector3(-12f, 0f, 0f), Vector3.forward, "lsr", 0.1f);
            accumulator.AddArrow(new Vector3(-4f, 0f, 0f), Vector3.back, "lsr", 0.1f);
            accumulator.AddArrow(new Vector3(4f, 0f, 0f), Vector3.right, "lsr", 0.1f);
            accumulator.AddArrow(new Vector3(12f, 0f, 0f), Vector3.left, "lsr", 0.1f);
            var holder = new GameObject("arrow-winding-test");

            try
            {
                var root = accumulator.Build("arrows", null!, holder.transform, false);
                var mesh = root.GetComponentInChildren<MeshFilter>().sharedMesh;
                var vertices = mesh.vertices;
                var triangles = mesh.triangles;

                for (var index = 0; index < triangles.Length; index += 3)
                {
                    var normal = Vector3.Cross(
                        vertices[triangles[index + 1]] - vertices[triangles[index]],
                        vertices[triangles[index + 2]] - vertices[triangles[index]]);
                    Assert.That(Vector3.Dot(normal.normalized, Vector3.up), Is.GreaterThan(0.99f));
                }
            }
            finally
            {
                Object.DestroyImmediate(holder);
            }
        }
    }
}
