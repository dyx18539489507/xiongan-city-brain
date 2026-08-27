import {useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent} from "react";
import type {Map as LeafletMap} from "leaflet";
import {TrafficCanvasRenderer, type RendererStats} from "../2d/TrafficCanvasRenderer";
import type {CameraPose} from "../2d/camera/MapCamera";
import type {LayerVisibility, MapSelection, SceneLoadState} from "../2d/model";
import {CoordinateService} from "../3d/core/CoordinateService";
import type {LiveComparisonSummary, PairedDigitalTwinStream} from "../3d/network/comparisonDigitalTwinTypes";
import type {DigitalTwinStream} from "../3d/network/digitalTwinTypes";
import type {StaticSceneDocument} from "../3d/scene/types";
import type {RealtimeSnapshot} from "../types";
import {algorithmLabel} from "../algorithmLabels";
import {wgs84ToGcj02} from "../chinaCoordinates";
import {TwinIcon} from "./twin/TwinIcon";

type CameraSyncSource = "baseline" | "candidate";
type CameraPoseListener = (pose: CameraPose) => void;

export type CameraSyncBus = {
  currentFor: (target: CameraSyncSource) => CameraPose | null;
  publish: (source: CameraSyncSource, pose: CameraPose) => void;
  subscribe: (target: CameraSyncSource, listener: CameraPoseListener) => () => void;
};

type Props = {scene: StaticSceneDocument | null; loadState: SceneLoadState; stream: DigitalTwinStream; snapshot: RealtimeSnapshot; layers: LayerVisibility; selection: MapSelection | null; sourceMode: "live" | "replay"; websocketOnline: boolean; onSelectionChange: (selection: MapSelection | null) => void; onRetry?: () => void; showLoadState?: boolean; comparison?: LiveComparisonSummary | null; cameraSyncBus?: CameraSyncBus; embedded?: boolean; mapRole?: CameraSyncSource};

function sameCameraPose(left: CameraPose, right: CameraPose): boolean {
  return Math.abs(left.centerX - right.centerX) < .001
    && Math.abs(left.centerY - right.centerY) < .001
    && Math.abs(left.scale - right.scale) < .0001;
}

export function createCameraSyncBus(): CameraSyncBus {
  const listeners = new Map<CameraSyncSource, Set<CameraPoseListener>>();
  let current: {source: CameraSyncSource; pose: CameraPose} | null = null;
  return {
    currentFor: (target) => current && current.source !== target ? {...current.pose} : null,
    publish: (source, pose) => {
      current = {source, pose: {...pose}};
      const target: CameraSyncSource = source === "baseline" ? "candidate" : "baseline";
      listeners.get(target)?.forEach((listener) => listener({...pose}));
    },
    subscribe: (target, listener) => {
      const targetListeners = listeners.get(target) ?? new Set<CameraPoseListener>();
      targetListeners.add(listener);
      listeners.set(target, targetListeners);
      return () => targetListeners.delete(listener);
    },
  };
}

function formatBytes(value: number): string { return value > 1024 * 1024 ? `${(value / 1024 / 1024).toFixed(1)} MB` : `${Math.round(value / 1024)} KB`; }

function selectionLabel(selection: MapSelection | null): string {
  if (!selection) return "";
  return selection.kind === "junction" ? "路口" : selection.kind === "edge" ? "道路" : selection.kind === "event" ? "仿真事件" : selection.kind === "pedestrian" ? "行人" : selection.kind === "bicycle" ? "非机动车" : "车辆";
}

function supportsGeographicMap(scene: StaticSceneDocument | null): scene is StaticSceneDocument {
  return Boolean(scene && scene.coordinateSystem.projection.trim() !== "!"
    && scene.coordinateSystem.utmZone >= 1 && scene.coordinateSystem.utmZone <= 60);
}

function leafletZoom(latitude: number, pixelsPerMeter: number): number {
  const groundResolutionAtZoomZero = 156543.03392 * Math.cos(latitude * Math.PI / 180);
  return Math.max(1, Math.min(20, Math.log2(groundResolutionAtZoomZero * Math.max(.0001, pixelsPerMeter))));
}

export function Traffic2DScene({scene, loadState, stream, snapshot, layers, selection, sourceMode, websocketOnline, onSelectionChange, onRetry, showLoadState = true, comparison = null, cameraSyncBus, embedded = false, mapRole}: Props) {
  const stageRef = useRef<HTMLDivElement>(null);
  const baseMapHostRef = useRef<HTMLDivElement>(null);
  const baseMapRef = useRef<LeafletMap | null>(null);
  const coordinateServiceRef = useRef<CoordinateService | null>(null);
  const sceneRef = useRef<StaticSceneDocument | null>(scene);
  const lastBaseMapPoseRef = useRef<{lat: number; lon: number; zoom: number; sceneId: string} | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const staticCanvasRef = useRef<HTMLCanvasElement>(null);
  const rendererRef = useRef<TrafficCanvasRenderer | null>(null);
  const dragRef = useRef({active: false, moved: false, x: 0, y: 0});
  const lastHoverPickRef = useRef(0);
  const lastCameraPoseRef = useRef<CameraPose | null>(null);
  const [hover, setHover] = useState<{selection: MapSelection; x: number; y: number} | null>(null);
  const [stats, setStats] = useState<RendererStats>({fps: 0, targetFps: 60, drawMs: 0, visibleEntities: 0, totalEntities: 0});
  const geographicMapVisible = supportsGeographicMap(scene) && layers.baseMap;

  sceneRef.current = scene;

  useEffect(() => {
    const host = baseMapHostRef.current;
    if (!host || baseMapRef.current) return;
    let disposed = false;
    let map: LeafletMap | null = null;
    let observer: ResizeObserver | null = null;
    void Promise.all([import("leaflet"), import("../mapTileLayer")]).then(([leaflet, tileLayer]) => {
      if (disposed) return;
      map = leaflet.map(host, {
        attributionControl: false,
        boxZoom: false,
        doubleClickZoom: false,
        dragging: false,
        keyboard: false,
        preferCanvas: true,
        scrollWheelZoom: false,
        touchZoom: false,
        zoomControl: false,
        zoomSnap: 0,
      }).setView([39.058, 115.916], 16);
      tileLayer.createRetryingChineseMapLayer().addTo(map);
      baseMapRef.current = map;
      observer = new ResizeObserver(() => map?.invalidateSize({pan: false, debounceMoveend: true}));
      observer.observe(host);
    });
    return () => {
      disposed = true;
      observer?.disconnect();
      map?.remove();
      baseMapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    const staticCanvas = staticCanvasRef.current;
    const stage = stageRef.current;
    if (!canvas || !staticCanvas || !stage) return;
    const renderer = new TrafficCanvasRenderer(canvas, staticCanvas, layers);
    rendererRef.current = renderer;
    const unsubscribeCameraSync = cameraSyncBus && mapRole
      ? cameraSyncBus.subscribe(mapRole, (pose) => {
          renderer.setCameraPose(pose);
          lastCameraPoseRef.current = renderer.getCameraPose();
        })
      : () => undefined;
    const resizeRenderer = (width: number, height: number) => {
      renderer.resize(width, height);
      baseMapRef.current?.invalidateSize({pan: false, debounceMoveend: true});
      lastCameraPoseRef.current = renderer.getCameraPose();
    };
    const observer = new ResizeObserver(([entry]) => resizeRenderer(entry.contentRect.width, entry.contentRect.height));
    const initialBounds = stage.getBoundingClientRect();
    resizeRenderer(initialBounds.width, initialBounds.height);
    const cockpit = stage.closest(".twin-cockpit");
    const overlayElements = cockpit
      ? Array.from(cockpit.querySelectorAll<HTMLElement>(".twin-header, .control-panel, .status-panel, .trend-dock"))
      : [];
    const updateViewportInsets = () => {
      if (embedded) {
        renderer.setViewportInsets({top: 52, right: 12, bottom: 44, left: 12});
        lastCameraPoseRef.current = renderer.getCameraPose();
        return;
      }
      const stageBounds = stage.getBoundingClientRect();
      const visibleRect = (selector: string) => {
        const element = cockpit?.querySelector<HTMLElement>(selector);
        if (!element) return null;
        const style = window.getComputedStyle(element);
        const bounds = element.getBoundingClientRect();
        return style.visibility === "hidden" || Number(style.opacity) === 0 || !bounds.width || !bounds.height ? null : bounds;
      };
      const header = visibleRect(".twin-header");
      const leftPanel = visibleRect(".control-panel");
      const rightPanel = visibleRect(".status-panel");
      const dock = visibleRect(".trend-dock");
      const gap = 14;
      renderer.setViewportInsets({
        top: header ? Math.max(0, header.bottom - stageBounds.top + gap) : gap,
        left: leftPanel ? Math.max(0, leftPanel.right - stageBounds.left + gap) : gap,
        right: rightPanel ? Math.max(0, stageBounds.right - rightPanel.left + gap) : gap,
        bottom: dock ? Math.max(0, stageBounds.bottom - dock.top + gap) : gap,
      });
      lastCameraPoseRef.current = renderer.getCameraPose();
    };
    const overlayObserver = new ResizeObserver(updateViewportInsets);
    overlayObserver.observe(stage);
    overlayElements.forEach((element) => overlayObserver.observe(element));
    const mutationObserver = new MutationObserver(updateViewportInsets);
    if (cockpit) mutationObserver.observe(cockpit, {attributes: true, subtree: true, attributeFilter: ["class"]});
    const handleWheel = (event: WheelEvent) => {
      event.preventDefault();
      const bounds = canvas.getBoundingClientRect();
      renderer.zoomAt(event.clientX - bounds.left, event.clientY - bounds.top, event.deltaY < 0 ? 1.14 : .88);
      const pose = renderer.getCameraPose();
      lastCameraPoseRef.current = pose;
      if (cameraSyncBus && mapRole) cameraSyncBus.publish(mapRole, pose);
    };
    observer.observe(stage);
    updateViewportInsets();
    canvas.addEventListener("wheel", handleWheel, {passive: false});
    window.addEventListener("resize", updateViewportInsets);
    let frame = 0;
    const animate = (now: number) => {
      renderer.render(now);
      const pose = renderer.getCameraPose();
      stage.dataset.cameraCenterX = String(pose.centerX);
      stage.dataset.cameraCenterY = String(pose.centerY);
      stage.dataset.cameraScale = String(pose.scale);
      const previous = lastCameraPoseRef.current;
      if (!previous || !sameCameraPose(previous, pose)) {
        lastCameraPoseRef.current = pose;
        if (cameraSyncBus && mapRole) cameraSyncBus.publish(mapRole, pose);
      }
      const currentScene = sceneRef.current;
      const coordinateService = coordinateServiceRef.current;
      const baseMap = baseMapRef.current;
      if (supportsGeographicMap(currentScene) && coordinateService && baseMap) {
        const mapPose = renderer.getGeographicMapPose();
        const wgs84 = coordinateService.sumoToLonLat(mapPose.centerX, mapPose.centerY);
        const gcj02 = wgs84ToGcj02(wgs84.lon, wgs84.lat);
        const zoom = leafletZoom(gcj02.lat, mapPose.scale);
        const previousMapPose = lastBaseMapPoseRef.current;
        if (!previousMapPose
          || previousMapPose.sceneId !== currentScene.metadata.sceneId
          || Math.abs(previousMapPose.lat - gcj02.lat) > 1e-8
          || Math.abs(previousMapPose.lon - gcj02.lon) > 1e-8
          || Math.abs(previousMapPose.zoom - zoom) > .002) {
          baseMap.setView([gcj02.lat, gcj02.lon], zoom, {animate: false});
          lastBaseMapPoseRef.current = {lat: gcj02.lat, lon: gcj02.lon, zoom, sceneId: currentScene.metadata.sceneId};
        }
      }
      frame = window.requestAnimationFrame(animate);
    };
    frame = window.requestAnimationFrame(animate);
    const statsTimer = window.setInterval(() => setStats(renderer.getStats()), 1000);
    return () => { unsubscribeCameraSync(); observer.disconnect(); overlayObserver.disconnect(); mutationObserver.disconnect(); canvas.removeEventListener("wheel", handleWheel); window.removeEventListener("resize", updateViewportInsets); window.cancelAnimationFrame(frame); window.clearInterval(statsTimer); renderer.destroy(); rendererRef.current = null; };
  }, [cameraSyncBus, embedded, mapRole]);

  useEffect(() => {
    const renderer = rendererRef.current;
    if (!scene || !renderer) return;
    coordinateServiceRef.current = supportsGeographicMap(scene) ? new CoordinateService(scene.coordinateSystem) : null;
    lastBaseMapPoseRef.current = null;
    renderer.setScene(scene);
    const synchronizedPose = mapRole ? cameraSyncBus?.currentFor(mapRole) : null;
    if (synchronizedPose) renderer.setCameraPose(synchronizedPose);
    lastCameraPoseRef.current = renderer.getCameraPose();
  }, [cameraSyncBus, mapRole, scene]);
  useEffect(() => {
    rendererRef.current?.setLayers(layers);
    rendererRef.current?.setGeographicBaseMapVisible(geographicMapVisible);
  }, [geographicMapVisible, layers]);
  useEffect(() => rendererRef.current?.setSelection(selection), [selection]);
  useEffect(() => rendererRef.current?.setData(stream.state, snapshot, performance.now()), [snapshot, stream.state]);
  useEffect(() => rendererRef.current?.setComparison(comparison), [comparison]);
  const pointerPosition = (event: ReactPointerEvent<HTMLCanvasElement>) => { const bounds = event.currentTarget.getBoundingClientRect(); return {x: event.clientX - bounds.left, y: event.clientY - bounds.top}; };
  const focusJunction = (id: string) => {
    if (!id) {
      onSelectionChange(null);
      rendererRef.current?.fitScene();
      return;
    }
    const next: MapSelection = {kind: "junction", id};
    onSelectionChange(next);
    rendererRef.current?.focusJunction(id);
  };

  const controlledJunctions = [...(scene?.junctions.filter((item) => item.controlled) ?? [])]
    .sort((left, right) => (left.displayId ?? left.displayName ?? left.sumoJunctionId).localeCompare(
      right.displayId ?? right.displayName ?? right.sumoJunctionId,
      "zh-CN",
      {numeric: true, sensitivity: "base"},
    ));

  return <div className={`traffic-2d-stage ${embedded ? "embedded" : ""} ${mapRole ? `map-role-${mapRole}` : ""}`} data-draw-ms={stats.drawMs.toFixed(2)} data-fps={stats.fps.toFixed(1)} data-map-role={mapRole} data-target-fps={stats.targetFps} data-visible-entities={stats.visibleEntities} ref={stageRef}>
    <div aria-hidden="true" className={`traffic-2d-base-map ${geographicMapVisible ? "visible" : ""}`} ref={baseMapHostRef} />
    <canvas aria-hidden="true" className="traffic-2d-static-canvas" ref={staticCanvasRef} />
    <canvas
      aria-label="SUMO 实时二维交通数字孪生地图"
      className="traffic-2d-canvas"
      onContextMenu={(event) => event.preventDefault()}
      onDoubleClick={() => rendererRef.current?.fitScene()}
      onPointerDown={(event) => {
        const point = pointerPosition(event);
        dragRef.current = {active: true, moved: false, ...point};
        event.currentTarget.setPointerCapture(event.pointerId);
      }}
      onPointerLeave={() => {
        rendererRef.current?.setHover(null);
        setHover(null);
      }}
      onPointerMove={(event) => {
        const point = pointerPosition(event);
        const drag = dragRef.current;
        if (drag.active) {
          const dx = point.x - drag.x;
          const dy = point.y - drag.y;
          if (Math.hypot(dx, dy) > 1) drag.moved = true;
          const renderer = rendererRef.current;
          renderer?.pan(dx, dy);
          if (renderer && cameraSyncBus && mapRole) {
            const pose = renderer.getCameraPose();
            lastCameraPoseRef.current = pose;
            cameraSyncBus.publish(mapRole, pose);
          }
          drag.x = point.x;
          drag.y = point.y;
          setHover(null);
          return;
        }
        const now = performance.now();
        if (now - lastHoverPickRef.current < 50) return;
        lastHoverPickRef.current = now;
        const picked = rendererRef.current?.pick(point.x, point.y) ?? null;
        rendererRef.current?.setHover(picked);
        setHover((current) => current && current.selection.kind === picked?.kind && current.selection.id === picked?.id
          ? current
          : picked ? {selection: picked, x: point.x, y: point.y} : null);
        event.currentTarget.style.cursor = picked ? "pointer" : "grab";
      }}
      onPointerUp={(event) => {
        const point = pointerPosition(event);
        if (!dragRef.current.moved) onSelectionChange(rendererRef.current?.pick(point.x, point.y) ?? null);
        const renderer = rendererRef.current;
        if (dragRef.current.moved && renderer && cameraSyncBus && mapRole) {
          const pose = renderer.getCameraPose();
          lastCameraPoseRef.current = pose;
          cameraSyncBus.publish(mapRole, pose);
        }
        dragRef.current.active = false;
        event.currentTarget.releasePointerCapture(event.pointerId);
      }}
      ref={canvasRef}
    />

    <div className="map-view-controls" aria-label="地图视角">
      <button onClick={() => rendererRef.current?.fitScene()}><TwinIcon name="map" /><span>区域总览</span></button>
      <button disabled={!scene?.controlCorridors.length} onClick={() => rendererRef.current?.focusCorridor()}><TwinIcon name="route" /><span>核心走廊</span></button>
      <label><TwinIcon name="focus" /><select aria-label="选择重点路口" onChange={(event) => focusJunction(event.target.value)} value={selection?.kind === "junction" ? selection.id : ""}><option value="">重点路口</option>{controlledJunctions.map((item) => <option key={item.sumoJunctionId} value={item.sumoJunctionId}>{item.displayId ?? item.displayName ?? "受控路口"}</option>)}</select></label>
    </div>
    <div className="map-live-counters"><span><b>{stream.state.vehicles.size}</b>机动车</span><span><b>{stream.state.bicycles.size}</b>非机动车</span><span><b>{stream.state.pedestrians.size}</b>行人</span><span><b>{stream.state.trafficLights.size}</b>信号机</span></div>
    <div className="traffic-legend"><span><i className="neutral" />无车 / 无数据</span><span><i className="free" />畅通</span><span><i className="slow" />缓行</span><span><i className="congested" />拥堵</span><span><i className="severe" />严重拥堵</span></div>

    {!websocketOnline && sourceMode === "live" && <div className="connection-notice"><TwinIcon name="warning" /><span><strong>实时数据连接中断</strong><small>保留最后一帧，正在自动重连</small></span></div>}
    {hover && <div className="map-hover-tooltip" style={{left: hover.x + 14, top: hover.y + 14}}><span>{selectionLabel(hover.selection)}</span><strong>{hover.selection.kind === "junction" ? scene?.junctions.find((item) => item.sumoJunctionId === hover.selection.id)?.displayId ?? "受控路口" : selectionLabel(hover.selection)}</strong></div>}

    {showLoadState && loadState.status !== "ready" && <div aria-live="polite" className={`scene-loading ${loadState.status}`} role="status"><div className="loading-brand"><TwinIcon name={loadState.status === "error" ? "warning" : "map"} /></div><span>雄安交通数字孪生</span><strong>{loadState.status === "error" ? "数字场景暂时无法加载" : "正在加载当前数字场景"}</strong>{loadState.status === "loading" && <i aria-hidden="true" className="scene-loading-spinner" />}<div className="loading-steps"><i className={loadState.status === "error" ? "" : "done"} />路网几何<i className={loadState.loadedBytes > 0 ? "done" : ""} />城市空间<i className={loadState.loadedBytes > 0 ? "active" : ""} />实时数据</div><small>{loadState.message}</small>{loadState.status === "loading" && loadState.loadedBytes > 0 && <em>{formatBytes(loadState.loadedBytes)}{loadState.totalBytes ? ` / ${formatBytes(loadState.totalBytes)}` : ""}</em>}{loadState.status === "error" && onRetry && <button className="scene-retry" onClick={onRetry}><TwinIcon name="reset" />重新加载路网</button>}</div>}
    {loadState.status === "ready" && !stream.state.initialized && <div className="data-waiting-overlay"><span><TwinIcon name="activity" /></span><strong>等待第一帧交通数据</strong><small>{embedded ? "静态路网已就绪，可启动同条件双 SUMO 实时对照。" : "静态路网已就绪，可启动 SUMO 实验或载入真实回放。"}</small></div>}
  </div>;
}

function snapshotFromPairedState(
  paired: PairedDigitalTwinStream,
  role: "baseline" | "candidate",
): {stream: DigitalTwinStream; snapshot: RealtimeSnapshot} {
  const state = paired.state[role];
  const metrics = state.metrics as Partial<RealtimeSnapshot>;
  const intersections = state.intersectionMetrics.map((item) => ({
    ...item,
    lane_states: Array.isArray(item.approaches) ? item.approaches : [],
  })) as unknown as NonNullable<RealtimeSnapshot["intersections"]>;
  return {
    stream: {
      connection: paired.connection,
      issue: paired.issue,
      state: {...state, initialized: paired.state.initialized && state.initialized},
    },
    snapshot: {
      ...metrics,
      status: paired.state.status,
      experiment_id: state.experimentId ?? undefined,
      scenario_id: state.scenarioId ?? undefined,
      algorithm: role === "baseline" ? paired.state.baselineAlgorithm : paired.state.candidateAlgorithm,
      simulation_time_s: paired.state.simulationTimeS,
      intersections,
    },
  };
}

type PairedProps = {
  scene: StaticSceneDocument | null;
  loadState: SceneLoadState;
  paired: PairedDigitalTwinStream;
  layers: LayerVisibility;
  selection: MapSelection | null;
  onSelectionChange: (selection: MapSelection | null) => void;
  configuredCandidateAlgorithm: string;
  onRetry?: () => void;
};

export function PairedTraffic2DScene({scene, loadState, paired, layers, selection, onSelectionChange, configuredCandidateAlgorithm, onRetry}: PairedProps) {
  const cameraSyncBus = useMemo(createCameraSyncBus, []);
  const baseline = snapshotFromPairedState(paired, "baseline");
  const candidate = snapshotFromPairedState(paired, "candidate");

  return <div className="paired-2d-scene">
    <div className="paired-2d-grid">
      <section className="paired-map-pane baseline-pane" aria-label="基准算法实时地图">
        <header><span>基准</span><strong>{algorithmLabel(paired.state.baselineAlgorithm || "fixed-time")}</strong><small>独立 SUMO · {baseline.stream.state.vehicles.size} 辆在途</small></header>
        <Traffic2DScene cameraSyncBus={cameraSyncBus} embedded layers={layers} loadState={loadState} mapRole="baseline" onSelectionChange={onSelectionChange} scene={scene} selection={selection} showLoadState={false} snapshot={baseline.snapshot} sourceMode="live" stream={baseline.stream} websocketOnline={paired.connection === "online"} />
      </section>
      <section className="paired-map-pane candidate-pane" aria-label="候选算法实时地图与改善差值">
        <header><span>候选</span><strong>{algorithmLabel(paired.state.candidateAlgorithm || configuredCandidateAlgorithm)}</strong><small>独立 SUMO · {candidate.stream.state.vehicles.size} 辆在途</small></header>
        <Traffic2DScene cameraSyncBus={cameraSyncBus} comparison={paired.state.comparison} embedded layers={layers} loadState={loadState} mapRole="candidate" onSelectionChange={onSelectionChange} scene={scene} selection={selection} showLoadState={false} snapshot={candidate.snapshot} sourceMode="live" stream={candidate.stream} websocketOnline={paired.connection === "online"} />
      </section>
      {loadState.status !== "ready" && <div aria-live="polite" className={`paired-scene-state ${loadState.status}`} role={loadState.status === "error" ? "alert" : "status"}><div className="loading-brand"><TwinIcon name={loadState.status === "error" ? "warning" : "map"} /></div>{loadState.status === "error" && <strong>双路数字场景暂时无法加载</strong>}{loadState.status === "loading" && <i aria-hidden="true" className="scene-loading-spinner" />}<span>{loadState.message}</span>{loadState.status === "loading" && loadState.loadedBytes > 0 && <small>{formatBytes(loadState.loadedBytes)}{loadState.totalBytes ? ` / ${formatBytes(loadState.totalBytes)}` : ""}</small>}{loadState.status === "error" && onRetry && <button className="scene-retry" onClick={onRetry}><TwinIcon name="reset" />重新加载路网</button>}</div>}
    </div>
    <div className="comparison-map-legend" aria-label="改善差值图例"><span className="improved">↓ 排队减少</span><span className="stable">≈ 基本持平</span><span className="worse">↑ 排队增加</span><small>右图进口道与路口相对左图，60 秒滚动窗口</small></div>
  </div>;
}
