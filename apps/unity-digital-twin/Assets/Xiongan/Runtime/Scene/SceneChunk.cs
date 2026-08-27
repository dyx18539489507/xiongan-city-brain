using UnityEngine;

namespace Xiongan.DigitalTwin.Scene
{
    public enum SceneDetailClass
    {
        Essential = 0,
        Context = 1,
        Fine = 2,
    }

    [DisallowMultipleComponent]
    public sealed class SceneChunk : MonoBehaviour
    {
        [SerializeField] private SceneDetailClass detailClass;

        public SceneDetailClass DetailClass => detailClass;
        public Renderer Renderer => GetComponent<Renderer>();

        public void Configure(SceneDetailClass value)
        {
            detailClass = value;
        }
    }
}
