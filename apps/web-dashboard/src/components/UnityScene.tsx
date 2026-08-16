import {useCallback, useEffect, useMemo, useRef, useState} from "react";
import type {DigitalTwinStream} from "../3d/network/digitalTwinTypes";
import type {IntersectionNode, IntersectionRealtime} from "../types";

type UnitySceneProps = {
  digitalTwin: DigitalTwinStream;
  node: IntersectionNode | null;
  nodes: IntersectionNode[];
  onNodeSelect: (id: string | null) => void;
  realtime: IntersectionRealtime | null;
  simulationTime?: number;
  status: string;
  websocketOnline: boolean;
  sourceMode: "live" | "replay";
};

type UnityEvent = {
  type?: string;
  payload?: Record<string, unknown>;
};

type ViewMode = "traffic" | "overview" | "corridor" | "junction" | "monitor" | "driver";

const views: Array<[ViewMode, string]> = [
  ["traffic", "交通"],
  ["overview", "全域"],
  ["corridor", "走廊"],
  ["junction", "路口"],
  ["monitor", "监控"],
  ["driver", "跟车"],
];

const unityCameraMode = (mode: ViewMode) => mode === "junction" ? "monitor" : mode;
const showcaseJunctionId = "cluster_11122023464_11122023574";

export function UnityScene({
  digitalTwin,
  node,
  nodes,
  onNodeSelect,
  realtime,
  simulationTime,
  status,
  websocketOnline,
  sourceMode,
}: UnitySceneProps) {
  const frameRef = useRef<HTMLIFrameElement | null>(null);
  const [unityReady, setUnityReady] = useState(false);
  const [sceneReady, setSceneReady] = useState(false);
  const [fatal, setFatal] = useState<string | null>(null);
  const [loading, setLoading] = useState("正在启动 Unity WebGL");
  const [view, setView] = useState<ViewMode>("traffic");
  const [selection, setSelection] = useState<{id: string; kind: string; provenance: string} | null>(null);
  const [sceneSummary, setSceneSummary] = useState<{junctions: number; lanes: number; buildings: number} | null>(null);
  const [appliedCommand, setAppliedCommand] = useState("");

  const post = useCallback((type: string, payload: Record<string, unknown>) => {
    frameRef.current?.contentWindow?.postMessage({type, payload}, window.location.origin);
  }, []);

  const cameraTarget = useMemo(() => {
    if (view === "driver") return digitalTwin.state.vehicles.keys().next().value as string | undefined;
    return node?.intersection_id ?? showcaseJunctionId;
  }, [digitalTwin.state.vehicles, node?.intersection_id, view]);

  useEffect(() => {
    const receive = (event: MessageEvent) => {
      if (event.origin !== window.location.origin || event.source !== frameRef.current?.contentWindow) return;
      if (event.data?.type === "xiongan-unity-ready") {
        setUnityReady(true);
        return;
      }
      if (event.data?.type === "xiongan-unity-fatal") {
        setFatal(String(event.data.message ?? "Unity WebGL 启动失败"));
        return;
      }
      if (event.data?.type !== "xiongan-unity-event") return;
      const message = event.data.detail as UnityEvent;
      if (message.type === "scene-ready") {
        setSceneReady(true);
        setSceneSummary({
          junctions: Number(message.payload?.junctions ?? 0),
          lanes: Number(message.payload?.lanes ?? 0),
          buildings: Number(message.payload?.buildings ?? 0),
        });
      }
      if (message.type === "command-applied") {
        setAppliedCommand(`${String(message.payload?.action ?? "").toUpperCase()} ${String(message.payload?.mode ?? "").toUpperCase()}`.trim());
      }
      if (message.type === "loading" && typeof message.payload?.message === "string") setLoading(message.payload.message);
      if (message.type === "fatal") setFatal(String(message.payload?.message ?? "场景加载失败"));
      if (message.type === "selection") {
        setSelection({
          id: String(message.payload?.id ?? ""),
          kind: String(message.payload?.kind ?? "entity"),
          provenance: String(message.payload?.provenance ?? "SUMO"),
        });
      }
    };
    window.addEventListener("message", receive);
    return () => window.removeEventListener("message", receive);
  }, []);

  useEffect(() => {
    if (!unityReady || !sceneReady) return;
    post("xiongan-unity-command", {action: "source", mode: sourceMode});
    post("xiongan-unity-command", {action: "weather", mode: "clear"});
  }, [post, sceneReady, sourceMode, unityReady]);

  useEffect(() => {
    if (!unityReady || !sceneReady) return;
    post("xiongan-unity-command", {action: "camera", mode: unityCameraMode(view), id: cameraTarget ?? ""});
  }, [cameraTarget, post, sceneReady, unityReady, view]);

  useEffect(() => {
    if (!unityReady || !sceneReady || sourceMode !== "replay") return;
    const state = digitalTwin.state;
    post("xiongan-unity-snapshot", {
      sequence: state.sequence,
      experimentId: state.experimentId,
      simulationTimeS: state.simulationTimeS,
      tickHz: state.tickHz,
      entities: {
        vehicles: [...state.vehicles.values()],
        bicycles: [...state.bicycles.values()],
        pedestrians: [...state.pedestrians.values()],
      },
      trafficLights: [...state.trafficLights.values()],
      conflicts: state.conflicts,
      events: state.events,
      metrics: state.metrics,
    });
  }, [digitalTwin.state, post, sceneReady, sourceMode, unityReady]);

  const changeView = (next: ViewMode) => {
    setView(next);
    const id = next === "driver"
      ? (digitalTwin.state.vehicles.keys().next().value as string | undefined)
      : node?.intersection_id ?? showcaseJunctionId;
    post("xiongan-unity-command", {action: "camera", mode: unityCameraMode(next), id: id ?? ""});
  };

  const timeLabel = Number.isFinite(simulationTime) ? `${Math.round(simulationTime ?? 0)} s` : "待机";
  const liveLabel = sourceMode === "replay" ? "回放真值" : websocketOnline ? "实时真值" : "等待数据";

  return (
    <section className="intersection-stage unity-stage" aria-label="雄安交通 Unity 三维数字孪生">
      <iframe
        ref={frameRef}
        className="unity-frame"
        title="雄安交通 Unity 三维场景"
        src="/unity/index.html"
        allow="fullscreen; autoplay"
      />

      <div className="unity-vignette" aria-hidden="true" />
      <div className="unity-title">
        <span>SUMO × UNITY DIGITAL TWIN</span>
        <h1>雄安新区车路云协同交通世界</h1>
        <p>{node ? `${node.display_id} · ${node.display_name}` : "容东 20 路口全域场景"}</p>
      </div>

      <div className={`unity-source ${sourceMode}`}>
        <i />
        <span>{liveLabel}</span>
        <strong>{timeLabel}</strong>
      </div>

      <div className="unity-controls unity-view-controls" aria-label="摄像机视角">
        <label className="unity-junction-select">
          <span>路口</span>
          <select
            aria-label="选择三维路口"
            onChange={(event) => onNodeSelect(event.target.value || null)}
            value={node?.intersection_id ?? ""}
          >
            <option value="">K08 主展示区</option>
            {nodes.map((item) => (
              <option key={item.intersection_id} value={item.intersection_id}>
                {item.display_id} · {item.display_name}
              </option>
            ))}
          </select>
        </label>
        {views.map(([key, label]) => (
          <button key={key} type="button" className={view === key ? "active" : ""} onClick={() => changeView(key)}>
            {label}
          </button>
        ))}
      </div>

      <div className="unity-readout">
        <div><span>仿真状态</span><strong>{status || "IDLE"}</strong></div>
        <div><span>信号相位</span><strong>{realtime?.phase_id ?? "—"}</strong></div>
        <div><span>排队车辆</span><strong>{realtime?.queue_vehicles ?? 0}</strong></div>
        <div><span>场景数据</span><strong>{digitalTwin.state.vehicles.size} 车辆</strong></div>
      </div>

      {sceneSummary && (
        <div className="unity-scene-ready" role="status">
          <strong>{sceneSummary.junctions} / 20</strong>
          <span>SUMO STATIC READY · {sceneSummary.lanes} LANES · {sceneSummary.buildings} BUILDINGS</span>
          {appliedCommand && <small>{appliedCommand}</small>}
        </div>
      )}

      {!sceneReady && (
        <div className={`unity-loader ${fatal ? "error" : ""}`} role="status">
          <span />
          <strong>{fatal ?? loading}</strong>
          <small>{fatal ? "请检查 Unity 构建产物与后端场景接口" : "道路、建筑、设施与信号机正在一次性构建"}</small>
        </div>
      )}

      {selection && (
        <aside className="unity-selection">
          <button type="button" aria-label="关闭对象信息" onClick={() => setSelection(null)}>×</button>
          <span>{selection.kind}</span>
          <strong>{selection.id}</strong>
          <small>{selection.provenance}</small>
        </aside>
      )}
    </section>
  );
}
