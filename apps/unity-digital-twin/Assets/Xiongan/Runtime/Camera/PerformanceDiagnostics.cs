using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

namespace Xiongan.DigitalTwin.CameraSystem
{
    public sealed class PerformanceDiagnostics : MonoBehaviour
    {
        private readonly Queue<float> frameTimes = new();
        private AdaptiveSceneQuality quality = null!;
        private bool visible;
        private float nextSample;
        private float fps;
        private float p95Ms;

        public void Initialise(AdaptiveSceneQuality adaptiveQuality)
        {
            quality = adaptiveQuality;
            visible = !string.IsNullOrWhiteSpace(Application.absoluteURL) &&
                      Application.absoluteURL.Contains("perf=1", StringComparison.OrdinalIgnoreCase);
        }

        private void Update()
        {
            if (Input.GetKeyDown(KeyCode.F3)) visible = !visible;
            var milliseconds = Mathf.Min(Time.unscaledDeltaTime, 1f) * 1000f;
            frameTimes.Enqueue(milliseconds);
            while (frameTimes.Count > 240) frameTimes.Dequeue();
            if (Time.unscaledTime < nextSample || frameTimes.Count == 0) return;
            nextSample = Time.unscaledTime + 0.75f;
            var samples = frameTimes.OrderBy(value => value).ToArray();
            var average = samples.Average();
            fps = average <= 0.001f ? 0f : 1000f / average;
            p95Ms = samples[Mathf.Clamp(Mathf.CeilToInt(samples.Length * 0.95f) - 1, 0, samples.Length - 1)];
        }

        private void OnGUI()
        {
            if (!visible || quality == null) return;
            var area = new Rect(16f, 16f, 260f, 92f);
            GUI.Box(area, GUIContent.none);
            GUI.Label(new Rect(28f, 26f, 230f, 22f), $"FPS {fps:0.0}   P95 {p95Ms:0.0} ms");
            GUI.Label(new Rect(28f, 50f, 230f, 22f), $"QUALITY {quality.ProfileName}");
            GUI.Label(new Rect(28f, 74f, 230f, 22f), $"CHUNKS {quality.ActiveChunkCount}/{quality.TotalChunkCount}");
        }
    }
}
