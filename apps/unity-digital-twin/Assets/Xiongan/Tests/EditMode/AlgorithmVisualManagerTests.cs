using System.Collections.Generic;
using System.Reflection;
using NUnit.Framework;
using UnityEngine;
using Xiongan.DigitalTwin.Data;
using Xiongan.DigitalTwin.Traffic;

namespace Xiongan.DigitalTwin.Tests.EditMode
{
    public sealed class AlgorithmVisualManagerTests
    {
        [Test]
        public void EvidenceLayerCanBeHiddenByTheBrowserCommand()
        {
            var root = new GameObject("算法证据测试");
            try
            {
                var manager = root.AddComponent<AlgorithmVisualManager>();

                manager.SetVisible(false);

                Assert.That(root.activeSelf, Is.False);
            }
            finally
            {
                Object.DestroyImmediate(root);
            }
        }

        [Test]
        public void QueueTailUsesMeasuredLengthAndEndsAtStopLine()
        {
            var method = typeof(AlgorithmVisualManager).GetMethod(
                "Tail",
                BindingFlags.NonPublic | BindingFlags.Static);
            Assert.That(method, Is.Not.Null);
            var points = new List<Vector3>
            {
                new(0f, 0f, 0f),
                new(0f, 0f, 10f),
                new(0f, 0f, 20f),
            };

            var tail = method!.Invoke(null, new object[] { points, 6f })
                as IReadOnlyList<Vector3>;

            Assert.That(tail, Is.Not.Null);
            Assert.That(tail!.Count, Is.EqualTo(2));
            Assert.That(tail[0].z, Is.EqualTo(14f).Within(0.001f));
            Assert.That(tail[1].z, Is.EqualTo(20f).Within(0.001f));
        }

        [Test]
        public void BrowserSnapshotCarriesIntersectionEvidence()
        {
            var field = typeof(BrowserSnapshot).GetField("IntersectionMetrics");

            Assert.That(field, Is.Not.Null);
            Assert.That(field!.FieldType.Name, Is.EqualTo("JArray"));
        }
    }
}
