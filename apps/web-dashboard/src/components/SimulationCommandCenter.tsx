import {useEffect, useMemo, useState} from "react";
import {defaultLayerVisibility, type LayerKey, type MapSelection, type SimulationViewMode} from "../2d/model";
import {useStaticScene} from "../2d/useStaticScene";
import type {DigitalTwinStream} from "../3d/network/digitalTwinTypes";
import type {ReplayItem} from "../3d/replay/useDigitalTwinPlayback";
import type {Algorithm, IntersectionNode, IntersectionRealtime, RealtimeSnapshot, Scenario, TimelineEvent} from "../types";
import {EventDrawer, type SupportedEvent} from "./twin/EventDrawer";
import {RegionalStatusPanel, deriveOperationalStage, hasActiveDisturbance} from "./twin/RegionalStatusPanel";
import {TrendDock, type RealComparison} from "./twin/TrendDock";
import {TwinControlPanel} from "./twin/TwinControlPanel";
import {TwinIcon} from "./twin/TwinIcon";
import {Traffic2DScene} from "./Traffic2DScene";
import {UnityScene} from "./UnityScene";

type Props = {
  scenarios: Scenario[]; algorithms: Algorithm[]; nodes: IntersectionNode[]; scenarioId: string; scenarioProfile: string; algorithm: string; seed: number; durationS: number; experimentId: string | null; snapshot: RealtimeSnapshot; digitalTwin: DigitalTwinStream; sourceMode: "live" | "replay"; websocketOnline: boolean; commandBusy: boolean; selectedIntersectionId: string | null;
  history: RealtimeSnapshot[]; timelineEvents: TimelineEvent[]; comparison: RealComparison | null; replays: ReplayItem[]; selectedReplayId: string | null; replayLoaded: boolean; replayBusy: boolean; replayPlaying: boolean; replaySpeed: number; replayCurrentTimeS: number; replayDurationS: number; simulationRate: number | null;
  onScenarioChange: (value: string) => void; onProfileChange: (value: string) => void; onAlgorithmChange: (value: string) => void; onSeedChange: (value: number) => void; onSimulationRate: (value: number | null) => void; onDurationChange: (value: number) => void; onIntersectionSelect: (value: string | null) => void; onStart: () => void; onPause: () => void; onResume: () => void; onStop: () => void; onReset: () => void; onFault: (type: string, target: string, detail: string, parameters?: Record<string, number | string | boolean>, durationS?: number) => void; onClearFaults: () => void; onToggleReplay: () => void; onReplaySpeed: (value: number) => void; onSeekReplay: (value: number) => void; onLoadReplay: (id: string) => void; onGoLive: () => void;
};

function initialView(): SimulationViewMode { return new URLSearchParams(window.location.search).get("view") === "3d" ? "3d" : "2d"; }
function simulationClock(seconds = 0): string { const rounded = Math.max(0, Math.floor(seconds)); const hours = Math.floor(rounded / 3600).toString().padStart(2, "0"); const minutes = Math.floor((rounded % 3600) / 60).toString().padStart(2, "0"); const secs = (rounded % 60).toString().padStart(2, "0"); return `${hours}:${minutes}:${secs}`; }

export function SimulationCommandCenter(props: Props) {
  const [viewMode, setViewMode] = useState<SimulationViewMode>(initialView);
  const [layers, setLayers] = useState(defaultLayerVisibility);
  const [selection, setSelection] = useState<MapSelection | null>(null);
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(false);
  const [drawerEvent, setDrawerEvent] = useState<SupportedEvent | null>(null);
  const {scene, loadState} = useStaticScene(props.scenarioId);
  const currentScenario = props.scenarios.find((item) => item.scenario_id === props.scenarioId);
  const selectedNode = props.nodes.find((node) => node.intersection_id === props.selectedIntersectionId) ?? null;
  const selectedRealtime: IntersectionRealtime | null = props.snapshot.intersections?.find((item) => item.intersection_id === props.selectedIntersectionId) ?? null;
  const coreIds = useMemo(() => props.nodes.filter((node) => node.role === "core_corridor").map((node) => node.intersection_id), [props.nodes]);

  useEffect(() => { const url = new URL(window.location.href); url.searchParams.set("view", viewMode); window.history.replaceState(null, "", url); }, [viewMode]);
  useEffect(() => { if (!selection && props.selectedIntersectionId) setSelection({kind: "junction", id: props.selectedIntersectionId}); }, [props.selectedIntersectionId, selection]);

  const updateSelection = (next: MapSelection | null) => { setSelection(next); props.onIntersectionSelect(next?.kind === "junction" ? next.id : null); };
  const liveRunning = props.snapshot.status === "running";
  const livePaused = props.snapshot.status === "paused";
  const controlsDisabled = props.commandBusy || props.sourceMode === "replay";
  const stage = deriveOperationalStage(props.snapshot, props.digitalTwin.state.events);
  const activeEventCount = Math.max(
    props.snapshot.active_disturbances?.length ?? 0,
    hasActiveDisturbance(props.digitalTwin.state.events) ? 1 : 0,
  );
  const rate = props.sourceMode === "replay" ? props.replaySpeed : props.simulationRate;
  const simTime = props.snapshot.simulation_time_s ?? 0;

  return <section aria-label="雄安城市交通数字孪生驾驶舱" className={`twin-cockpit view-${viewMode} ${leftCollapsed ? "left-collapsed" : ""} ${rightCollapsed ? "right-collapsed" : ""}`}>
    <div className="twin-map-surface">{viewMode === "2d" ? <Traffic2DScene layers={layers} loadState={loadState} onSelectionChange={updateSelection} scene={scene} selection={selection} snapshot={props.snapshot} sourceMode={props.sourceMode} stream={props.digitalTwin} websocketOnline={props.websocketOnline} /> : <UnityScene digitalTwin={props.digitalTwin} node={selectedNode} nodes={props.nodes} onNodeSelect={props.onIntersectionSelect} realtime={selectedRealtime} simulationTime={props.snapshot.simulation_time_s} sourceMode={props.sourceMode} status={props.snapshot.status} websocketOnline={props.websocketOnline} />}</div>

    <header className="twin-header">
      <div className="brand-lockup"><span>XIONG'AN URBAN TRAFFIC DIGITAL TWIN</span><h1>雄安城市交通数字孪生</h1></div>
      <div className="header-context"><div><span>控制算法</span><strong>{props.algorithm}</strong></div><i /><div><span>随机种子</span><strong>{props.seed}</strong></div><i /><div><span>当前阶段</span><strong className="stage">{stage}</strong></div></div>
      <div className="header-actions">
        <button className="sumo-status" title="状态来自 SUMO / TraCI"><i className={props.digitalTwin.state.initialized ? "online" : ""} /><span>SUMO / TraCI</span><b>{props.sourceMode === "replay" ? "REPLAY" : "LIVE"}</b></button>
        <div className="header-clock"><span>仿真时间</span><strong>{simulationClock(simTime)}</strong></div>
        <div className="transport-group">
          <button aria-label={props.sourceMode === "replay" ? (props.replayPlaying ? "暂停回放" : "播放回放") : livePaused ? "继续仿真" : "启动仿真"} className="primary" disabled={props.commandBusy || (props.sourceMode === "live" && liveRunning) || (props.sourceMode === "live" && !currentScenario?.runnable)} onClick={props.sourceMode === "replay" ? props.onToggleReplay : livePaused ? props.onResume : props.onStart}><TwinIcon name={props.sourceMode === "replay" && props.replayPlaying ? "pause" : "play"} /></button>
          <button aria-label="暂停仿真" disabled={props.sourceMode === "replay" ? !props.replayPlaying : controlsDisabled || !props.experimentId || !liveRunning} onClick={props.sourceMode === "replay" ? props.onToggleReplay : props.onPause}><TwinIcon name="pause" /></button>
          <button aria-label="停止仿真" disabled={controlsDisabled || !props.experimentId} onClick={props.onStop}><TwinIcon name="stop" /></button>
          <button aria-label="重置仿真" disabled={controlsDisabled} onClick={props.onReset}><TwinIcon name="reset" /></button>
        </div>
        <div className="rate-group" aria-label="仿真倍速">{[1, 2, 4, 8].map((value) => <button className={rate === value ? "active" : ""} key={value} onClick={() => props.sourceMode === "replay" ? props.onReplaySpeed(value) : props.onSimulationRate(value)}>×{value}</button>)}{props.sourceMode === "live" && <button className={rate === null ? "active" : ""} onClick={() => props.onSimulationRate(null)}>MAX</button>}</div>
        <div className="view-mode-switch"><button className={viewMode === "2d" ? "active" : ""} onClick={() => setViewMode("2d")}>2D</button><button className={viewMode === "3d" ? "active" : ""} onClick={() => setViewMode("3d")}>3D</button></div>
      </div>
    </header>

    <TwinControlPanel activeEventCount={activeEventCount} algorithm={props.algorithm} algorithms={props.algorithms} collapsed={leftCollapsed} durationS={props.durationS} eventsDisabled={controlsDisabled || !props.experimentId} layers={layers} onAlgorithmChange={props.onAlgorithmChange} onClearEvents={props.onClearFaults} onCollapsed={() => setLeftCollapsed((value) => !value)} onDurationChange={props.onDurationChange} onEventOpen={setDrawerEvent} onLayerChange={(key: LayerKey) => setLayers((current) => ({...current, [key]: !current[key]}))} onProfileChange={props.onProfileChange} onSeedChange={props.onSeedChange} scenarioId={props.scenarioId} scenarioProfile={props.scenarioProfile} scenarios={props.scenarios} scene={scene} seed={props.seed} />
    <RegionalStatusPanel collapsed={rightCollapsed} comparison={props.comparison} nodes={props.nodes} onCollapsed={() => setRightCollapsed((value) => !value)} scene={scene} selection={selection} snapshot={props.snapshot} state={props.digitalTwin.state} />

    <div className="source-switcher"><TwinIcon name="timeline" /><select aria-label="实时或真实回放" disabled={props.replayBusy} onChange={(event) => event.target.value === "live" ? props.onGoLive() : props.onLoadReplay(event.target.value)} value={props.sourceMode === "live" ? "live" : props.selectedReplayId ?? ""}><option value="live">实时仿真</option>{props.replays.map((item) => <option key={item.experimentId} value={item.experimentId}>真实回放 · {item.algorithm ?? item.experimentId}</option>)}</select></div>
    <TrendDock comparison={props.comparison} coreIntersectionIds={coreIds} durationS={props.sourceMode === "replay" ? props.replayDurationS : props.durationS} events={props.timelineEvents} history={props.history} onSeek={props.onSeekReplay} replayLoaded={props.replayLoaded} simulationTimeS={props.sourceMode === "replay" ? props.replayCurrentTimeS : simTime} sourceMode={props.sourceMode} />
    <EventDrawer disabled={props.commandBusy} event={drawerEvent} onClose={() => setDrawerEvent(null)} onConfirm={(event, duration) => { props.onFault(event.type, event.target, event.label, event.parameters, duration); setDrawerEvent(null); }} />
  </section>;
}
