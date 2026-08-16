using System.Linq;
using NUnit.Framework;
using UnityEngine;

namespace Xiongan.DigitalTwin.Tests
{
    public sealed class MobilityAssetTests
    {
        [Test]
        public void PedestrianAssetContainsArticulatedBodyMesh()
        {
            var model = Resources.Load<GameObject>("Art/Models/generated_mobility/pedestrian_hq");
            Assert.That(model, Is.Not.Null);
            var names = model!.GetComponentsInChildren<Transform>(true).Select(item => item.name).ToHashSet();
            Assert.That(names, Does.Contain("Hip_L"));
            Assert.That(names, Does.Contain("Knee_R"));
            Assert.That(names, Does.Contain("Shoulder_L"));
            Assert.That(model.GetComponentsInChildren<MeshRenderer>(true).Length, Is.GreaterThan(20));
        }

        [Test]
        public void BicycleAssetContainsMechanicalAndRiderDetail()
        {
            var model = Resources.Load<GameObject>("Art/Models/generated_mobility/bicycle_rider_hq");
            Assert.That(model, Is.Not.Null);
            var names = model!.GetComponentsInChildren<Transform>(true).Select(item => item.name).ToHashSet();
            foreach (var required in new[]
                     {
                         "Wheel_Front", "Wheel_Rear", "Crank", "Chainring",
                         "Rider_Hip_L", "Rider_Knee_R", "Rider_Shoulder_L",
                     })
                Assert.That(names, Does.Contain(required), required);
            Assert.That(names.Count(item => item.StartsWith("Wheel_Front_Spoke_")), Is.EqualTo(12));
            Assert.That(names.Count(item => item.StartsWith("Wheel_Rear_Spoke_")), Is.EqualTo(12));
            Assert.That(model.GetComponentsInChildren<MeshRenderer>(true).Length, Is.GreaterThan(50));
        }
    }
}
