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
        public IEnumerator Load(string url, Action<float, string> onProgress, Action<SceneDocument> onLoaded, Action<string> onError)
        {
            onProgress(0.02f, "正在读取20路口场景");
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
                document = JsonConvert.DeserializeObject<SceneDocument>(request.downloadHandler.text);
            }
            catch (Exception error)
            {
                onError($"场景解析失败：{error.Message}");
                yield break;
            }
            if (document == null || document.Metadata.SceneId != "xiongan_rongdong_20")
            {
                onError("场景身份校验失败");
                yield break;
            }
            if (document.TrafficLights.Count != 20)
            {
                onError($"受控信号路口数量错误：{document.TrafficLights.Count}/20");
                yield break;
            }
            onLoaded(document);
        }
    }
}
