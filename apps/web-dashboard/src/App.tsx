import {useEffect, useMemo, useRef, useState} from "react";
import {
  clearFaults,
  createAndStartExperiment,
  injectFault,
  lifecycle,
  loadInventory,
} from "./api";
import {Inspector} from "./components/Inspector";
import {UnityScene} from "./components/UnityScene";
import {Timeline} from "./components/Timeline";
import {TopologyView} from "./components/TopologyView";
import {TrendChart} from "./components/TrendChart";
import {useDigitalTwinPlayback} from "./3d/replay/useDigitalTwinPlayback";
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
  const digitalTwin = playback.stream;
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [algorithms, setAlgorithms] = useState<Algorithm[]>([]);
  const [nodes, setNodes] = useState<IntersectionNode[]>([]);
  const [edges, setEdges] = useState<TopologyEdge[]>([]);
  const [scenarioId, setScenarioId] = useState("xiongan_rongdong_20");
  const [scenarioProfile, setScenarioProfile] = useState("BASE");
  const [algorithm, setAlgorithm] = useState("coordinated-max-pressure");
  const [seed, setSeed] = useState(42);
  const [durationS, setDurationS] = useState(1800);
  const [experimentId, setExperimentId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<RealtimeSnapshot>({
    status: "idle",
    message: "尚未运行",
  });
  const [history, setHistory] = useState<RealtimeSnapshot[]>([]);
  const [localEvents, setLocalEvents] = useState<TimelineEvent[]>([]);
  const [connection, setConnection] = useState<
    "connecting" | "online" | "offline"
  >("connecting");
  const [commandBusy, setCommandBusy] = useState(false);
  const [commandLabel, setCommandLabel] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [replayChoice, setReplayChoice] = useState("");
  const [replayHistory, setReplayHistory] = useState<RealtimeSnapshot[]>([]);
  const [baselineChoice, setBaselineChoice] = useState("");
  const [candidateChoice, setCandidateChoice] = useState("");
  const previousRef = useRef<RealtimeSnapshot | null>(null);
  const replayExperimentRef = useRef<string | null>(null);
  const showcaseReplayStartedRef = useRef(false);

  useEffect(() => {
    loadInventory()
      .then((inventory) => {
        setScenarios(inventory.scenarios);
        setAlgorithms(inventory.algorithms);
        setNodes(inventory.intersections);
        setEdges(inventory.topologyEdges);
        setAlgorithm(inventory.activeAlgorithm);
        setSelectedId(
          inventory.intersections.find((item) => item.display_id === "K08")
            ?.intersection_id ?? inventory.intersections[0]?.intersection_id ?? null,
        );
      })
      .catch((reason: unknown) => setError(String(reason)));
  }, []);

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

  useEffect(() => {
    if (showcaseReplayStartedRef.current || !playback.replays.length) return;
    const showcase = playback.replays[0];
    const timer = window.setTimeout(() => {
      if (showcaseReplayStartedRef.current) return;
      showcaseReplayStartedRef.current = true;
      playback
        .loadReplay(showcase.experimentId)
        .then(() => {
          playback.seekReplay(Math.min(311, Math.max(0, showcase.simulationTimeS - 359)));
        })
        .catch((reason: unknown) => {
          showcaseReplayStartedRef.current = false;
          setError(String(reason));
        });
    }, 3200);
    return () => window.clearTimeout(timer);
  }, [playback.loadReplay, playback.replays, playback.seekReplay, playback.toggleReplay]);

  const replaySnapshot = useMemo<RealtimeSnapshot>(() => {
    const metrics = digitalTwin.state.metrics as unknown as Partial<RealtimeSnapshot>;
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
      simulation_time_s: digitalTwin.state.simulationTimeS,
      intersections,
    };
  }, [digitalTwin.state, playback.replay.playing]);

  const viewSnapshot = playback.mode === "replay" ? replaySnapshot : snapshot;

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
        setSnapshot(next);
        if (next.experiment_id) setExperimentId(next.experiment_id);
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

  const selectedNode =
    nodes.find((node) => node.intersection_id === selectedId) ?? null;
  const selectedRealtime =
    viewSnapshot.intersections?.find((item) => item.intersection_id === selectedId) ??
    null;
  const currentScenario = scenarios.find(
    (item) => item.scenario_id === scenarioId,
  );
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
  const timelineEvents = [...eventMap.values()].slice(0, 60);
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
  ) => {
    setCommandBusy(true);
    setCommandLabel(label);
    setError(null);
    try {
      await operation();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setCommandBusy(false);
      setCommandLabel(null);
    }
  };

  const start = () =>
    runCommand("正在启动 SUMO 与协同链路", async () => {
      const id = await createAndStartExperiment({
        scenario_id: scenarioId,
        profile: scenarioProfile,
        algorithm,
        seed,
        duration_s: durationS,
      });
      setExperimentId(id);
      setHistory([]);
      setLocalEvents([
        {
          id: `${id}-start`,
          simulationTime: 0,
          type: "state",
          title: "实验启动",
          detail: `${scenarioProfile} · ${algorithm} · seed ${seed} · ${durationS}s`,
        },
      ]);
    });

  const reset = () =>
    runCommand("正在安全停止并重置", async () => {
      if (experimentId && ["running", "paused"].includes(snapshot.status)) {
        await lifecycle(experimentId, "stop");
      }
      setExperimentId(null);
      setHistory([]);
      setLocalEvents([]);
      setSnapshot({status: "idle", message: "已重置，等待启动"});
      previousRef.current = null;
    });

  const fault = (
    faultType: string,
    target: string,
    detail: string,
    parameters: Record<string, number | string | boolean> = {},
    injectedDurationS = 30,
  ) =>
    runCommand(`正在注入：${detail}`, async () => {
      await injectFault(faultType, target, parameters, injectedDurationS);
      setLocalEvents((current) => [
        {
          id: `fault-${Date.now()}`,
          simulationTime: snapshot.simulation_time_s ?? null,
          type: "fault",
          title: "故障注入",
          detail,
        },
        ...current,
      ]);
    });

  const kpis = useMemo(
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

  return (
    <main className="app-shell">
      <header className="status-rail">
        <div className="brand-block">
          <span className="brand-mark">XA</span>
          <div>
            <strong>雄安交通协同控制台</strong>
            <small>ROAD · EDGE · CLOUD</small>
          </div>
        </div>
        <dl>
          <div>
            <dt>场景</dt>
            <dd>{currentScenario?.display_name ?? "加载中"}</dd>
          </div>
          <div>
            <dt>工况</dt>
            <dd>{viewSnapshot.scenario_profile ?? scenarioProfile}</dd>
          </div>
          <div>
            <dt>实验</dt>
            <dd>{viewSnapshot.experiment_id ?? experimentId ?? "尚未创建"}</dd>
          </div>
          <div>
            <dt>算法</dt>
            <dd>{viewSnapshot.algorithm ?? algorithm}</dd>
          </div>
          <div>
            <dt>仿真时间</dt>
            <dd>
              {viewSnapshot.simulation_time_s === undefined
                ? dash
                : `T+${viewSnapshot.simulation_time_s.toFixed(0)}s`}
            </dd>
          </div>
        </dl>
        <div className="live-states">
          <span
            className={`status-chip ${
              viewSnapshot.cloud_online === false ? "fault" : "ok"
            }`}
          >
            云端 {viewSnapshot.cloud_online === false ? "离线" : "在线"}
          </span>
          <span
            className={`status-chip ${
              viewSnapshot.mqtt_online === false ? "fault" : "ok"
            }`}
          >
            MQTT {viewSnapshot.mqtt_online === false ? "中断" : "在线"}
          </span>
          <span className={`status-chip ${connection}`}>
            WS {connection === "online" ? "在线" : "重连中"}
          </span>
          <span className="status-chip mode">
            {playback.mode === "replay" ? "REPLAY" : (viewSnapshot.fallback_mode ?? "IDLE")}
          </span>
        </div>
      </header>

      <UnityScene
        digitalTwin={digitalTwin}
        node={selectedNode}
        realtime={selectedRealtime}
        simulationTime={viewSnapshot.simulation_time_s}
        status={viewSnapshot.status}
        websocketOnline={connection === "online"}
        sourceMode={playback.mode}
      />

      <section className="kpi-strip" aria-label="实时关键指标">
        {kpis.map(([label, value, unit]) => (
          <div key={label}>
            <span>{label}</span>
            <strong>{value}</strong>
            <small>{unit}</small>
          </div>
        ))}
      </section>

      {commandLabel && (
        <div className="command-banner" role="status">
          <span />
          {commandLabel}
        </div>
      )}
      {error && (
        <div className="error-banner" role="alert">
          {error}
        </div>
      )}

      <div className="primary-grid">
        <TopologyView
          nodes={nodes}
          edges={edges}
          realtime={viewSnapshot.intersections ?? []}
          selectedId={selectedId}
          activeDisturbances={viewSnapshot.active_disturbances ?? []}
          congestedIntersections={viewSnapshot.congested_intersection_ids ?? []}
          spillbackEdges={viewSnapshot.spillback_edges ?? []}
          onSelect={setSelectedId}
        />
        <Inspector node={selectedNode} realtime={selectedRealtime} />
      </div>

      <div className="analysis-grid">
        <section className="trend-section" aria-labelledby="trend-title">
          <div className="section-heading compact">
            <div>
              <p className="eyebrow">LIVE METRICS</p>
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
          <p className="eyebrow">TRUTHFUL PLAYBACK</p>
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
            LIVE
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
            <p className="eyebrow">ACTUAL RUN COMPARISON</p>
            <strong>同一画布切换 + 真实结果指标对比</strong>
            <small>仅显示 result.json 中 actual_run=true 的实验汇总，不推断控制收益</small>
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
          <p className="eyebrow">EXPERIMENT CONTROL</p>
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
              {algorithms
                .filter(
                  (item) =>
                    item.name !== "predictive-controller-placeholder",
                )
                .map((item) => (
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
            onClick={start}
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
              fault("incident", "downstream_bottleneck", "事故车辆占道 60s", {}, 60)
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
      </section>
    </main>
  );
}
