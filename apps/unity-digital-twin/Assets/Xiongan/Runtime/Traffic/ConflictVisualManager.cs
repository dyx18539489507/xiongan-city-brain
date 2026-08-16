using System.Collections.Generic;
using UnityEngine;
using Xiongan.DigitalTwin.Core;
using Xiongan.DigitalTwin.Data;

namespace Xiongan.DigitalTwin.Traffic
{
    public sealed class ConflictVisualManager : MonoBehaviour
    {
        private readonly Dictionary<string, GameObject> visuals = new();
        private CoordinateService coordinates = null!;
        private MaterialLibrary materials = null!;

        public void Initialise(CoordinateService coordinateService, MaterialLibrary materialLibrary)
        {
            coordinates = coordinateService;
            materials = materialLibrary;
        }

        public void Apply(IEnumerable<ConflictEntity> conflicts)
        {
            var active = new HashSet<string>();
            foreach (var conflict in conflicts)
            {
                active.Add(conflict.Id);
                if (!visuals.TryGetValue(conflict.Id, out var visual))
                {
                    visual = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
                    visual.name = $"安全冲突-{conflict.Id}";
                    visual.transform.SetParent(transform, false);
                    visual.GetComponent<Renderer>().sharedMaterial = materials.Alert;
                    Object.Destroy(visual.GetComponent<Collider>());
                    visual.AddComponent<PulseMarker>();
                    visuals[conflict.Id] = visual;
                }
                visual.transform.position = coordinates.ToWorld(conflict.X, conflict.Y, 0.12f);
                visual.GetComponent<PulseMarker>().BaseScale = conflict.Severity == "critical" ? new Vector3(5f, 0.06f, 5f) : new Vector3(3f, 0.04f, 3f);
            }
            foreach (var id in new List<string>(visuals.Keys))
            {
                if (active.Contains(id)) continue;
                Destroy(visuals[id]);
                visuals.Remove(id);
            }
        }

    }
}
