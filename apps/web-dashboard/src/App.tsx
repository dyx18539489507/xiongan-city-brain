import {lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState} from "react";
import {
  clearFaults,
  clearLiveComparisonFaults,
  createAndStartLiveComparison,
  createAndStartExperiment,
  describeRequestError,
  injectFault,
  injectLiveComparisonFault,
  lifecycle,
  liveComparisonLifecycle,
  loadExperimentState,
  loadInventory,
  setSimulationRate,
  setLiveComparisonRate,
} from "./api";
import {algorithmLabel} from "./algorithmLabels";
import {SimulationCommandCenter, startupPhaseLabel, type TransportCommand} from "./components/SimulationCommandCenter";
import {PlatformWorkspaceNav, type PlatformWorkspace} from "./components/PlatformWorkspaceNav";
import {ScenarioFactoryWorkspace} from "./components/ScenarioFactoryWorkspace";
import {TwinIcon} from "./components/twin/TwinIcon";
import {AlgorithmComparisonChart} from "./components/AlgorithmComparisonChart";
import {Timeline} from "./components/Timeline";
import {TrendChart} from "./components/TrendChart";
import {useDigitalTwinPlayback} from "./3d/replay/useDigitalTwinPlayback";
import {usePairedDigitalTwinStream} from "./3d/network/ComparisonDigitalTwinSocket";
import {selectOperationalTimelineEvents} from "./2d/timeline";
import {resolveScenarioRuntimeParameters} from "./scenarioRuntime";
import {isActiveRealtimeSnapshot} from "./realtimeSnapshot";
import {canReuseExperiment} from "./experimentReuse";
import type {
  Algorithm,
  IntersectionNode,
  IntersectionRealtime,
  RealtimeSnapshot,
  RuntimeEvent,
  Scenario,
  TimelineEvent,
  TopologyEdge,
} from "./types";

const dash = "—";
const minimumCommandFeedbackMs = 320;
const pairedFirstFrameTimeoutMs = 120_000;
const terminalRuntimeStatuses = new Set(["completed", "failed", "invalid", "stopped"]);

async function loadLiveComparisonState(pairId: string): Promise<{status: string}> {
  const response = await fetch(`/api/v1/live-comparisons/${pairId}`, {cache: "no-store"});
  if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
  return response.json() as Promise<{status: string}>;
}

async function waitForRuntimeTerminal(
  runtimeId: string,
  loadState: (id: string) => Promise<{status: string}>,
  timeoutMs = 20_000,
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const state = await loadState(runtimeId);
    if (terminalRuntimeStatuses.has(state.status)) return;
    await new Promise((resolve) => window.setTimeout(resolve, 160));
  }
  throw new Error(`等待运行实例 ${runtimeId} 停止超时`);
}
const AlgorithmEvaluationWorkspace = lazy(() =>
  import("./components/AlgorithmEvaluationWorkspace").then((module) => ({
    default: module.AlgorithmEvaluationWorkspace,
  })),
);

function formatMetric(value: number | null | undefined, digits = 1): string {
  return value === undefined || value === null ? dash : value.toFixed(digits);
}

function classifyEvent(event: RuntimeEvent): TimelineEvent {
  const name = event.event.toUpperCase();
  const type: TimelineEvent["type"] =
    name.includes("RECOVER") || name.includes("COORDINATED")
      ? "recovery"
      : name.includes("FAULT") || name.includes("OFFLINE") || name.includes("LOSS")
        ? "fault"
        : name.includes("SAFETY") || name.includes("REJECT") || name.includes("MODIFIED")
          ? "safety"
          : name.includes("STRATEGY")
            ? "strategy"
            : name.includes("ACTION") || name.includes("FEEDBACK")
              ? "action"
              : name.includes("ROADWORK") ||
                  name.includes("INCIDENT") ||
                  name.includes("DISTURBANCE") ||
                  name.includes("DISPERSAL") ||
                  name.includes("EMERGENCY")
                ? "disturbance"
                : "state";
  const titleByType: Record<TimelineEvent["type"], string> = {
    state: "运行状态",
    strategy: "云端策略",
    action: "边缘执行",
    safety: "安全内核",
    disturbance: "场景扰动",
    fault: "通信故障",
    recovery: "协同恢复",
  };
  return {
    id: `${event.simulation_time}-${event.event}-${event.detail ?? ""}`,
    simulationTime: event.simulation_time,
    type,
    title: titleByType[type],
    detail: `${event.event}${event.detail ? ` · ${event.detail}` : ""}`,
  };
}

export function App() {
  const playback = useDigitalTwinPlayback();
  const pairedDigitalTwin = usePairedDigitalTwinStream();
  const digitalTwin = playback.stream;
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [algorithms, setAlgorithms] = useState<Algorithm[]>([]);
  const [nodes, setNodes] = useState<IntersectionNode[]>([]);
  const [topologyEdges, setTopologyEdges] = useState<TopologyEdge[]>([]);
  const [workspace, setWorkspace] = useState<PlatformWorkspace>(() => {
    const value = new URLSearchParams(window.location.search).get("workspace");
    return value === "algorithms" || value === "scenarios" ? value : "simulation";
  });
  const [scenarioId, setScenarioId] = useState("xiongan_rongdong_20");
  const [scenarioProfile, setScenarioProfile] = useState("BASE");
  const [algorithm, setAlgorithm] = useState("fixed-time");
  const [candidateAlgorithm, setCandidateAlgorithm] = useState("coordinated-max-pressure");
  const [seed, setSeed] = useState(42);
  const [durationS, setDurationS] = useState(1800);
  const [simulationRate, setSimulationRateState] = useState<number | null>(1);
  const [experimentId, setExperimentId] = useState<string | null>(null);
  const [comparisonId, setComparisonId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<RealtimeSnapshot>({
    status: "idle",
    message: "尚未运行",
  });
  const [history, setHistory] = useState<RealtimeSnapshot[]>([]);
  const [comparisonHistory, setComparisonHistory] = useState<RealtimeSnapshot[]>([]);
  const [localEvents, setLocalEvents] = useState<TimelineEvent[]>([]);
  const [connection, setConnection] = useState<
    "connecting" | "online" | "offline"
  >("connecting");
  const [commandBusy, setCommandBusy] = useState(false);
  const [commandLabel, setCommandLabel] = useState<string | null>(null);
  const [activeTransportCommand, setActiveTransportCommand] = useState<TransportCommand | null>(null);
  const [startupStage, setStartupStage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [replayChoice, setReplayChoice] = useState("");
  const [replayHistory, setReplayHistory] = useState<RealtimeSnapshot[]>([]);
  const [baselineChoice, setBaselineChoice] = useState("");
  const [candidateChoice, setCandidateChoice] = useState("");
  const previousRef = useRef<RealtimeSnapshot | null>(null);
  const replayExperimentRef = useRef<string | null>(null);
  const activeExperimentRef = useRef<string | null>(null);
  const pendingStartRef = useRef(false);
  const simulationRateRef = useRef<number | null>(1);
  const pairedDigitalTwinRef = useRef(pairedDigitalTwin);
  pairedDigitalTwinRef.current = pairedDigitalTwin;

  const refreshInventory = useCallback(async () => {
    const inventory = await loadInventory();
    setScenarios(inventory.scenarios);
    setAlgorithms(inventory.algorithms);
    setNodes(inventory.intersections);
    setTopologyEdges(inventory.topologyEdges);
    setSelectedId((current) => current ?? inventory.intersections.find((item) => item.display_id === "B01")
      ?.intersection_id ?? inventory.intersections[0]?.intersection_id ?? null);
    return inventory;
  }, []);

  useEffect(() => {
    refreshInventory().catch((reason: unknown) => setError(describeRequestError(reason)));
  }, [refreshInventory]);

  const changeWorkspace = useCallback((next: PlatformWorkspace) => {
    setError(null);
    setWorkspace(next);
    const url = new URL(window.location.href);
    if (next === "simulation") url.searchParams.delete("workspace");
    else url.searchParams.set("workspace", next);
    window.history.replaceState(null, "", url);
  }, []);

  useEffect(() => {
    const pair = pairedDigitalTwin.state;
    if (pairedDigitalTwin.connection === "online" && !pair.pairId) {
      setComparisonId(null);
      return;
    }
    if (!pair.pairId || !pair.initialized) return;
    setComparisonId(pair.pairId);
    if (pair.candidateAlgorithm) setCandidateAlgorithm(pair.candidateAlgorithm);
    const manifest = pair.fairnessManifest;
    if (typeof manifest.scenario_id === "string") setScenarioId(manifest.scenario_id);
    if (typeof manifest.scenario_profile === "string") setScenarioProfile(manifest.scenario_profile);
    if (typeof manifest.seed === "number") setSeed(manifest.seed);
    if (typeof manifest.duration_s === "number") setDurationS(manifest.duration_s);
    const candidate = pair.candidate;
    const metrics = candidate.metrics as Partial<RealtimeSnapshot>;
    const next: RealtimeSnapshot = {
      ...metrics,
      status: pair.status,
      experiment_id: candidate.experimentId ?? undefined,
      scenario_id: candidate.scenarioId ?? undefined,
      scenario_profile: String(manifest.scenario_profile ?? scenarioProfile),
      algorithm: pair.candidateAlgorithm,
      seed: Number(manifest.seed ?? seed),
      duration_s: Number(manifest.duration_s ?? durationS),
      simulation_time_s: pair.simulationTimeS,
      intersections: candidate.intersectionMetrics.map((item) => ({
        ...item,
        lane_states: Array.isArray(item.approaches) ? item.approaches : [],
      })) as unknown as IntersectionRealtime[],
    };
    setComparisonHistory((current) => {
      const sameRun = current.filter((item) => item.experiment_id === next.experiment_id);
      const withoutCurrentTime = sameRun.filter(
        (item) => item.simulation_time_s !== next.simulation_time_s,
      );
      return [...withoutCurrentTime, next]
        .sort((left, right) => (left.simulation_time_s ?? 0) - (right.simulation_time_s ?? 0))
        .slice(-180);
    });
  }, [durationS, pairedDigitalTwin.connection, pairedDigitalTwin.state, scenarioProfile, seed]);

  useEffect(() => {
    if (!replayChoice && playback.selectedReplayId) {
      setReplayChoice(playback.selectedReplayId);
    }
  }, [playback.selectedReplayId, replayChoice]);

  useEffect(() => {
    const actual = playback.replays.filter((item) => item.actualRun);
    setBaselineChoice((current) => current || actual[1]?.experimentId || actual[0]?.experimentId || "");
    setCandidateChoice((current) => current || actual[0]?.experimentId || "");
  }, [playback.replays]);

  const replaySnapshot = useMemo<RealtimeSnapshot>(() => {
    const metrics = digitalTwin.state.metrics as unknown as Partial<RealtimeSnapshot>;
    const replayItem = playback.replays.find((item) => item.experimentId === playback.selectedReplayId);
    const intersections = digitalTwin.state.intersectionMetrics.map((item) => ({
      ...item,
      lane_states: [],
    })) as unknown as IntersectionRealtime[];
    return {
      ...metrics,
      status: playback.replay.playing ? "replay-running" : "replay-paused",
      message: "真实 SUMO 实验数据回放",
      experiment_id: digitalTwin.state.experimentId ?? undefined,
      scenario_id: digitalTwin.state.scenarioId ?? undefined,
      scenario_profile: replayItem?.profile ?? undefined,
      seed: replayItem?.seed ?? undefined,
      duration_s: playback.replay.durationS,
      simulation_time_s: digitalTwin.state.simulationTimeS,
      intersections,
    };
  }, [digitalTwin.state, playback.replay.durationS, playback.replay.playing, playback.replays, playback.selectedReplayId]);

  const viewSnapshot = playback.mode === "replay" ? replaySnapshot : snapshot;

  const currentScenario = scenarios.find((item) => item.scenario_id === scenarioId);
  const profileOptions = [
    {
      code: "BASE",
      name: "综合扰动主场景",
      flow_multiplier: 1,
      communication_profile: "configured",
      disturbance_types: [],
    },
    ...(currentScenario?.profiles ?? []),
  ];

  useEffect(() => {
    if (playback.mode !== "replay" || !digitalTwin.state.initialized) return;
    if (replayExperimentRef.current !== digitalTwin.state.experimentId) {
      replayExperimentRef.current = digitalTwin.state.experimentId;
      setReplayHistory([replaySnapshot]);
      return;
    }
    setReplayHistory((current) => {
      const withoutCurrentTime = current.filter(
        (item) => item.simulation_time_s !== replaySnapshot.simulation_time_s,
      );
      return [...withoutCurrentTime, replaySnapshot]
        .sort((left, right) =>
          (left.simulation_time_s ?? 0) - (right.simulation_time_s ?? 0),
        )
        .slice(-180);
    });
  }, [digitalTwin.state, playback.mode, replaySnapshot]);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let reconnectTimer: number | null = null;
    let closed = false;
    const connect = () => {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      socket = new WebSocket(`${protocol}//${window.location.host}/ws/v1/realtime`);
      socket.onopen = () => setConnection("online");
      socket.onclose = () => {
        setConnection("offline");
        if (!closed) reconnectTimer = window.setTimeout(connect, 1500);
      };
      socket.onerror = () => setConnection("offline");
      socket.onmessage = (message) => {
        const next = JSON.parse(message.data as string) as RealtimeSnapshot;
        const activeExperimentId = activeExperimentRef.current;
        if (!isActiveRealtimeSnapshot(activeExperimentId, next.experiment_id)) return;
        if (pendingStartRef.current) pendingStartRef.current = false;
        setSnapshot(next);
        if (next.experiment_id) {
          setExperimentId(next.experiment_id);
          if (["starting", "running", "paused"].includes(next.status)) {
            activeExperimentRef.current = next.experiment_id;
          }
        }
        if (next.algorithm) setAlgorithm(next.algorithm);
        if (next.simulation_time_s !== undefined) {
          setHistory((current) => [...current, next].slice(-180));
        }
        const previous = previousRef.current;
        if (previous?.fallback_mode !== next.fallback_mode && next.fallback_mode) {
          const recovery = next.fallback_mode === "CLOUD_COORDINATED";
          setLocalEvents((current) => [
            {
              id: `${next.simulation_time_s}-${next.fallback_mode}`,
              simulationTime: next.simulation_time_s ?? null,
              type: recovery
                ? ("recovery" as const)
                : ("state" as const),
              title: recovery ? "恢复云边协调" : "边缘模式切换",
              detail: next.fallback_mode ?? "",
            },
            ...current,
          ].slice(0, 20));
        }
        if (
          previous?.cloud_online !== next.cloud_online &&
          next.cloud_online !== undefined
        ) {
          setLocalEvents((current) => [
            {
              id: `${next.simulation_time_s}-cloud-${next.cloud_online}`,
              simulationTime: next.simulation_time_s ?? null,
              type: next.cloud_online
                ? ("recovery" as const)
                : ("fault" as const),
              title: next.cloud_online ? "云端通信恢复" : "云端通信中断",
              detail: next.cloud_online
                ? "等待状态与策略版本同步"
                : "边缘端将按阈值自动降级",
            },
            ...current,
          ].slice(0, 20));
        }
        previousRef.current = next;
      };
    };
    connect();
    return () => {
      closed = true;
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, []);

  const coreIds = nodes
    .filter((node) => node.role === "core_corridor")
    .map((node) => node.intersection_id);
  const averageLatency =
    viewSnapshot.end_to_end_control_latency_ms ??
    viewSnapshot.cloud_decision_latency_ms ??
    viewSnapshot.edge_decision_latency_ms;
  const replayEvents: RuntimeEvent[] = digitalTwin.state.events.map((event) => ({
    simulation_time: event.simulationTime,
    event: event.event,
    detail: event.detail ?? undefined,
  }));
  const backendEvents = (
    playback.mode === "replay" ? replayEvents : (viewSnapshot.recent_events ?? [])
  ).map(classifyEvent).reverse();
  const eventMap = new Map<string, TimelineEvent>();
  for (const event of [...backendEvents, ...localEvents]) eventMap.set(event.id, event);
  const timelineEvents = selectOperationalTimelineEvents([...eventMap.values()]);
  const baselineReplay = playback.replays.find((item) => item.experimentId === baselineChoice);
  const candidateReplay = playback.replays.find((item) => item.experimentId === candidateChoice);
  const comparisonMetrics: Array<[string, string, boolean]> = [
    ["mean_speed_m_s", "平均速度", true],
    ["mean_waiting_time", "平均等待", false],
    ["mean_queue_vehicles", "平均排队", false],
    ["max_queue", "最大排队", false],
    ["completed_trips", "完成出行", true],
    ["end_to_end_control_latency_ms", "端到端时延", false],
  ];

  const runCommand = async (
    label: string,
    operation: () => Promise<unknown>,
    transportCommand: TransportCommand | null = null,
  ): Promise<string | null> => {
    const feedbackStartedAt = Date.now();
    setCommandBusy(true);
    setCommandLabel(label);
    setActiveTransportCommand(transportCommand);
    setError(null);
    try {
      await operation();
      return null;
    } catch (reason) {
      const message = describeRequestError(reason);
      setError(message);
      return message;
    } finally {
      const feedbackRemainingMs = minimumCommandFeedbackMs - (Date.now() - feedbackStartedAt);
      if (feedbackRemainingMs > 0) {
        await new Promise((resolve) => window.setTimeout(resolve, feedbackRemainingMs));
      }
      setCommandBusy(false);
      setCommandLabel(null);
      setActiveTransportCommand(null);
    }
  };

  const launchExperiment = async (
    targetScenarioId: string,
    targetAlgorithm: string,
    fallbackSnapshot: RealtimeSnapshot,
    options: {profile?: string; seed?: number; durationS?: number} = {},
  ) => {
    const targetProfile = options.profile ?? scenarioProfile;
    const targetSeed = options.seed ?? seed;
    const targetDurationS = options.durationS ?? durationS;
    pendingStartRef.current = true;
    activeExperimentRef.current = null;
    setSnapshot({
      status: "starting",
      message: "正在启动 SUMO 与 TraCI",
      scenario_id: targetScenarioId,
      scenario_profile: targetProfile,
      algorithm: targetAlgorithm,
      seed: targetSeed,
      duration_s: targetDurationS,
      simulation_time_s: 0,
    });
    try {
      const id = await createAndStartExperiment({
        scenario_id: targetScenarioId,
        profile: targetProfile,
        algorithm: targetAlgorithm,
        seed: targetSeed,
        duration_s: targetDurationS,
      }, simulationRateRef.current);
      activeExperimentRef.current = id;
      setSnapshot((current) => ({...current, experiment_id: id}));
      setExperimentId(id);
      setHistory([]);
      setLocalEvents([
        {
          id: `${id}-start`,
          simulationTime: 0,
          type: "state",
          title: "实验启动",
          detail: `${targetProfile} · ${algorithmLabel(targetAlgorithm)} · seed ${targetSeed} · ${targetDurationS}s`,
        },
      ]);
    } catch (reason) {
      pendingStartRef.current = false;
      activeExperimentRef.current = null;
      setSnapshot(fallbackSnapshot);
      throw reason;
    }
  };

  const stopSingleRuntimeBeforeComparison = async () => {
    const activeId = experimentId ?? snapshot.experiment_id ?? digitalTwin.state.experimentId;
    if (!activeId) return;
    const state = await loadExperimentState(activeId);
    if (!terminalRuntimeStatuses.has(state.status)) {
      if (!["stopping", "finalizing"].includes(state.status)) {
        await lifecycle(activeId, "stop");
      }
      await waitForRuntimeTerminal(activeId, loadExperimentState);
    }
    activeExperimentRef.current = null;
    pendingStartRef.current = false;
    setExperimentId(null);
    setSnapshot({status: "idle", message: "单路仿真已停止"});
  };

  const stopComparisonRuntimeBeforeExperiment = async () => {
    const activeId = comparisonId ?? pairedDigitalTwin.state.pairId;
    if (!activeId) return;
    if (!terminalRuntimeStatuses.has(pairedDigitalTwin.state.status)) {
      const state = await loadLiveComparisonState(activeId);
      if (state.status !== "stopping") {
        await liveComparisonLifecycle(activeId, "stop");
      }
      await waitForRuntimeTerminal(activeId, loadLiveComparisonState);
    }
    setComparisonId(null);
    setComparisonHistory([]);
    pairedDigitalTwin.reset?.();
  };

  const clearRuntimePresentation = (message = "已重置，等待启动") => {
    activeExperimentRef.current = null;
    pendingStartRef.current = false;
    previousRef.current = null;
    replayExperimentRef.current = null;
    setExperimentId(null);
    setComparisonId(null);
    setHistory([]);
    setComparisonHistory([]);
    setReplayHistory([]);
    setLocalEvents([]);
    setSelectedId(null);
    setStartupStage(null);
    setSnapshot({status: "idle", message, simulation_time_s: 0});
    simulationRateRef.current = 1;
    setSimulationRateState(1);
    playback.goLive();
    playback.resetLive();
    pairedDigitalTwin.reset?.();
  };

  const changeSimulationView = (next: "2d" | "3d") =>
    runCommand(`正在重置并切换到 ${next.toUpperCase()}`, async () => {
      await stopSingleRuntimeBeforeComparison();
      await stopComparisonRuntimeBeforeExperiment();
      clearRuntimePresentation(`已切换到 ${next.toUpperCase()}，等待启动`);
    }, "reset");

  const start = (
    targetScenarioId = scenarioId,
    options: {profile?: string; seed?: number; durationS?: number} = {},
  ) => {
    const runtime = resolveScenarioRuntimeParameters(
      scenarios,
      targetScenarioId,
      {seed, durationS},
      options,
    );
    return runCommand("正在启动 SUMO 与协同链路", async () => {
      await stopComparisonRuntimeBeforeExperiment();
      await launchExperiment(targetScenarioId, algorithm, snapshot, {...options, ...runtime});
    }, "start");
  };

  const enterGeneratedScenario = async (targetScenarioId: string, view: "2d" | "3d") => {
    const inventory = await refreshInventory();
    const targetScenario = inventory.scenarios.find((item) => item.scenario_id === targetScenarioId);
    if (!targetScenario?.runnable) throw new Error("生成场景尚未通过 SUMO 可运行校验");
    const targetSeed = targetScenario.seed ?? seed;
    const targetDurationS = targetScenario.duration_s ?? 180;
    setScenarioId(targetScenarioId);
    setScenarioProfile("BASE");
    setSeed(targetSeed);
    setDurationS(targetDurationS);
    simulationRateRef.current = 1;
    setSimulationRateState(1);
    const url = new URL(window.location.href);
    url.searchParams.set("view", view);
    url.searchParams.set("run", "single");
    window.history.replaceState(null, "", url);
    const activeId = experimentId ?? snapshot.experiment_id ?? digitalTwin.state.experimentId;
    if (activeId) {
      const activeState = await loadExperimentState(activeId);
      if (canReuseExperiment(activeState, targetScenarioId)) {
        activeExperimentRef.current = activeId;
        pendingStartRef.current = false;
        setExperimentId(activeId);
        setSnapshot((current) => ({
          ...current,
          status: activeState.status,
          experiment_id: activeId,
          scenario_id: targetScenarioId,
          scenario_profile: activeState.request.profile,
          algorithm: activeState.request.algorithm,
          seed: activeState.request.seed,
          duration_s: activeState.request.duration_s,
        }));
        changeWorkspace("simulation");
        return;
      }
    }
    await stopSingleRuntimeBeforeComparison();
    await start(targetScenarioId, {profile: "BASE", seed: targetSeed, durationS: targetDurationS});
    changeWorkspace("simulation");
  };

  const waitForPairedFirstFrame = async (pairId: string): Promise<void> => {
    const deadline = Date.now() + pairedFirstFrameTimeoutMs;
    while (Date.now() < deadline) {
      const stream = pairedDigitalTwinRef.current;
      const state = stream.state;
      if (state.pairId === pairId && state.simulationTimeS > 0 && state.initialized) return;
      if (state.pairId === pairId && ["failed", "invalid"].includes(state.status)) {
        throw new Error(stream.issue || "双路 SUMO 启动失败");
      }
      await new Promise((resolve) => window.setTimeout(resolve, 120));
    }
    throw new Error("双路仿真等待超时：120 秒内未收到基准与候选路的首帧数据。请重新启动；若再次出现，请检查后端与 TraCI 连接");
  };

  const startComparison = () =>
    runCommand("正在启动同条件双 SUMO 实时对照", async () => {
      try {
      if (candidateAlgorithm === "fixed-time") {
        throw new Error("候选算法必须与基准 fixed-time 不同");
      }
      const runtime = resolveScenarioRuntimeParameters(
        scenarios,
        scenarioId,
        {seed, durationS},
      );
      setStartupStage("准备运行环境");
      await stopSingleRuntimeBeforeComparison();
      if (
        comparisonId
        && ["created", "configured"].includes(pairedDigitalTwin.state.status)
      ) {
        setStartupStage("启动双路 SUMO");
        await liveComparisonLifecycle(comparisonId, "start");
        setStartupStage("等待 TraCI 首帧");
        await waitForPairedFirstFrame(comparisonId);
        setComparisonHistory([]);
        setLocalEvents((current) => [{
          id: `${comparisonId}-start`,
          simulationTime: 0,
          type: "state" as const,
          title: "实时对照启动",
          detail: `fixed-time ↔ ${algorithmLabel(candidateAlgorithm)} · ${scenarioProfile} · seed ${runtime.seed}`,
        }, ...current].slice(0, 20));
        return;
      }
      const stageLabels = {
        creating: "创建对照任务",
        configuring: "配置运行倍速",
        starting: "启动双路 SUMO",
      } as const;
      const created = await createAndStartLiveComparison({
        scenario_id: scenarioId,
        profile: scenarioProfile,
        baseline_algorithm: "fixed-time",
        candidate_algorithm: candidateAlgorithm,
        seed: runtime.seed,
        duration_s: runtime.durationS,
      }, simulationRateRef.current, (stage) => setStartupStage(stageLabels[stage]));
      setComparisonId(created.id);
      setStartupStage("等待 TraCI 首帧");
      await waitForPairedFirstFrame(created.id);
      setComparisonHistory([]);
      setLocalEvents((current) => [{
        id: `${created.id}-start`,
        simulationTime: 0,
        type: "state" as const,
        title: "实时对照启动",
        detail: `fixed-time ↔ ${algorithmLabel(candidateAlgorithm)} · ${scenarioProfile} · seed ${runtime.seed}`,
      }, ...current].slice(0, 20));
      } finally {
        setStartupStage(null);
      }
    }, "start");

  const changeAlgorithm = (targetAlgorithm: string) => {
    if (targetAlgorithm === algorithm) return;
    const shouldRestart = playback.mode === "live"
      && Boolean(experimentId)
      && ["starting", "running", "paused"].includes(snapshot.status);
    if (!shouldRestart) {
      setAlgorithm(targetAlgorithm);
      return;
    }
    void runCommand(`正在切换到${algorithmLabel(targetAlgorithm)}`, async () => {
      if (experimentId) await lifecycle(experimentId, "stop");
      activeExperimentRef.current = null;
      pendingStartRef.current = false;
      setExperimentId(null);
      setAlgorithm(targetAlgorithm);
      await launchExperiment(
        scenarioId,
        targetAlgorithm,
        {...snapshot, status: "stopped", message: "原实验已停止，新算法启动失败"},
      );
    });
  };

  const reset = () =>
    runCommand("正在重置中", async () => {
      await stopSingleRuntimeBeforeComparison();
      clearRuntimePresentation();
    }, "reset");

  const resetComparison = () =>
    runCommand("正在重置实时对照", async () => {
      await stopComparisonRuntimeBeforeExperiment();
      clearRuntimePresentation();
    }, "reset");

  const changeSingleSimulationRate = async (value: number | null): Promise<string | null> => {
    const activeId = activeExperimentRef.current ?? experimentId;
    if (!activeId) {
      simulationRateRef.current = value;
      setSimulationRateState(value);
      return null;
    }
    const issue = await runCommand(
      "正在调整 SUMO 运行倍速",
      () => setSimulationRate(activeId, value),
    );
    if (issue === null) {
      simulationRateRef.current = value;
      setSimulationRateState(value);
    }
    return issue;
  };

  const changeComparisonSimulationRate = async (value: number | null): Promise<string | null> => {
    const activeId = comparisonId ?? pairedDigitalTwin.state.pairId;
    if (!activeId) {
      simulationRateRef.current = value;
      setSimulationRateState(value);
      return null;
    }
    const issue = await runCommand(
      "正在调整双路 SUMO 倍速",
      () => setLiveComparisonRate(activeId, value),
    );
    if (issue === null) {
      simulationRateRef.current = value;
      setSimulationRateState(value);
    }
    return issue;
  };

  const fault = (
    faultType: string,
    target: string,
    detail: string,
    parameters: Record<string, number | string | boolean> = {},
    injectedDurationS = 30,
  ) =>
    runCommand(`正在注入：${detail}`, async () => {
      const comparisonActive = new URLSearchParams(window.location.search).get("run") !== "single";
      const activePairId = comparisonActive ? comparisonId : null;
      if (activePairId) {
        await injectLiveComparisonFault(activePairId, faultType, target, parameters, injectedDurationS);
      } else {
        await injectFault(faultType, target, parameters, injectedDurationS);
      }
      setLocalEvents((current) => [
        {
          id: `fault-${Date.now()}`,
          simulationTime: activePairId ? pairedDigitalTwin.state.simulationTimeS : snapshot.simulation_time_s ?? null,
          type: "fault",
          title: "故障注入",
          detail,
        },
        ...current,
      ]);
    });

  const clearActiveFaults = () => {
    const activePairId = new URLSearchParams(window.location.search).get("run") !== "single"
      ? comparisonId
      : null;
    return runCommand(
      "正在清除故障",
      () => activePairId ? clearLiveComparisonFaults(activePairId) : clearFaults(),
    );
  };

  const kpis = useMemo<Array<[string, string, string]>>(
    () => [
      ["平均速度", formatMetric(viewSnapshot.mean_speed_m_s), "m/s"],
      ["平均等待", formatMetric(viewSnapshot.waiting_time_s), "s"],
      ["当前总排队", formatMetric(viewSnapshot.total_queue_vehicles, 0), "veh"],
      ["最大路口排队", formatMetric(viewSnapshot.max_queue_vehicles, 0), "veh"],
      ["累计吞吐", formatMetric(viewSnapshot.throughput_vehicles, 0), "veh"],
      ["完成车辆", formatMetric(viewSnapshot.completed_trips, 0), "veh"],
      ["骑行者在途", formatMetric(viewSnapshot.bicycle_active_count, 0), "人"],
      ["骑行排队", formatMetric(viewSnapshot.bicycle_queue_count, 0), "人"],
      ["行人在途", formatMetric(viewSnapshot.pedestrian_active_count, 0), "人"],
      ["行人等待", formatMetric(viewSnapshot.pedestrian_waiting_time_s), "s"],
      ["完成过街", formatMetric(viewSnapshot.pedestrian_crossing_count, 0), "次"],
      ["最小 TTC", formatMetric(viewSnapshot.minimum_ttc_s), "s"],
      ["最小 PET", formatMetric(viewSnapshot.minimum_pet_s), "s"],
      ["端到端时延", formatMetric(averageLatency), "ms"],
      ["边缘决策", formatMetric(viewSnapshot.edge_decision_latency_ms), "ms"],
    ],
    [averageLatency, viewSnapshot],
  );

  const cockpitHistory = playback.mode === "replay" ? replayHistory : history;
  const cockpitComparison = baselineReplay?.actualRun && candidateReplay?.actualRun
    && candidateReplay.experimentId === viewSnapshot.experiment_id
    ? {
        baselineLabel: baselineReplay.algorithm ?? "Baseline",
        candidateLabel: candidateReplay.algorithm ?? "Candidate",
        baseline: baselineReplay.summaryMetrics,
        candidate: candidateReplay.summaryMetrics,
      }
    : null;
  const commandFeedbackLabel = startupStage ? startupPhaseLabel(startupStage) : commandLabel;

  return (
    <main className={`app-shell has-platform-nav workspace-${workspace}`}>
      <PlatformWorkspaceNav active={workspace} onChange={changeWorkspace} />
      {commandFeedbackLabel && (
        <div className={`command-banner ${startupStage ? "pending" : ""}`} role="status">
          <span />
          {commandFeedbackLabel}
        </div>
      )}
      {error && workspace === "simulation" && (
        <div className="error-banner" role="alert">
          <TwinIcon name="warning" />
          <span>{error}</span>
          <button aria-label="关闭错误提示" onClick={() => setError(null)}><TwinIcon name="close" /></button>
        </div>
      )}

      {workspace === "simulation" && <SimulationCommandCenter
        activeTransportCommand={activeTransportCommand}
        algorithm={algorithm}
        algorithms={algorithms}
        candidateAlgorithm={candidateAlgorithm}
        commandBusy={commandBusy}
        comparisonHistory={comparisonHistory}
        comparisonId={comparisonId}
        digitalTwin={digitalTwin}
        durationS={durationS}
        experimentId={experimentId}
        comparison={cockpitComparison}
        history={cockpitHistory}
        nodes={nodes}
        onAlgorithmChange={changeAlgorithm}
        onCandidateAlgorithmChange={setCandidateAlgorithm}
        onClearFaults={clearActiveFaults}
        onComparisonPause={() => comparisonId && runCommand("正在暂停双路仿真", () => liveComparisonLifecycle(comparisonId, "pause"), "pause")}
        onComparisonReset={resetComparison}
        onComparisonResume={() => comparisonId && runCommand("正在继续双路仿真", () => liveComparisonLifecycle(comparisonId, "resume"), "start")}
        onComparisonSimulationRate={changeComparisonSimulationRate}
        onComparisonStart={startComparison}
        onComparisonStop={() => comparisonId && runCommand("正在停止双路仿真", () => liveComparisonLifecycle(comparisonId, "stop"), "stop")}
        onDurationChange={setDurationS}
        onFault={fault}
        onIntersectionSelect={setSelectedId}
        onGoLive={playback.goLive}
        onLoadReplay={(id) => runCommand("正在载入真实仿真回放", () => playback.loadReplay(id))}
        onPause={() => experimentId && runCommand("正在暂停", () => lifecycle(experimentId, "pause"), "pause")}
        onProfileChange={setScenarioProfile}
        onReplaySpeed={playback.setReplaySpeed}
        onSeekReplay={playback.seekReplay}
        onReset={reset}
        onResume={() => experimentId && runCommand("正在继续", () => lifecycle(experimentId, "resume"), "start")}
        onScenarioChange={(value) => { setScenarioId(value); setScenarioProfile("BASE"); }}
        onSeedChange={setSeed}
        onSimulationRate={changeSingleSimulationRate}
        onStart={start}
        onStop={() => experimentId && runCommand("正在停止", () => lifecycle(experimentId, "stop"), "stop")}
        onToggleReplay={playback.toggleReplay}
        onViewModeChange={changeSimulationView}
        pairedDigitalTwin={pairedDigitalTwin}
        replayPlaying={playback.replay.playing}
        replayBusy={playback.replayBusy}
        replayCurrentTimeS={playback.replay.currentTimeS}
        replayDurationS={playback.replay.durationS}
        replayLoaded={playback.replay.loaded}
        replaySpeed={playback.replay.speed}
        replays={playback.replays}
        scenarioId={scenarioId}
        scenarioProfile={scenarioProfile}
        scenarios={scenarios}
        seed={seed}
        simulationRate={simulationRate}
        selectedIntersectionId={selectedId}
        selectedReplayId={playback.selectedReplayId}
        snapshot={viewSnapshot}
        sourceMode={playback.mode}
        startupStage={startupStage}
        timelineEvents={timelineEvents}
        websocketOnline={connection === "online"}
      />}

      {workspace === "algorithms" && <Suspense fallback={<div aria-live="polite" className="workspace-loading" role="status"><i className="factory-spinner" aria-hidden="true" /><div><strong>正在载入算法评估</strong><span>准备实验矩阵、配对证据与指标视图</span></div><div aria-hidden="true" className="workspace-loading-skeleton"><b /><b /><b /></div></div>}><AlgorithmEvaluationWorkspace
        algorithms={algorithms}
        baselineId={baselineChoice}
        candidateId={candidateChoice}
        onBaselineChange={setBaselineChoice}
        onCandidateChange={setCandidateChoice}
        onRefresh={playback.refreshReplays}
        replays={playback.replays}
      /></Suspense>}

      {workspace === "scenarios" && <ScenarioFactoryWorkspace
        nodes={nodes}
        onBuilt={async (id) => {
          await refreshInventory();
          setScenarioId(id);
          setScenarioProfile("BASE");
        }}
        onEnter2D={(id) => enterGeneratedScenario(id, "2d")}
        onEnter3D={(id) => enterGeneratedScenario(id, "3d")}
        topologyEdges={topologyEdges}
      />}

      {false && <><div className="analysis-grid">
        <section className="trend-section" aria-labelledby="trend-title">
          <div className="section-heading compact">
            <div>
              <h2 id="trend-title">真实采样趋势</h2>
            </div>
            <span className="count-label">
              {playback.mode === "replay" ? replayHistory.length : history.length} 个采样点
            </span>
          </div>
          <TrendChart
            history={playback.mode === "replay" ? replayHistory : history}
            coreIntersectionIds={coreIds}
          />
          {!(playback.mode === "replay" ? replayHistory : history).length && (
            <p className="chart-empty">尚未运行，没有可绘制的指标数据</p>
          )}
        </section>
        <Timeline events={timelineEvents} />
      </div>

      <section className="replay-deck" aria-labelledby="replay-title">
        <div className="replay-heading">
          <h2 id="replay-title">实时 / 回放</h2>
          <span className={`replay-mode ${playback.mode}`}>{playback.mode.toUpperCase()}</span>
        </div>
        <label>
          真实实验记录
          <select
            value={replayChoice}
            onChange={(event) => setReplayChoice(event.target.value)}
          >
            {!playback.replays.length && <option value="">暂无回放</option>}
            {playback.replays.map((item) => (
              <option key={item.experimentId} value={item.experimentId}>
                {item.experimentId} · {item.simulationTimeS.toFixed(0)}s · {item.frameCount}帧
              </option>
            ))}
          </select>
        </label>
        <div className="replay-transport">
          <button
            disabled={!replayChoice || playback.replayBusy}
            onClick={() =>
              runCommand("正在载入真实仿真回放", () => playback.loadReplay(replayChoice))
            }
          >
            载入
          </button>
          <button
            className={playback.mode === "live" ? "primary-action" : ""}
            onClick={playback.goLive}
          >
            实时
          </button>
          <button
            disabled={playback.mode !== "replay" || !playback.replay.loaded}
            onClick={playback.toggleReplay}
          >
            {playback.replay.playing ? "暂停" : "播放"}
          </button>
          <button
            disabled={playback.mode !== "replay" || !playback.replay.loaded}
            onClick={playback.stepReplay}
          >
            单步
          </button>
          <label className="replay-speed">
            倍速
            <select
              value={playback.replay.speed}
              onChange={(event) => playback.setReplaySpeed(Number(event.target.value))}
            >
              {[0.5, 1, 2, 4, 8].map((speed) => (
                <option key={speed} value={speed}>{speed}×</option>
              ))}
            </select>
          </label>
          <button
            onClick={() =>
              runCommand("正在刷新回放清单", playback.refreshReplays)
            }
          >
            刷新
          </button>
        </div>
        <div className="replay-scrubber">
          <input
            aria-label="回放时间"
            disabled={playback.mode !== "replay" || !playback.replay.loaded}
            max={Math.max(1, playback.replay.durationS)}
            min={0}
            onChange={(event) => playback.seekReplay(Number(event.target.value))}
            step={1}
            type="range"
            value={playback.replay.currentTimeS}
          />
          <span>
            T+{playback.replay.currentTimeS.toFixed(0)} / {playback.replay.durationS.toFixed(0)}s
            {playback.replay.loaded
              ? ` · ${playback.replay.frameIndex + 1}/${playback.replay.frameCount}`
              : ""}
          </span>
        </div>
        {playback.replayIssue && <p className="replay-issue">{playback.replayIssue}</p>}
        <div className="experiment-comparison">
          <div>
            <strong>同一画布切换 + 真实结果指标对比</strong>
            <small>仅显示 result.json 中标记为实际运行的实验汇总，不推断控制收益</small>
          </div>
          <label>
            Baseline
            <select value={baselineChoice} onChange={(event) => setBaselineChoice(event.target.value)}>
              {playback.replays.filter((item) => item.actualRun).map((item) => (
                <option key={item.experimentId} value={item.experimentId}>
                  {item.algorithm ?? "unknown"} · {item.profile ?? "BASE"} · seed {item.seed ?? "—"}
                </option>
              ))}
            </select>
          </label>
          <label>
            Candidate
            <select value={candidateChoice} onChange={(event) => setCandidateChoice(event.target.value)}>
              {playback.replays.filter((item) => item.actualRun).map((item) => (
                <option key={item.experimentId} value={item.experimentId}>
                  {item.algorithm ?? "unknown"} · {item.profile ?? "BASE"} · seed {item.seed ?? "—"}
                </option>
              ))}
            </select>
          </label>
          <AlgorithmComparisonChart
            baseline={baselineReplay?.summaryMetrics}
            baselineLabel={baselineReplay?.algorithm ?? "Baseline"}
            candidate={candidateReplay?.summaryMetrics}
            candidateLabel={candidateReplay?.algorithm ?? "Candidate"}
          />
          <div className="comparison-values">
            {comparisonMetrics.map(([key, label, higherBetter]) => {
              const baseline = baselineReplay?.summaryMetrics?.[key];
              const candidate = candidateReplay?.summaryMetrics?.[key];
              const left = typeof baseline === "number" ? baseline : null;
              const right = typeof candidate === "number" ? candidate : null;
              const delta = left !== null && right !== null ? right - left : null;
              const favorable = delta === null || delta === 0 ? null : higherBetter ? delta > 0 : delta < 0;
              return (
                <div key={key}>
                  <span>{label}</span>
                  <b>{left === null ? "—" : left.toFixed(2)} → {right === null ? "—" : right.toFixed(2)}</b>
                  <small className={favorable === null ? "" : favorable ? "better" : "worse"}>
                    Δ {delta === null ? "—" : `${delta >= 0 ? "+" : ""}${delta.toFixed(2)}`}
                  </small>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      <section className="control-deck" aria-labelledby="control-title">
        <div>
          <h2 id="control-title">实验与故障控制</h2>
        </div>
        <div className="selectors">
          <label>
            场景
            <select
              value={scenarioId}
              onChange={(event) => {
                setScenarioId(event.target.value);
                setScenarioProfile("BASE");
              }}
            >
              {scenarios.map((item) => (
                <option
                  disabled={!item.runnable}
                  key={item.scenario_id}
                  value={item.scenario_id}
                >
                  {item.display_name}
                  {item.runnable ? "" : "（资料复现集）"}
                </option>
              ))}
            </select>
          </label>
          <label>
            工况
            <select
              aria-label="仿真工况"
              value={scenarioProfile}
              onChange={(event) => setScenarioProfile(event.target.value)}
            >
              {profileOptions.map((item) => (
                <option key={item.code} value={item.code}>
                  {item.code} · {item.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            算法
            <select
              value={algorithm}
              onChange={(event) => setAlgorithm(event.target.value)}
            >
              {algorithms.map((item) => (
                  <option key={item.name} value={item.name}>
                    {item.name}
                  </option>
                ))}
            </select>
          </label>
          <label>
            随机种子
            <input
              aria-label="随机种子"
              disabled={Boolean(experimentId)}
              max={2147483647}
              min={0}
              onChange={(event) => setSeed(Number(event.target.value))}
              step={1}
              type="number"
              value={seed}
            />
          </label>
          <label>
            仿真时长
            <select
              aria-label="仿真时长"
              disabled={Boolean(experimentId)}
              onChange={(event) => setDurationS(Number(event.target.value))}
              value={durationS}
            >
              <option value={300}>300 s 验证</option>
              <option value={900}>900 s 场景</option>
              <option value={1800}>1800 s 正式</option>
              <option value={3600}>3600 s 长稳</option>
            </select>
          </label>
        </div>
        <div className="control-actions">
          <button
            className="primary-action"
            disabled={commandBusy || playback.mode === "replay" || !currentScenario?.runnable}
            onClick={() => void start()}
          >
            启动
          </button>
          <button
            disabled={!experimentId || commandBusy || playback.mode === "replay"}
            onClick={() =>
              experimentId &&
              runCommand("正在暂停", () => lifecycle(experimentId, "pause"))
            }
          >
            暂停
          </button>
          <button
            disabled={!experimentId || commandBusy || playback.mode === "replay"}
            onClick={() =>
              experimentId &&
              runCommand("正在继续", () => lifecycle(experimentId, "resume"))
            }
          >
            继续
          </button>
          <button
            disabled={!experimentId || commandBusy || playback.mode === "replay"}
            onClick={() =>
              experimentId &&
              runCommand("正在停止", () => lifecycle(experimentId, "stop"))
            }
          >
            停止
          </button>
          <button disabled={commandBusy || playback.mode === "replay"} onClick={reset}>
            重置
          </button>
          <span className="control-divider" />
          <button
            disabled={commandBusy || playback.mode === "replay"}
            onClick={() =>
              fault("roadwork", "configured_downstream_lane", "施工占道")
            }
          >
            注入施工
          </button>
          <button
            disabled={commandBusy || playback.mode === "replay" || !experimentId}
            onClick={() =>
              fault("incident", "downstream_bottleneck", "事故车辆占道 60 秒", {}, 60)
            }
          >
            注入事故
          </button>
          <button
            disabled={commandBusy || playback.mode === "replay" || !experimentId}
            onClick={() =>
              fault(
                "flow_surge",
                "network_local",
                "区域流量突增 90s",
                {flow_multiplier: 1.8},
                90,
              )
            }
          >
            流量突增
          </button>
          <button
            disabled={commandBusy || playback.mode === "replay" || !experimentId}
            onClick={() =>
              fault(
                "large_event",
                "north_activity",
                "北部活动散场 120s",
                {flow_multiplier: 2.5},
                120,
              )
            }
          >
            大型活动
          </button>
          <button
            disabled={commandBusy || playback.mode === "replay"}
            onClick={() =>
              fault(
                "communication_latency",
                "cloud_edge",
                "云边延迟 500ms",
                {latency_ms: 500},
              )
            }
          >
            延迟 500ms
          </button>
          <button
            disabled={commandBusy || playback.mode === "replay"}
            onClick={() =>
              fault("packet_loss", "cloud_edge", "云边丢包 10%", {
                packet_loss_rate: 0.1,
              })
            }
          >
            丢包 10%
          </button>
          <button
            className="fault-action"
            disabled={commandBusy || playback.mode === "replay"}
            onClick={() =>
              fault("cloud_offline", "cloud", "云端断网 30s")
            }
          >
            断开云端
          </button>
          <button
            disabled={commandBusy || playback.mode === "replay"}
            onClick={() =>
              runCommand("正在清除故障", async () => {
                await clearFaults();
              })
            }
          >
            清除故障
          </button>
          <a
            className={`button-link ${experimentId && playback.mode === "live" ? "" : "disabled"}`}
            href={
              experimentId && playback.mode === "live"
                ? `/api/v1/experiments/${experimentId}/report`
                : undefined
            }
            target="_blank"
            rel="noreferrer"
          >
            导出报告
          </a>
        </div>
      </section></>}
    </main>
  );
}
