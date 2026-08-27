import {useEffect, useMemo, useRef, useState} from "react";
import {defaultLayerVisibility, type LayerKey, type MapSelection, type SimulationViewMode} from "../2d/model";
import {useStaticScene} from "../2d/useStaticScene";
import type {DigitalTwinStream} from "../3d/network/digitalTwinTypes";
import type {PairedDigitalTwinStream} from "../3d/network/comparisonDigitalTwinTypes";
import type {ReplayItem} from "../3d/replay/useDigitalTwinPlayback";
import {algorithmLabel} from "../algorithmLabels";
import {appendSimulationRateSample, calculateEffectiveSimulationRate, type SimulationRateSample} from "../simulationRate";
import type {Algorithm, IntersectionNode, IntersectionRealtime, RealtimeSnapshot, Scenario, TimelineEvent} from "../types";
import {EventDrawer, type SupportedEvent} from "./twin/EventDrawer";
import {LiveComparisonDock} from "./twin/LiveComparisonDock";
import {RegionalStatusPanel, hasActiveDisturbance} from "./twin/RegionalStatusPanel";
import type {RealComparison} from "./twin/TrendDock";
import type {ComparisonRole} from "./twin/AlgorithmComparisonDock";
import {TwinControlPanel} from "./twin/TwinControlPanel";
import {TwinIcon} from "./twin/TwinIcon";
import {PairedTraffic2DScene, Traffic2DScene} from "./Traffic2DScene";
import {UnityScene} from "./UnityScene";

export type TransportCommand = "start" | "pause" | "stop" | "reset";

type Props = {
  scenarios: Scenario[]; algorithms: Algorithm[]; nodes: IntersectionNode[]; scenarioId: string; scenarioProfile: string; algorithm: string; candidateAlgorithm: string; seed: number; durationS: number; experimentId: string | null; comparisonId: string | null; snapshot: RealtimeSnapshot; digitalTwin: DigitalTwinStream; pairedDigitalTwin: PairedDigitalTwinStream; sourceMode: "live" | "replay"; websocketOnline: boolean; commandBusy: boolean; activeTransportCommand: TransportCommand | null; startupStage: string | null; selectedIntersectionId: string | null;
  history: RealtimeSnapshot[]; comparisonHistory: RealtimeSnapshot[]; timelineEvents: TimelineEvent[]; comparison: RealComparison | null; replays: ReplayItem[]; selectedReplayId: string | null; replayLoaded: boolean; replayBusy: boolean; replayPlaying: boolean; replaySpeed: number; replayCurrentTimeS: number; replayDurationS: number; simulationRate: number | null;
  onScenarioChange: (value: string) => void; onProfileChange: (value: string) => void; onAlgorithmChange: (value: string) => void; onCandidateAlgorithmChange: (value: string) => void; onSeedChange: (value: number) => void; onSimulationRate: (value: number | null) => Promise<string | null>; onComparisonSimulationRate: (value: number | null) => Promise<string | null>; onDurationChange: (value: number) => void; onIntersectionSelect: (value: string | null) => void; onStart: () => void; onComparisonStart: () => void; onPause: () => void; onComparisonPause: () => void; onResume: () => void; onComparisonResume: () => void; onStop: () => void; onComparisonStop: () => void; onReset: () => void; onComparisonReset: () => void; onFault: (type: string, target: string, detail: string, parameters?: Record<string, number | string | boolean>, durationS?: number) => Promise<string | null>; onClearFaults: () => void; onToggleReplay: () => void; onReplaySpeed: (value: number) => void; onSeekReplay: (value: number) => void; onLoadReplay: (id: string) => void; onGoLive: () => void; onViewModeChange: (value: SimulationViewMode) => Promise<string | null>;
};

function initialView(): SimulationViewMode { return new URLSearchParams(window.location.search).get("view") === "2d" ? "2d" : "3d"; }
function initialRunMode(): "single" | "comparison" { return new URLSearchParams(window.location.search).get("run") === "single" ? "single" : "comparison"; }
function initialPanelCollapsed(): boolean { return window.innerWidth < 1100; }
function simulationClock(seconds = 0): string { const rounded = Math.max(0, Math.floor(seconds)); const hours = Math.floor(rounded / 3600).toString().padStart(2, "0"); const minutes = Math.floor((rounded % 3600) / 60).toString().padStart(2, "0"); const secs = (rounded % 60).toString().padStart(2, "0"); return `${hours}:${minutes}:${secs}`; }
export function liveStartBlocked(experimentId: string | null, status: string): boolean {
  return Boolean(experimentId) && !["completed", "failed", "stopped", "paused"].includes(status);
}
export function liveConfigurationLocked(experimentId: string | null, status: string): boolean {
  return Boolean(experimentId) && !["completed", "failed", "invalid", "stopped"].includes(status);
}
export function comparisonStartBlocked(pairId: string | null, status: string): boolean {
  return Boolean(pairId) && !["created", "configured", "completed", "failed", "invalid", "stopped", "paused"].includes(status);
}

export function startupPhaseLabel(stage: string | null): "启动中" | "等待中" {
  return stage?.startsWith("等待") ? "等待中" : "启动中";
}

export function pairedRuntimeOnline(connection: string, initialized: boolean): boolean {
  return connection === "online" && initialized;
}

export function replayOptionLabel(item: ReplayItem): string {
  const algorithm = algorithmLabel(item.algorithm);
  const profile = item.profile ?? "BASE";
  const seed = item.seed ?? "—";
  const createdAt = item.createdAt ? new Intl.DateTimeFormat("zh-CN", {month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false}).format(new Date(item.createdAt)).replaceAll("/", "-") : "时间未知";
  return `${algorithm} · ${profile} · seed ${seed} · ${createdAt} · ${item.experimentId.replace(/^exp-/, "").slice(0, 6)}`;
}

function pairedRoleSnapshot(props: Props, role: ComparisonRole): RealtimeSnapshot {
  const state = props.pairedDigitalTwin.state[role];
  const metrics = state.metrics as Partial<RealtimeSnapshot>;
  return {
    ...metrics,
    status: props.pairedDigitalTwin.state.status,
    experiment_id: state.experimentId ?? undefined,
    scenario_id: state.scenarioId ?? props.scenarioId,
    scenario_profile: String(props.pairedDigitalTwin.state.fairnessManifest.scenario_profile ?? props.scenarioProfile),
    algorithm: role === "baseline"
      ? props.pairedDigitalTwin.state.baselineAlgorithm || "fixed-time"
      : props.pairedDigitalTwin.state.candidateAlgorithm || props.candidateAlgorithm,
    seed: Number(props.pairedDigitalTwin.state.fairnessManifest.seed ?? props.seed),
    duration_s: Number(props.pairedDigitalTwin.state.fairnessManifest.duration_s ?? props.durationS),
    simulation_time_s: props.pairedDigitalTwin.state.simulationTimeS,
    intersections: state.intersectionMetrics.map((item) => ({
      ...item,
      lane_states: Array.isArray(item.approaches) ? item.approaches.map((approach) => {
        const lane = approach as Record<string, unknown>;
        return {
          ...lane,
          queue_vehicle_count: lane.queue_vehicle_count ?? lane.queue_vehicles ?? 0,
          queue_length_m: lane.queue_length_m ?? Number(lane.queue_vehicles ?? 0) * 7.5,
        };
      }) : [],
    })) as unknown as IntersectionRealtime[],
  };
}

export function SimulationCommandCenter(props: Props) {
  const [viewMode, setViewMode] = useState<SimulationViewMode>(initialView);
  const [runMode] = useState<"single" | "comparison">(initialRunMode);
  const [comparisonRole, setComparisonRole] = useState<ComparisonRole>("candidate");
  const [layers, setLayers] = useState(defaultLayerVisibility);
  const [selection, setSelection] = useState<MapSelection | null>(null);
  const [leftCollapsed, setLeftCollapsed] = useState(initialPanelCollapsed);
  const [rightCollapsed, setRightCollapsed] = useState(initialPanelCollapsed);
  const [drawerEvent, setDrawerEvent] = useState<SupportedEvent | null>(null);
  const [viewSwitching, setViewSwitching] = useState(false);
  const [ratePending, setRatePending] = useState(false);
  const [rateIssue, setRateIssue] = useState<string | null>(null);
  const [actualRate, setActualRate] = useState<number | null>(null);
  const rateSamplesRef = useRef<SimulationRateSample[]>([]);
  const rateRuntimeRef = useRef<string | null>(null);
  const selectedSceneRef = useRef<string | null>(null);
  const {scene, loadState, reload: reloadScene} = useStaticScene(props.scenarioId);
  const currentScenario = props.scenarios.find((item) => item.scenario_id === props.scenarioId);
  const effectiveNodes = useMemo<IntersectionNode[]>(() => {
    if (!scene || props.scenarioId === "xiongan_rongdong_20") return props.nodes;
    return scene.junctions.filter((junction) => junction.controlled).map((junction) => ({
      intersection_id: junction.sumoJunctionId,
      display_id: junction.displayId ?? junction.sumoJunctionId,
      display_name: junction.displayName ?? `路口 ${junction.sumoJunctionId}`,
      source_label: junction.displayId ?? junction.sumoJunctionId,
      lon: junction.lon ?? 0,
      lat: junction.lat ?? 0,
      role: junction.role === "core_corridor" ? "core_corridor" : "controlled",
      parameter_provenance: junction.provenance ?? "sumo_scene_document",
    }));
  }, [props.nodes, props.scenarioId, scene]);
  const selectedNode = effectiveNodes.find((node) => node.intersection_id === props.selectedIntersectionId) ?? null;
  const comparisonView = runMode === "comparison";
  const comparisonSnapshot = pairedRoleSnapshot(props, comparisonRole);
  const activeSnapshot = comparisonView ? comparisonSnapshot : props.snapshot;
  const activeHistory = comparisonView ? props.comparisonHistory : props.history;
  const activeDigitalTwin = comparisonView ? props.pairedDigitalTwin.state[comparisonRole] : props.digitalTwin.state;
  const activeStream: DigitalTwinStream = comparisonView
    ? {connection: props.pairedDigitalTwin.connection, issue: props.pairedDigitalTwin.issue, state: activeDigitalTwin}
    : props.digitalTwin;
  const activeSourceMode = comparisonView ? "live" : props.sourceMode;
  const activeRuntimeId = comparisonView ? props.comparisonId : props.experimentId;
  useEffect(() => { const url = new URL(window.location.href); url.searchParams.set("view", viewMode); window.history.replaceState(null, "", url); }, [viewMode]);
  useEffect(() => { if (!selection && props.selectedIntersectionId) setSelection({kind: "junction", id: props.selectedIntersectionId}); }, [props.selectedIntersectionId, selection]);
  useEffect(() => {
    if (!scene || selectedSceneRef.current === scene.metadata.sceneId) return;
    selectedSceneRef.current = scene.metadata.sceneId;
    const validCurrent = effectiveNodes.find((node) => node.intersection_id === props.selectedIntersectionId);
    const nextId = validCurrent?.intersection_id ?? effectiveNodes[0]?.intersection_id ?? null;
    setSelection(nextId ? {kind: "junction", id: nextId} : null);
    if (nextId !== props.selectedIntersectionId) props.onIntersectionSelect(nextId);
  }, [effectiveNodes, props.onIntersectionSelect, props.selectedIntersectionId, scene]);

  const updateSelection = (next: MapSelection | null) => { setSelection(next); props.onIntersectionSelect(next?.kind === "junction" ? next.id : null); };
  const liveRunning = activeSnapshot.status === "running";
  const livePaused = activeSnapshot.status === "paused";
  const startBlocked = comparisonView
    ? comparisonStartBlocked(activeRuntimeId, activeSnapshot.status)
    : liveStartBlocked(activeRuntimeId, activeSnapshot.status);
  const controlsDisabled = props.commandBusy || activeSourceMode === "replay";
  const configurationDisabled = activeSourceMode === "replay" || liveConfigurationLocked(activeRuntimeId, activeSnapshot.status);
  const activeEventCount = Math.max(
    activeSnapshot.active_disturbances?.length ?? 0,
    hasActiveDisturbance(activeDigitalTwin.events) ? 1 : 0,
  );
  const rate = activeSourceMode === "replay" ? props.replaySpeed : props.simulationRate;
  const simTime = activeSnapshot.simulation_time_s ?? 0;
  useEffect(() => {
    if (activeSourceMode !== "live" || activeSnapshot.status !== "running" || !activeRuntimeId) {
      rateSamplesRef.current = [];
      rateRuntimeRef.current = activeRuntimeId;
      setActualRate(null);
      return;
    }
    if (rateRuntimeRef.current !== activeRuntimeId) {
      rateSamplesRef.current = [];
      rateRuntimeRef.current = activeRuntimeId;
    }
    rateSamplesRef.current = appendSimulationRateSample(rateSamplesRef.current, {
      simulationTimeS: simTime,
      wallTimeMs: performance.now(),
    });
    setActualRate(calculateEffectiveSimulationRate(rateSamplesRef.current));
  }, [activeRuntimeId, activeSnapshot.status, activeSourceMode, simTime]);
  const startLoading = props.commandBusy && props.activeTransportCommand === "start";
  const pauseLoading = props.commandBusy && props.activeTransportCommand === "pause";
  const stopLoading = props.commandBusy && props.activeTransportCommand === "stop";
  const resetLoading = props.commandBusy && props.activeTransportCommand === "reset";
  const startupActive = Boolean(props.startupStage) && activeSourceMode === "live";
  const effectiveProfile = activeSnapshot.scenario_profile ?? props.scenarioProfile;
  const effectiveSeed = activeSnapshot.seed ?? props.seed;
  const runtimeId = activeSourceMode === "replay"
    ? activeSnapshot.experiment_id ?? props.digitalTwin.state.experimentId
    : activeRuntimeId;
  const runtimeTitle = `${activeSnapshot.scenario_id ?? props.scenarioId} · ${effectiveProfile} · seed ${effectiveSeed}${runtimeId ? ` · ${runtimeId}` : ""}`;
  const awaitingFirstFrame = comparisonView
    && Boolean(runtimeId)
    && !props.pairedDigitalTwin.state.initialized
    && ["starting", "running"].includes(activeSnapshot.status);
  const statusPending = startupActive || awaitingFirstFrame;
  const identityOnline = comparisonView
    ? pairedRuntimeOnline(props.pairedDigitalTwin.connection, props.pairedDigitalTwin.state.initialized)
    : props.digitalTwin.state.initialized && props.websocketOnline;
  const liveStart = comparisonView ? props.onComparisonStart : props.onStart;
  const livePause = comparisonView ? props.onComparisonPause : props.onPause;
  const liveResume = comparisonView ? props.onComparisonResume : props.onResume;
  const liveStop = comparisonView ? props.onComparisonStop : props.onStop;
  const liveReset = comparisonView ? props.onComparisonReset : props.onReset;
  const changeLiveRate = comparisonView ? props.onComparisonSimulationRate : props.onSimulationRate;
  const changeLiveAlgorithm = comparisonView ? props.onCandidateAlgorithmChange : props.onAlgorithmChange;
  const configuredAlgorithm = comparisonView ? props.candidateAlgorithm : props.algorithm;
  const runtimeModeLabel = comparisonView
    ? awaitingFirstFrame ? "等待中" : ({configured: "待启动", starting: "启动中", running: "运行中", paused: "已暂停", stopping: "停止中", stopped: "已停止", completed: "已完成", failed: "失败", invalid: "对照无效"}[activeSnapshot.status] ?? activeSnapshot.status)
    : activeSourceMode === "replay" ? "回放" : "实时";
  const startupLabel = startupPhaseLabel(props.startupStage);
  const visualRate = Math.max(.25, Math.min(24, actualRate ?? rate ?? 1));
  const actualRateLabel = actualRate === null ? "—" : `×${actualRate.toFixed(actualRate >= 10 ? 0 : 1)}`;

  const requestRate = async (value: number | null) => {
    if (activeSourceMode === "replay") {
      props.onReplaySpeed(value ?? 1);
      return;
    }
    setRatePending(true);
    setRateIssue(null);
    const issue = await changeLiveRate(value);
    setRateIssue(issue);
    setRatePending(false);
  };

  const changeViewMode = async (next: SimulationViewMode) => {
    if (next === viewMode || viewSwitching || props.commandBusy) return;
    setViewSwitching(true);
    setDrawerEvent(null);
    setSelection(null);
    const issue = await props.onViewModeChange(next);
    if (issue === null) setViewMode(next);
    setViewSwitching(false);
  };

  return <section aria-label="雄安城市交通数字孪生驾驶舱" className={`twin-cockpit view-${viewMode} ${leftCollapsed ? "left-collapsed" : ""} ${rightCollapsed ? "right-collapsed" : ""}`}>
    <div className="twin-map-surface">{viewMode === "2d" ? comparisonView ? <PairedTraffic2DScene configuredCandidateAlgorithm={props.candidateAlgorithm} layers={layers} loadState={loadState} onRetry={reloadScene} onSelectionChange={updateSelection} paired={props.pairedDigitalTwin} scene={scene} selection={selection} /> : <Traffic2DScene layers={layers} loadState={loadState} onRetry={reloadScene} onSelectionChange={updateSelection} scene={scene} selection={selection} snapshot={activeSnapshot} sourceMode={activeSourceMode} stream={activeStream} websocketOnline={props.websocketOnline} /> : <UnityScene algorithmEvidenceVisible={layers.algorithm} digitalTwin={activeStream} node={selectedNode} renderRate={visualRate} runtimeId={activeRuntimeId ? activeDigitalTwin.experimentId : null} scenarioId={props.scenarioId} sourceMode={comparisonView ? "replay" : props.sourceMode} />}</div>

    <header className="twin-header">
      <div className="brand-lockup"><h1>雄安城市交通数字孪生</h1></div>
      <div className="header-actions">
        <div aria-label={startupActive ? `启动进度：${startupLabel}` : "当前仿真运行身份"} className={`sumo-status ${runtimeId || startupActive ? "" : "idle"} ${statusPending ? "starting" : ""}`} title={startupActive ? props.startupStage ?? startupLabel : runtimeTitle}><i className={statusPending ? "pending" : identityOnline ? "online" : ""} />{startupActive ? <><span>双 SUMO / TraCI</span><b>{startupLabel}</b></> : runtimeId ? <><span>{identityOnline || activeSourceMode === "replay" ? (comparisonView ? "双 SUMO / TraCI" : "SUMO / TraCI") : awaitingFirstFrame ? "等待双路首帧" : "数据重连中"}</span><b>{runtimeModeLabel}</b></> : <b>待启动</b>}</div>
        <div aria-label={`仿真时间 ${simulationClock(simTime)}`} className="header-clock" title="仿真时间"><strong>{simulationClock(simTime)}</strong></div>
        <div className="transport-group">
          <button aria-busy={startLoading} aria-label={startLoading ? "正在启动中" : activeSourceMode === "replay" ? (props.replayPlaying ? "暂停回放" : "播放回放") : livePaused ? "继续仿真" : comparisonView ? "启动实时对照" : "启动仿真"} className="primary" disabled={props.commandBusy || (activeSourceMode === "live" && (liveRunning || startBlocked)) || (activeSourceMode === "live" && !currentScenario?.runnable)} onClick={() => { if (activeSourceMode === "replay") props.onToggleReplay(); else if (livePaused) liveResume(); else liveStart(); }}>{startLoading ? <span aria-hidden="true" className="transport-spinner" /> : <TwinIcon name={activeSourceMode === "replay" && props.replayPlaying ? "pause" : "play"} />}</button>
          <button aria-busy={pauseLoading} aria-label={pauseLoading ? "正在暂停中" : "暂停仿真"} disabled={activeSourceMode === "replay" ? !props.replayPlaying : controlsDisabled || !activeRuntimeId || !liveRunning} onClick={activeSourceMode === "replay" ? props.onToggleReplay : livePause}>{pauseLoading ? <span aria-hidden="true" className="transport-spinner" /> : <TwinIcon name="pause" />}</button>
          <button aria-busy={stopLoading} aria-label={stopLoading ? "正在停止中" : "停止仿真"} disabled={controlsDisabled || !activeRuntimeId || !["starting", "running", "paused", "stopping"].includes(activeSnapshot.status)} onClick={liveStop}>{stopLoading ? <span aria-hidden="true" className="transport-spinner" /> : <TwinIcon name="stop" />}</button>
          <button aria-busy={resetLoading} aria-label={resetLoading ? "正在重置中" : "重置仿真"} disabled={controlsDisabled} onClick={liveReset}>{resetLoading ? <span aria-hidden="true" className="transport-spinner" /> : <TwinIcon name="reset" />}</button>
        </div>
        <div className={`rate-control ${rateIssue ? "error" : ""}`} title={rateIssue ?? `目标 ${rate === null ? "最大" : `×${rate}`}，实际 ${actualRateLabel}`}><div className="rate-group" aria-busy={ratePending} aria-label="仿真倍速">{[1, 2, 4, 8].map((value) => <button className={rate === value ? "active" : ""} disabled={ratePending || props.commandBusy} key={value} onClick={() => void requestRate(value)}>×{value}</button>)}{activeSourceMode === "live" && <button className={rate === null ? "active" : ""} disabled={ratePending || props.commandBusy} onClick={() => void requestRate(null)}>最大</button>}</div><output aria-label={`实际仿真速度 ${actualRateLabel}`}><small>实际</small><strong>{actualRateLabel}</strong></output></div>
        <div className="view-mode-switch"><button aria-busy={viewSwitching && viewMode !== "2d"} className={viewMode === "2d" ? "active" : ""} disabled={viewSwitching || props.commandBusy} onClick={() => void changeViewMode("2d")}>2D</button><button aria-busy={viewSwitching && viewMode !== "3d"} className={viewMode === "3d" ? "active" : ""} disabled={viewSwitching || props.commandBusy} onClick={() => void changeViewMode("3d")}>3D</button></div>
      </div>
    </header>

    <TwinControlPanel activeEventCount={activeEventCount} algorithm={configuredAlgorithm} algorithmDisabled={configurationDisabled} algorithms={comparisonView ? props.algorithms.filter((item) => item.name !== "fixed-time") : props.algorithms} collapsed={leftCollapsed} comparisonMode={comparisonView} comparisonRole={comparisonRole} configurationDisabled={configurationDisabled} durationS={props.durationS} eventsDisabled={controlsDisabled || !activeRuntimeId || !["running", "paused"].includes(activeSnapshot.status)} history={activeHistory} layers={layers} nodes={effectiveNodes} onAlgorithmChange={changeLiveAlgorithm} onClearEvents={props.onClearFaults} onCollapsed={() => setLeftCollapsed((value) => !value)} onComparisonRoleChange={setComparisonRole} onDurationChange={props.onDurationChange} onEventOpen={setDrawerEvent} onIntersectionChange={props.onIntersectionSelect} onLayerChange={(key: LayerKey) => setLayers((current) => ({...current, [key]: !current[key]}))} onProfileChange={props.onProfileChange} onScenarioChange={props.onScenarioChange} onSeedChange={props.onSeedChange} pairedDigitalTwin={props.pairedDigitalTwin} scenarioId={props.scenarioId} scenarioProfile={props.scenarioProfile} scenarios={props.scenarios} scene={scene} seed={props.seed} selectedIntersectionId={props.selectedIntersectionId} snapshot={activeSnapshot} viewMode={viewMode} />
    <RegionalStatusPanel collapsed={rightCollapsed} comparison={comparisonView ? null : props.comparison} nodes={effectiveNodes} onCollapsed={() => setRightCollapsed((value) => !value)} scene={scene} selection={selection} snapshot={activeSnapshot} state={activeDigitalTwin} />

    {comparisonView && viewMode === "2d" && <LiveComparisonDock baselineAlgorithm={props.pairedDigitalTwin.state.baselineAlgorithm || "fixed-time"} candidateAlgorithm={props.pairedDigitalTwin.state.candidateAlgorithm || props.candidateAlgorithm} nodes={effectiveNodes} selectedIntersectionId={props.selectedIntersectionId} simulationTimeS={props.pairedDigitalTwin.state.simulationTimeS} summary={props.pairedDigitalTwin.state.comparison} />}
    <EventDrawer disabled={props.commandBusy} event={drawerEvent} onClose={() => setDrawerEvent(null)} onConfirm={(event, duration) => props.onFault(event.type, event.target, event.label, event.parameters, duration)} />
  </section>;
}
