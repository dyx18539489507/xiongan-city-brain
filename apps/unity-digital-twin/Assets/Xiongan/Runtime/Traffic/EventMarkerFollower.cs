using UnityEngine;

namespace Xiongan.DigitalTwin.Traffic
{
    public sealed class EventMarkerFollower : MonoBehaviour
    {
        public Transform? Target;
        public Vector3 Offset = Vector3.up * 2.8f;

        private void LateUpdate()
        {
            if (Target != null) transform.position = Target.position + Offset;
        }
    }
}
