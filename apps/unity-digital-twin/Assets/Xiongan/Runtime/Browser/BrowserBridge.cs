using System.Runtime.InteropServices;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace Xiongan.DigitalTwin.Browser
{
    public sealed class BrowserBridge : MonoBehaviour
    {
#if UNITY_WEBGL && !UNITY_EDITOR
        [DllImport("__Internal")] private static extern void XionganDispatchBrowserEvent(string payload);
#endif

        public void Emit(string type, object? payload = null)
        {
            var message = new JObject { ["type"] = type };
            if (payload != null) message["payload"] = JToken.FromObject(payload);
            var json = message.ToString(Formatting.None);
#if UNITY_WEBGL && !UNITY_EDITOR
            XionganDispatchBrowserEvent(json);
#else
            Debug.Log($"Browser event: {json}");
#endif
        }
    }
}
