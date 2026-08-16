using System;
using System.Collections.Concurrent;
using System.Net.WebSockets;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using UnityEngine;
using Xiongan.DigitalTwin.Data;
using Xiongan.DigitalTwin.Entities;
using Xiongan.DigitalTwin.Traffic;

namespace Xiongan.DigitalTwin.Network
{
    public sealed class DigitalTwinClient : MonoBehaviour
    {
        public string ConnectionState { get; private set; } = "connecting";
        public string? ExperimentId { get; private set; }
        public float SimulationTimeS { get; private set; }
        public JObject Metrics { get; private set; } = new();
        public event Action<string>? StateChanged;
        public event Action<JObject>? MessageApplied;

        private readonly ConcurrentQueue<string> messages = new();
        private EntityManager entities = null!;
        private TrafficLightManager trafficLights = null!;
        private ConflictVisualManager conflicts = null!;
        private EventVisualManager events = null!;
        private string url = string.Empty;
        private long lastSequence = -1;
        private bool initialised;
        private bool externalReplay;
        private float reconnectAt;
        private int reconnectAttempt;

#if UNITY_WEBGL && !UNITY_EDITOR
        [DllImport("__Internal")] private static extern int XionganWebSocketConnect(string url, string gameObjectName);
        [DllImport("__Internal")] private static extern void XionganWebSocketClose(int socketId);
        private int socketId = -1;
#else
        private ClientWebSocket? editorSocket;
        private CancellationTokenSource? cancellation;
#endif

        public void Initialise(string socketUrl, EntityManager entityManager, TrafficLightManager lightManager, ConflictVisualManager conflictManager, EventVisualManager eventManager)
        {
            url = socketUrl;
            entities = entityManager;
            trafficLights = lightManager;
            conflicts = conflictManager;
            events = eventManager;
            Connect();
        }

        public void SetExternalReplay(bool enabled)
        {
            if (externalReplay == enabled) return;
            externalReplay = enabled;
            if (enabled)
            {
                Disconnect();
                SetState("replay");
            }
            else
            {
                lastSequence = -1;
                initialised = false;
                Connect();
            }
        }

        public void ApplyBrowserSnapshot(string json)
        {
            try
            {
                var snapshot = JsonConvert.DeserializeObject<BrowserSnapshot>(json);
                if (snapshot == null) return;
                entities.ApplySnapshot(snapshot);
                trafficLights.Apply(snapshot.TrafficLights);
                conflicts.Apply(snapshot.Conflicts);
                events.Apply(snapshot.Events);
                lastSequence = snapshot.Sequence;
                ExperimentId = snapshot.ExperimentId;
                SimulationTimeS = snapshot.SimulationTimeS;
                Metrics = snapshot.Metrics;
                SetState("replay");
            }
            catch (Exception error)
            {
                Debug.LogError($"Replay snapshot rejected: {error}");
            }
        }

        public void OnWebSocketOpen(string _)
        {
            reconnectAttempt = 0;
            SetState("resyncing");
        }

        public void OnWebSocketMessage(string payload)
        {
            messages.Enqueue(payload);
        }

        public void OnWebSocketClosed(string reason)
        {
            if (externalReplay) return;
            SetState("offline");
            reconnectAt = Time.unscaledTime + Mathf.Min(5f, Mathf.Pow(2f, Mathf.Min(reconnectAttempt++, 3)));
        }

        private void Update()
        {
            while (messages.TryDequeue(out var message)) ApplyMessage(message);
            if (!externalReplay && ConnectionState == "offline" && Time.unscaledTime >= reconnectAt) Connect();
        }

        private void ApplyMessage(string json)
        {
            try
            {
                var envelope = JObject.Parse(json);
                if (envelope.Value<string>("protocolVersion") != "1.0") throw new InvalidOperationException("unsupported protocol version");
                var type = envelope.Value<string>("type");
                if (type == "init")
                {
                    var message = envelope.ToObject<DigitalTwinInit>() ?? throw new InvalidOperationException("empty init");
                    entities.ApplyInit(message);
                    trafficLights.Apply(message.TrafficLights);
                    conflicts.Apply(message.Conflicts);
                    events.Reset();
                    events.Apply(message.ActiveEvents);
                    lastSequence = message.Sequence;
                    ExperimentId = message.ExperimentId;
                    SimulationTimeS = message.SimulationTimeS;
                    Metrics = message.Metrics;
                    initialised = true;
                    SetState("online");
                }
                else if (type == "delta")
                {
                    var message = envelope.ToObject<DigitalTwinDelta>() ?? throw new InvalidOperationException("empty delta");
                    if (!initialised) throw new InvalidOperationException("delta before init");
                    if (message.Sequence <= lastSequence) return;
                    if (message.Sequence != lastSequence + 1) throw new InvalidOperationException($"sequence gap {lastSequence + 1}->{message.Sequence}");
                    if (ExperimentId != null && message.ExperimentId != ExperimentId) throw new InvalidOperationException("experiment changed without init");
                    entities.ApplyDelta(message);
                    trafficLights.Apply(message.TrafficLights);
                    conflicts.Apply(message.Conflicts);
                    events.Apply(message.Events);
                    lastSequence = message.Sequence;
                    ExperimentId = message.ExperimentId;
                    SimulationTimeS = message.SimulationTimeS;
                    Metrics = message.Metrics;
                }
                MessageApplied?.Invoke(envelope);
            }
            catch (Exception error)
            {
                Debug.LogError($"Digital-twin frame rejected: {error.Message}");
                initialised = false;
                lastSequence = -1;
                Disconnect();
                OnWebSocketClosed("protocol resync required");
            }
        }

        private void Connect()
        {
            if (externalReplay) return;
            Disconnect();
            SetState(reconnectAttempt == 0 ? "connecting" : "resyncing");
#if UNITY_WEBGL && !UNITY_EDITOR
            socketId = XionganWebSocketConnect(url, gameObject.name);
#else
            cancellation = new CancellationTokenSource();
            _ = ConnectEditor(cancellation.Token);
#endif
        }

#if !UNITY_WEBGL || UNITY_EDITOR
        private async Task ConnectEditor(CancellationToken token)
        {
            try
            {
                editorSocket = new ClientWebSocket();
                await editorSocket.ConnectAsync(new Uri(url), token);
                OnWebSocketOpen(string.Empty);
                var buffer = new byte[1024 * 1024];
                while (editorSocket.State == WebSocketState.Open && !token.IsCancellationRequested)
                {
                    var count = 0;
                    WebSocketReceiveResult result;
                    do
                    {
                        result = await editorSocket.ReceiveAsync(new ArraySegment<byte>(buffer, count, buffer.Length - count), token);
                        count += result.Count;
                        if (count == buffer.Length && !result.EndOfMessage) throw new InvalidOperationException("digital-twin frame exceeds 1 MiB");
                    } while (!result.EndOfMessage);
                    if (result.MessageType == WebSocketMessageType.Close) break;
                    messages.Enqueue(Encoding.UTF8.GetString(buffer, 0, count));
                }
            }
            catch (Exception error) when (error is not OperationCanceledException)
            {
                Debug.LogWarning($"Digital-twin socket: {error.Message}");
            }
            OnWebSocketClosed("editor socket closed");
        }
#endif

        private void Disconnect()
        {
#if UNITY_WEBGL && !UNITY_EDITOR
            if (socketId >= 0) XionganWebSocketClose(socketId);
            socketId = -1;
#else
            cancellation?.Cancel();
            cancellation?.Dispose();
            cancellation = null;
            editorSocket?.Dispose();
            editorSocket = null;
#endif
        }

        private void SetState(string state)
        {
            if (ConnectionState == state) return;
            ConnectionState = state;
            StateChanged?.Invoke(state);
        }

        private void OnDestroy()
        {
            Disconnect();
        }
    }
}
