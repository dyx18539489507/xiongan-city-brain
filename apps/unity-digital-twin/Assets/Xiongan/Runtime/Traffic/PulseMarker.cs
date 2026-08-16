using UnityEngine;

namespace Xiongan.DigitalTwin.Traffic
{
    public sealed class PulseMarker : MonoBehaviour
    {
        public Vector3 BaseScale = Vector3.one;

        private void Update()
        {
            var pulse = 0.82f + Mathf.Sin(Time.time * 5f) * 0.18f;
            transform.localScale = new Vector3(BaseScale.x * pulse, BaseScale.y, BaseScale.z * pulse);
        }
    }
}
