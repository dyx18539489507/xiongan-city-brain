using System.Linq;
using UnityEditor;
using UnityEngine;

namespace Xiongan.DigitalTwin.Editor
{
    public static class VehicleAssetAudit
    {
        public static void Print()
        {
            foreach (var path in new[]
                     {
                         "Assets/Xiongan/Resources/Art/Models/cc0_car/car_lyricsz_cc0.fbx",
                         "Assets/Xiongan/Resources/Art/Models/cc0_car/car_byzmod3d_high_cc0.fbx",
                     })
            {
                var source = AssetDatabase.LoadAssetAtPath<GameObject>(path);
                if (source == null)
                {
                    Debug.LogError($"VEHICLE_AUDIT missing={path}");
                    continue;
                }
                var instance = Object.Instantiate(source);
                var renderers = instance.GetComponentsInChildren<Renderer>(true);
                var bounds = renderers.Length == 0 ? new Bounds(Vector3.zero, Vector3.zero) : renderers[0].bounds;
                foreach (var renderer in renderers.Skip(1)) bounds.Encapsulate(renderer.bounds);
                Debug.Log($"VEHICLE_AUDIT path={path} bounds={bounds.size} center={bounds.center} renderers={renderers.Length}");
                foreach (var renderer in renderers)
                    Debug.Log($"VEHICLE_NODE model={source.name} name={renderer.name} material={renderer.sharedMaterial?.name}");
                Object.DestroyImmediate(instance);
            }
        }
    }
}
