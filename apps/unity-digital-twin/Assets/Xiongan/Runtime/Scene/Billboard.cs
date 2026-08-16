using UnityEngine;

namespace Xiongan.DigitalTwin.Scene
{
    public sealed class Billboard : MonoBehaviour
    {
        private void LateUpdate()
        {
            var camera = Camera.main;
            if (camera == null) return;
            transform.rotation = Quaternion.LookRotation(transform.position - camera.transform.position, Vector3.up);
        }
    }
}
