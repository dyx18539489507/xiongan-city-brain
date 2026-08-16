import type {MapSelection} from "../../2d/model";
import type {DigitalTwinState, RealtimeEvent} from "../../3d/network/digitalTwinTypes";
import type {StaticSceneDocument} from "../../3d/scene/types";
import type {IntersectionNode, RealtimeSnapshot} from "../../types";
import type {RealComparison} from "./TrendDock";
import {TwinIcon} from "./TwinIcon";
import {TwinInspector} from "./TwinInspector";

type Props = {collapsed: boolean; scene: StaticSceneDocument | null; state: DigitalTwinState; snapshot: RealtimeSnapshot; nodes: IntersectionNode[]; selection: MapSelection | null; comparison: RealComparison | null; onCollapsed: () => void};

function metric(value: number | null | undefined, digits = 1): string { return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "—"; }

function comparisonDelta(comparison: RealComparison | null, key: string, higherBetter: boolean): {label: string; better: boolean} | null {
  const before = comparison?.baseline?.[key];
  const after = comparison?.candidate?.[key];
  if (typeof before !== "number" || typeof after !== "number" || before === 0) return null;
  const ratio = (after - before) / Math.abs(before) * 100;
  return {label: `${ratio >= 0 ? "+" : ""}${ratio.toFixed(1)}%`, better: higherBetter ? ratio > 0 : ratio < 0};
}

/** Derived presentation state: it only classifies real fault/control/metric fields. */
export function hasActiveDisturbance(events: readonly RealtimeEvent[]): boolean {
  let active = false;
  for (const item of events) {
    if (/ROADWORK_LANE_CLOSED|INCIDENT_VEHICLE_STOPPED|EVENT_DISPERSAL_STARTED|FAULT_INJECTED|OFFLINE|PACKET_LOSS/i.test(item.event)) active = true;
    if (/ROADWORK_LANE_REOPENED|INCIDENT_CLEARED|INCIDENT_STOP_CANCELLED|EVENT_DISPERSAL_ENDED|FAULT_AUTO_CLEARED|RECOVERED/i.test(item.event)) active = false;
  }
  return active;
}

export function deriveOperationalStage(snapshot: RealtimeSnapshot, events: readonly RealtimeEvent[] = []): string {
  if (snapshot.status === "idle") return "等待启动";
  if (snapshot.status === "completed") return "仿真完成";
  if ((snapshot.active_disturbances?.length ?? 0) > 0 || hasActiveDisturbance(events)) return "扰动响应";
  if (snapshot.cloud_online === false || (snapshot.fallback_mode && snapshot.fallback_mode !== "CLOUD_COORDINATED")) return "边缘自治";
  if ((snapshot.congested_intersection_ids?.length ?? 0) > 0 || (snapshot.total_queue_vehicles ?? 0) >= 25) return "拥堵形成";
  if (snapshot.intersections?.some((item) => item.control_mode && !/fixed|none|idle/i.test(item.control_mode))) return "协同调控";
  if (snapshot.status.includes("running") || snapshot.status.includes("replay")) return "正常运行";
  return "数据就绪";
}

export function RegionalStatusPanel(props: Props) {
  if (props.collapsed) return <aside className="status-panel collapsed"><button aria-label="展开运行态势" className="panel-collapse-button" onClick={props.onCollapsed}><TwinIcon className="reverse" name="chevron" /><TwinIcon name="activity" /></button></aside>;
  const speedDelta = comparisonDelta(props.comparison, "mean_speed_m_s", true);
  const delayDelta = comparisonDelta(props.comparison, "mean_waiting_time", false);
  const queueDelta = comparisonDelta(props.comparison, "max_queue", false);
  const throughputDelta = comparisonDelta(props.comparison, "completed_trips", true);
  const kpis = [
    {label: "区域平均速度", value: metric(props.snapshot.mean_speed_m_s === undefined ? undefined : props.snapshot.mean_speed_m_s * 3.6), unit: "km/h", delta: speedDelta, tone: "free"},
    {label: "平均等待", value: metric(props.snapshot.waiting_time_s), unit: "s", delta: delayDelta, tone: "warning"},
    {label: "最大路口排队", value: metric(props.snapshot.max_queue_vehicles, 0), unit: "辆", delta: queueDelta, tone: "congested"},
    {label: "完成出行", value: metric(props.snapshot.completed_trips, 0), unit: "辆", delta: throughputDelta, tone: "cloud"},
  ];
  return <aside className="status-panel floating-panel">
    <header className="floating-panel-header"><div><span>REAL-TIME TRAFFIC</span><h2>区域运行态势</h2></div><button aria-label="收起运行态势" className="icon-button" onClick={props.onCollapsed}><TwinIcon name="chevron" /></button></header>
    <div className="status-scroll">
      <section className="stage-card"><span>当前阶段</span><strong>{deriveOperationalStage(props.snapshot, props.state.events)}</strong><i className={props.snapshot.status.includes("running") || props.snapshot.status.includes("replay") ? "active" : ""} /></section>
      <section className="regional-kpis">{kpis.map((item, index) => <article className={`${item.tone} ${index === 0 ? "hero" : ""}`} key={item.label}><span>{item.label}</span><div><strong>{item.value}</strong><small>{item.unit}</small></div>{item.delta && <em className={item.delta.better ? "better" : "worse"}>{item.delta.better ? "改善" : "变化"} {item.delta.label}</em>}</article>)}</section>
      <section className="status-subsection"><header><span>当前控制对象</span><TwinIcon name="focus" /></header><TwinInspector nodes={props.nodes} scene={props.scene} selection={props.selection} snapshot={props.snapshot} state={props.state} /></section>
      <section className="status-subsection coordination"><header><span>云边协同</span><TwinIcon name="cloud" /></header>
        <div><span><i className={props.snapshot.cloud_online === false ? "offline" : "online"} />云端调度</span><b>{props.snapshot.cloud_online === undefined ? "—" : props.snapshot.cloud_online ? "在线" : "离线"}</b></div>
        <div><span><i className={props.snapshot.mqtt_online === false ? "offline" : "online"} />消息链路</span><b>{props.snapshot.mqtt_online === undefined ? "—" : props.snapshot.mqtt_online ? "正常" : "中断"}</b></div>
        <div><span><i className="neutral" />控制模式</span><b>{props.snapshot.fallback_mode ?? "—"}</b></div>
        <div><span><i className="neutral" />端到端时延</span><b>{metric(props.snapshot.end_to_end_control_latency_ms)} ms</b></div>
      </section>
    </div>
  </aside>;
}
