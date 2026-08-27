import {useCallback, useEffect, useMemo, useRef, useState} from "react";
import type {DigitalTwinState, DigitalTwinStream} from "../3d/network/digitalTwinTypes";
import type {IntersectionNode} from "../types";
import {TwinIcon} from "./twin/TwinIcon";

type UnitySceneProps = {
  algorithmEvidenceVisible: boolean;
  digitalTwin: DigitalTwinStream;
  node: IntersectionNode | null;
  renderRate: number;
  runtimeId: string | null;
  scenarioId: string;
  sourceMode: "live" | "replay";
};

type UnityEvent = {
  type?: string;
  payload?: Record<string, unknown>;
};

type ViewMode = "hero" | "monitor" | "overview";

const views: Array<{mode: ViewMode; label: string; detail: string; image: string}> = [
  {mode: "hero", label: "主视角", detail: "B01 路口", image: "/assets/cameras/hero.png"},
  {mode: "monitor", label: "路口监控", detail: "信号与过街", image: "/assets/cameras/junction.png"},
  {mode: "overview", label: "全域鸟瞰", detail: "容东片区", image: "/assets/cameras/overview.png"},
];

const selectionKindLabels: Record<string, string> = {
  vehicle: "机动车",
  bicycle: "非机动车",
  pedestrian: "行人",
  lane: "车道",
  road: "道路",
  junction: "路口",
  traffic_light: "信号灯",
  device: "路侧设备",
  vehicle_cluster: "车辆聚合",
};

const showcaseJunctionId = "cluster_10739806290_13007678851_13007678852_9999059766";

export function resolveUnityFrameSource(scenarioId: string, search = window.location.search): string {
  const parameters = new URLSearchParams({scenarioId});
  if (new URLSearchParams(search).get("perf") === "1") parameters.set("perf", "1");
  return `/unity/index.html?${parameters.toString()}`;
}

export function shouldForwardUnitySnapshot(
  state: DigitalTwinState,
  scenarioId: string,
  runtimeId: string | null = state.experimentId,
): boolean {
  return Boolean(runtimeId)
    && state.initialized
    && state.scenarioId === scenarioId
    && state.experimentId === runtimeId;
}

export function UnityScene({
  algorithmEvidenceVisible,
  digitalTwin,
  node,
  renderRate,
  runtimeId,
  scenarioId,
  sourceMode,
}: UnitySceneProps) {
  const frameRef = useRef<HTMLIFrameElement | null>(null);
  const [unityReady, setUnityReady] = useState(false);
  const [sceneReady, setSceneReady] = useState(false);
  const [fatal, setFatal] = useState<string | null>(null);
  const [loading, setLoading] = useState("正在启动中");
  const [view, setView] = useState<ViewMode>("hero");
  const [selection, setSelection] = useState<{id: string; kind: string; provenance: string} | null>(null);
  const [locatorOpen, setLocatorOpen] = useState(false);
  const [locatorStatus, setLocatorStatus] = useState<string | null>(null);

  const unityFrameSource = useMemo(() => resolveUnityFrameSource(scenarioId), [scenarioId]);

  const cameraViews = useMemo(() => views.map((item) => {
    if (scenarioId === "xiongan_rongdong_20") return item;
    if (item.mode === "hero") return {...item, detail: node?.display_id ?? "核心路口"};
    if (item.mode === "overview") return {...item, detail: "当前场景"};
    return {...item, detail: "信号与车流"};
  }), [node?.display_id, scenarioId]);

  const post = useCallback((type: string, payload: Record<string, unknown>) => {
    frameRef.current?.contentWindow?.postMessage({type, payload}, window.location.origin);
  }, []);

  const cameraTarget = useMemo(() => {
    return node?.intersection_id ?? (scenarioId === "xiongan_rongdong_20" ? showcaseJunctionId : "");
  }, [node?.intersection_id, scenarioId]);

  useEffect(() => {
    setUnityReady(false);
    setSceneReady(false);
    setFatal(null);
    setLoading("正在启动中");
    setLocatorOpen(false);
    setLocatorStatus(null);
    setSelection(null);
  }, [scenarioId]);

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
        const loadedSceneId = String(message.payload?.sceneId ?? "");
        if (loadedSceneId !== scenarioId) {
          setFatal(`Unity 场景身份不一致：${loadedSceneId || "未知场景"}`);
          return;
        }
        setSceneReady(true);
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
      if (message.type === "vehicle-locator") {
        const found = Boolean(message.payload?.found);
        const count = Number(message.payload?.count ?? 0);
        const id = String(message.payload?.id ?? "");
        setLocatorStatus(found ? count > 1 ? `已定位 ${count} 辆车` : "已定位车辆" : "当前无在途车辆");
        if (found && id) {
          setSelection({id, kind: "vehicle", provenance: "SUMO/TraCI realtime entity"});
        }
      }
    };
    window.addEventListener("message", receive);
    return () => window.removeEventListener("message", receive);
  }, [scenarioId]);

  useEffect(() => {
    if (!unityReady || !sceneReady) return;
    // The browser owns the authoritative stream shared by the 2D and 3D views.
    post("xiongan-unity-command", {action: "source", mode: "replay"});
    post("xiongan-unity-command", {action: "weather", mode: "clear"});
  }, [post, sceneReady, sourceMode, unityReady]);

  useEffect(() => {
    if (!unityReady || !sceneReady) return;
    post("xiongan-unity-command", {action: "algorithm-visuals", visible: algorithmEvidenceVisible});
  }, [algorithmEvidenceVisible, post, sceneReady, unityReady]);

  useEffect(() => {
    if (!unityReady || !sceneReady) return;
    post("xiongan-unity-command", {action: "camera", mode: view, id: cameraTarget ?? ""});
  }, [cameraTarget, post, sceneReady, unityReady, view]);

  useEffect(() => {
    if (!unityReady || !sceneReady) return;
    post("xiongan-unity-command", {
      action: "vehicle-locators",
      visible: view === "overview" || locatorOpen,
    });
  }, [locatorOpen, post, sceneReady, unityReady, view]);

  useEffect(() => {
    if (!unityReady || !sceneReady) return;
    const state = digitalTwin.state;
    if (!shouldForwardUnitySnapshot(state, scenarioId, runtimeId)) return;
    post("xiongan-unity-snapshot", {
      sequence: state.sequence,
      experimentId: state.experimentId,
      simulationTimeS: state.simulationTimeS,
      tickHz: state.tickHz * renderRate,
      entities: {
        vehicles: [...state.vehicles.values()],
        bicycles: [...state.bicycles.values()],
        pedestrians: [...state.pedestrians.values()],
      },
      trafficLights: [...state.trafficLights.values()],
      conflicts: state.conflicts,
      events: state.events,
      metrics: state.metrics,
      intersectionMetrics: algorithmEvidenceVisible ? state.intersectionMetrics : [],
    });
  }, [algorithmEvidenceVisible, digitalTwin.state, post, renderRate, runtimeId, scenarioId, sceneReady, unityReady]);

  const changeView = (next: ViewMode) => {
    setView(next);
    post("xiongan-unity-command", {action: "camera", mode: next, id: cameraTarget});
  };

  const locateVehicle = (mode: "cluster" | "nearest" | "previous" | "next" | "follow" | "restore") => {
    if (mode !== "restore" && digitalTwin.state.vehicles.size === 0) {
      setLocatorStatus("当前无在途车辆");
      return;
    }
    if (mode === "restore") {
      setLocatorOpen(false);
      setLocatorStatus(null);
    } else {
      setLocatorOpen(true);
      setLocatorStatus("正在定位");
    }
    post("xiongan-unity-command", {
      action: "vehicle-locate",
      mode,
      id: selection?.kind === "vehicle" ? selection.id : "",
    });
  };

  const openVehicleLocator = () => {
    if (locatorOpen) {
      locateVehicle("restore");
      return;
    }
    locateVehicle("cluster");
  };

  return (
    <section className="intersection-stage unity-stage" aria-label="雄安交通 Unity 三维数字孪生">
      <iframe
        ref={frameRef}
        key={scenarioId}
        className="unity-frame"
        title="雄安交通 Unity 三维场景"
        src={unityFrameSource}
        allow="fullscreen; autoplay"
      />

      <div className="unity-vignette" aria-hidden="true" />
      <aside className="unity-camera-rail" aria-label="三维摄像机视角">
        {cameraViews.map((item) => (
          <button key={item.mode} type="button" className={view === item.mode ? "active" : ""} onClick={() => changeView(item.mode)} aria-pressed={view === item.mode}>
            <img alt="" src={item.image} />
            <i className={sceneReady ? "camera-online" : ""} aria-hidden="true" />
            <span><strong>{item.label}</strong><small>{item.detail}</small></span>
          </button>
        ))}
        <div className={`unity-vehicle-locator ${locatorOpen ? "open" : ""}`}>
          <button aria-expanded={locatorOpen} aria-label="定位车辆" className="locator-trigger" disabled={!sceneReady} onClick={openVehicleLocator} title="定位车辆" type="button"><TwinIcon name="focus" /><span><strong>定位车辆</strong><small>{digitalTwin.state.vehicles.size} 辆在途</small></span></button>
          {locatorOpen && <div className="locator-menu" role="menu">
            <button onClick={() => locateVehicle("cluster")} role="menuitem" type="button"><TwinIcon name="map" /><span>最密集区域</span></button>
            <button onClick={() => locateVehicle("nearest")} role="menuitem" type="button"><TwinIcon name="focus" /><span>最近车辆</span></button>
            <button onClick={() => locateVehicle("previous")} role="menuitem" type="button"><TwinIcon name="chevron" /><span>上一辆</span></button>
            <button onClick={() => locateVehicle("next")} role="menuitem" type="button"><TwinIcon name="chevron" /><span>下一辆</span></button>
            <button onClick={() => locateVehicle("follow")} role="menuitem" type="button"><TwinIcon name="car" /><span>跟随当前</span></button>
            <button onClick={() => locateVehicle("restore")} role="menuitem" type="button"><TwinIcon name="reset" /><span>返回视角</span></button>
            {locatorStatus && <output>{locatorStatus}</output>}
          </div>}
        </div>
      </aside>

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
          <span>{selectionKindLabels[selection.kind] ?? "交通对象"}</span>
          <strong>{selection.id}</strong>
          <small>{selection.provenance}</small>
        </aside>
      )}
    </section>
  );
}
