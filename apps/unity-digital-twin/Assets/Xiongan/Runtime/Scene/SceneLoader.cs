using System;
using System.Collections;
using Newtonsoft.Json;
using UnityEngine;
using UnityEngine.Networking;
using Xiongan.DigitalTwin.Data;

namespace Xiongan.DigitalTwin.Scene
{
    public sealed class SceneLoader : MonoBehaviour
    {
        public IEnumerator Load(string url, string expectedScenarioId, Action<float, string> onProgress, Action<SceneDocument> onLoaded, Action<string> onError)
        {
            onProgress(0.02f, "正在读取当前 SUMO 场景");
            using var request = UnityWebRequest.Get(url);
            request.SetRequestHeader("Accept", "application/json");
            var operation = request.SendWebRequest();
            while (!operation.isDone)
            {
                onProgress(Mathf.Lerp(0.02f, 0.32f, request.downloadProgress), "正在下载场景几何");
                yield return null;
            }
            if (request.result != UnityWebRequest.Result.Success)
            {
                onError($"场景下载失败：{request.error}");
                yield break;
            }

            SceneDocument? document;
            try
            {
                onProgress(0.36f, "正在解析SUMO场景数据");
                document = Deserialize(request.downloadHandler.text);
            }
            catch (Exception error)
            {
                onError($"场景解析失败：{error.Message}");
                yield break;
            }
            var validationError = Validate(document, expectedScenarioId);
            if (validationError != null)
            {
                onError(validationError);
                yield break;
            }
            onLoaded(document!);
        }

        public static string? Validate(SceneDocument? document, string expectedScenarioId)
        {
            if (document == null ||
                document.Metadata.SceneId != expectedScenarioId ||
                document.Metadata.ScenarioId != expectedScenarioId)
                return "场景身份校验失败";
            if (document.Junctions.Count == 0 || document.Lanes.Count == 0)
                return "场景不包含可构建的 SUMO 路口和车道";
            return null;
        }

        public static SceneDocument? Deserialize(string json) =>
            JsonConvert.DeserializeObject<SceneDocument>(json);
    }
}
