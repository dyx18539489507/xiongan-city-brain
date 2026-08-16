import {useEffect, useRef, useState, type PointerEvent as ReactPointerEvent} from "react";
import {TrafficCanvasRenderer, type RendererStats} from "../2d/TrafficCanvasRenderer";
import type {LayerVisibility, MapSelection, SceneLoadState} from "../2d/model";
import type {DigitalTwinStream} from "../3d/network/digitalTwinTypes";
import type {StaticSceneDocument} from "../3d/scene/types";
import type {RealtimeSnapshot} from "../types";
import {TwinIcon} from "./twin/TwinIcon";

type Props = {scene: StaticSceneDocument | null; loadState: SceneLoadState; stream: DigitalTwinStream; snapshot: RealtimeSnapshot; layers: LayerVisibility; selection: MapSelection | null; sourceMode: "live" | "replay"; websocketOnline: boolean; onSelectionChange: (selection: MapSelection | null) => void};

function formatBytes(value: number): string { return value > 1024 * 1024 ? `${(value / 1024 / 1024).toFixed(1)} MB` : `${Math.round(value / 1024)} KB`; }

function selectionLabel(selection: MapSelection | null): string {
  if (!selection) return "";
  return selection.kind === "junction" ? "路口" : selection.kind === "edge" ? "道路" : selection.kind === "event" ? "仿真事件" : selection.kind === "pedestrian" ? "行人" : selection.kind === "bicycle" ? "非机动车" : "车辆";
}

export function Traffic2DScene({scene, loadState, stream, snapshot, layers, selection, sourceMode, websocketOnline, onSelectionChange}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const staticCanvasRef = useRef<HTMLCanvasElement>(null);
  const rendererRef = useRef<TrafficCanvasRenderer | null>(null);
  const dragRef = useRef({active: false, moved: false, x: 0, y: 0});
  const lastHoverPickRef = useRef(0);
  const [hover, setHover] = useState<{selection: MapSelection; x: number; y: number} | null>(null);
  const [truthOpen, setTruthOpen] = useState(false);
  const [stats, setStats] = useState<RendererStats>({fps: 0, targetFps: 60, drawMs: 0, visibleEntities: 0, totalEntities: 0});

  useEffect(() => {
    const canvas = canvasRef.current;
    const staticCanvas = staticCanvasRef.current;
    if (!canvas || !staticCanvas) return;
    const renderer = new TrafficCanvasRenderer(canvas, staticCanvas, layers);
    rendererRef.current = renderer;
    const observer = new ResizeObserver(([entry]) => renderer.resize(entry.contentRect.width, entry.contentRect.height));
    const handleWheel = (event: WheelEvent) => { event.preventDefault(); const bounds = canvas.getBoundingClientRect(); renderer.zoomAt(event.clientX - bounds.left, event.clientY - bounds.top, event.deltaY < 0 ? 1.14 : .88); };
    observer.observe(canvas);
    canvas.addEventListener("wheel", handleWheel, {passive: false});
    let frame = 0;
    const animate = (now: number) => { renderer.render(now); frame = window.requestAnimationFrame(animate); };
    frame = window.requestAnimationFrame(animate);
    const statsTimer = window.setInterval(() => setStats(renderer.getStats()), 1000);
    return () => { observer.disconnect(); canvas.removeEventListener("wheel", handleWheel); window.cancelAnimationFrame(frame); window.clearInterval(statsTimer); renderer.destroy(); rendererRef.current = null; };
  }, []);

  useEffect(() => { if (scene) rendererRef.current?.setScene(scene); }, [scene]);
  useEffect(() => rendererRef.current?.setLayers(layers), [layers]);
  useEffect(() => rendererRef.current?.setSelection(selection), [selection]);
  useEffect(() => rendererRef.current?.setData(stream.state, snapshot, performance.now()), [snapshot, stream.state]);

  const pointerPosition = (event: ReactPointerEvent<HTMLCanvasElement>) => { const bounds = event.currentTarget.getBoundingClientRect(); return {x: event.clientX - bounds.left, y: event.clientY - bounds.top}; };
  const focusJunction = (id: string) => { if (!id) return; const next: MapSelection = {kind: "junction", id}; onSelectionChange(next); rendererRef.current?.focusJunction(id); };

  return <div className="traffic-2d-stage" data-draw-ms={stats.drawMs.toFixed(2)} data-fps={stats.fps.toFixed(1)} data-target-fps={stats.targetFps} data-visible-entities={stats.visibleEntities}>
    <canvas aria-hidden="true" className="traffic-2d-static-canvas" ref={staticCanvasRef} />
    <canvas
      aria-label="SUMO 实时二维交通数字孪生地图"
      className="traffic-2d-canvas"
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
          rendererRef.current?.pan(dx, dy);
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
        dragRef.current.active = false;
        event.currentTarget.releasePointerCapture(event.pointerId);
      }}
      ref={canvasRef}
    />

    <div className="map-view-controls" aria-label="地图视角">
      <button onClick={() => rendererRef.current?.fitScene()}><TwinIcon name="map" /><span>区域总览</span></button>
      <button disabled={!scene?.controlCorridors.length} onClick={() => rendererRef.current?.focusCorridor()}><TwinIcon name="route" /><span>核心走廊</span></button>
      <label><TwinIcon name="focus" /><select aria-label="选择重点路口" onChange={(event) => focusJunction(event.target.value)} value={selection?.kind === "junction" ? selection.id : ""}><option value="">重点路口</option>{scene?.junctions.filter((item) => item.controlled).map((item) => <option key={item.sumoJunctionId} value={item.sumoJunctionId}>{item.displayId ?? item.displayName ?? "受控路口"}</option>)}</select></label>
    </div>
    <button aria-expanded={truthOpen} className="map-truth-badge" onClick={() => setTruthOpen((value) => !value)}><span className={stream.state.initialized ? "truth-dot live" : "truth-dot"} /><div><strong>SUMO / TraCI {sourceMode === "replay" ? "REPLAY" : "LIVE"}</strong><small>{stream.state.initialized ? "仿真状态已同步" : "等待交通数据"}</small></div></button>
    {truthOpen && <div className="truth-popover"><b>仿真可信链路</b><span>仿真引擎<strong>SUMO</strong></span><span>状态来源<strong>TraCI</strong></span><span>前端呈现<strong>{sourceMode === "replay" ? "真实记录回放" : "实时增量同步"}</strong></span></div>}

    <div className="map-live-counters"><span><b>{stream.state.vehicles.size}</b>机动车</span><span><b>{stream.state.bicycles.size}</b>非机动车</span><span><b>{stream.state.pedestrians.size}</b>行人</span><span><b>{stream.state.trafficLights.size}</b>信号机</span></div>
    <div className="traffic-legend"><span><i className="neutral" />无车 / 无数据</span><span><i className="free" />畅通</span><span><i className="slow" />缓行</span><span><i className="congested" />拥堵</span><span><i className="severe" />严重拥堵</span></div>

    {!websocketOnline && sourceMode === "live" && <div className="connection-notice"><TwinIcon name="warning" /><span><strong>实时数据连接中断</strong><small>保留最后一帧，正在自动重连</small></span></div>}
    {hover && <div className="map-hover-tooltip" style={{left: hover.x + 14, top: hover.y + 14}}><span>{selectionLabel(hover.selection)}</span><strong>{hover.selection.kind === "junction" ? scene?.junctions.find((item) => item.sumoJunctionId === hover.selection.id)?.displayId ?? "受控路口" : selectionLabel(hover.selection)}</strong></div>}

    {loadState.status !== "ready" && <div className={`scene-loading ${loadState.status}`} role="status"><div className="loading-brand"><TwinIcon name="map" /></div><span>雄安交通数字孪生</span><strong>{loadState.status === "error" ? "数字场景加载失败" : "正在加载 20 路口数字场景"}</strong><div className="loading-steps"><i className="done" />路网几何<i className={loadState.loadedBytes > 0 ? "done" : ""} />城市空间<i className={loadState.loadedBytes > 0 ? "active" : ""} />实时数据</div><small>{loadState.message}</small>{loadState.status === "loading" && loadState.loadedBytes > 0 && <em>{formatBytes(loadState.loadedBytes)}{loadState.totalBytes ? ` / ${formatBytes(loadState.totalBytes)}` : ""}</em>}</div>}
    {loadState.status === "ready" && !stream.state.initialized && <div className="data-waiting-overlay"><span><TwinIcon name="activity" /></span><strong>等待第一帧交通数据</strong><small>静态路网已就绪，可启动 SUMO 实验或载入真实回放。</small></div>}
  </div>;
}
