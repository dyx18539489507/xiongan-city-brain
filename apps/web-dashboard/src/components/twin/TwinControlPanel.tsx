import {useMemo, useState} from "react";
import type {LayerKey, LayerVisibility} from "../../2d/model";
import type {PairedDigitalTwinStream} from "../../3d/network/comparisonDigitalTwinTypes";
import type {StaticSceneDocument} from "../../3d/scene/types";
import {algorithmOptionLabel, sortAlgorithms} from "../../algorithmLabels";
import type {Algorithm, IntersectionNode, RealtimeSnapshot, Scenario, ScenarioProfile} from "../../types";
import {supportedEvents, type SupportedEvent} from "./EventDrawer";
import type {ComparisonRole} from "./AlgorithmComparisonDock";
import {ReferenceControlPanel} from "./ReferenceControlPanel";
import {TwinIcon} from "./TwinIcon";

export type TwinControlPanelProps = {
  collapsed: boolean;
  comparisonMode: boolean;
  comparisonRole: ComparisonRole;
  scene: StaticSceneDocument | null;
  scenarios: Scenario[];
  algorithms: Algorithm[];
  snapshot: RealtimeSnapshot;
  history: RealtimeSnapshot[];
  nodes: IntersectionNode[];
  selectedIntersectionId: string | null;
  viewMode: "2d" | "3d";
  algorithmDisabled: boolean;
  scenarioId: string;
  scenarioProfile: string;
  algorithm: string;
  seed: number;
  durationS: number;
  layers: LayerVisibility;
  pairedDigitalTwin: PairedDigitalTwinStream;
  activeEventCount: number;
  eventsDisabled: boolean;
  configurationDisabled: boolean;
  onCollapsed: () => void;
  onComparisonRoleChange: (role: ComparisonRole) => void;
  onScenarioChange: (value: string) => void;
  onIntersectionChange: (value: string | null) => void;
  onProfileChange: (value: string) => void;
  onAlgorithmChange: (value: string) => void;
  onSeedChange: (value: number) => void;
  onDurationChange: (value: number) => void;
  onLayerChange: (key: LayerKey) => void;
  onEventOpen: (event: SupportedEvent) => void;
  onClearEvents: () => void;
};

type AccordionKey = "scene" | "algorithm" | "event" | "layer";
export const layerGroups: Array<{label: string; items: Array<[LayerKey, string]>}> = [
  {label: "城市空间", items: [["baseMap", "基础路网"], ["geographicBaseMap", "地理底图"], ["buildings", "建筑地块"], ["roadMarkings", "车道标线"], ["corridor", "核心走廊"], ["rsu", "路侧设备"]]},
  {label: "交通主体", items: [["vehicles", "小汽车"], ["buses", "公交车"], ["trucks", "货车"], ["bicycles", "非机动车"], ["pedestrians", "行人"]]},
  {label: "运行态势", items: [["signals", "信号灯"], ["trafficState", "交通状态"], ["queues", "排队长度"], ["trails", "车辆轨迹"], ["algorithm", "算法证据"], ["events", "扰动事件"], ["labels", "路口标注"]]},
];

const algorithmDescriptions: Record<string, string> = {
  "fixed-time": "固定配时基线控制",
  "actuated-control": "基于检测状态的感应控制",
  "max-pressure": "路口最大压力控制",
  "coordinated-max-pressure": "在线预测增强的云边协同最大压力",
};

function metric(value: number | undefined, digits = 0): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "--";
}

function sparklinePoints(history: RealtimeSnapshot[]): string {
  const values = history
    .map((item) => item.total_queue_vehicles)
    .filter((value): value is number => typeof value === "number" && Number.isFinite(value))
    .slice(-32);
  if (!values.length) return "";
  const maximum = Math.max(...values, 1);
  return values.map((value, index) => {
    const x = values.length === 1 ? 50 : index / (values.length - 1) * 100;
    const y = 31 - value / maximum * 27;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
}

function LegacyControlPanel(props: TwinControlPanelProps) {
  const [open, setOpen] = useState<AccordionKey | null>("scene");
  const currentScenario = props.scenarios.find((item) => item.scenario_id === props.scenarioId);
  const profiles: ScenarioProfile[] = useMemo(() => [{code: "BASE", name: "基础配置", flow_multiplier: 1, communication_profile: "configured", disturbance_types: []}, ...(currentScenario?.profiles ?? [])], [currentScenario]);
  const scenarioNameCounts = useMemo(() => props.scenarios.reduce((counts, item) => counts.set(item.display_name, (counts.get(item.display_name) ?? 0) + 1), new Map<string, number>()), [props.scenarios]);
  const selectedRealtime = props.snapshot.intersections?.find((item) => item.intersection_id === props.selectedIntersectionId);
  const points = sparklinePoints(props.history);
  const queueVehicles = selectedRealtime?.queue_vehicles ?? props.snapshot.total_queue_vehicles;
  const speedMps = selectedRealtime?.mean_speed_m_s ?? props.snapshot.mean_speed_m_s;
  const speedKmh = speedMps === undefined ? undefined : speedMps * 3.6;
  const toggle = (key: AccordionKey) => setOpen((current) => current === key ? null : key);
  if (props.collapsed) return <aside className="control-panel collapsed"><button aria-label="展开控制面板" className="panel-collapse-button" onClick={props.onCollapsed}><TwinIcon name="settings" /><TwinIcon className="chevron" name="chevron" /></button></aside>;
  return <aside className={`control-panel floating-panel ${props.viewMode === "3d" ? "has-live" : ""}`}>
    <header className="floating-panel-header"><div><h2>协同管控</h2></div><button aria-label="收起控制面板" className="icon-button collapse-left" onClick={props.onCollapsed}><TwinIcon name="chevron" /></button></header>
    {props.viewMode === "3d" && <section className="control-panel-live" aria-label="三维场景实时概览">
      <label>
        <span>监测路口</span>
        <select aria-label="选择三维监测路口" onChange={(event) => props.onIntersectionChange(event.target.value || null)} value={props.selectedIntersectionId ?? ""}>
          <option value="">B01 · 参考展示区</option>
          {props.nodes.map((item) => <option key={item.intersection_id} value={item.intersection_id}>{item.display_id} · {item.display_name}</option>)}
        </select>
      </label>
      <div className="control-live-metrics">
        <div><span>排队</span><strong>{metric(queueVehicles)}<small> 辆</small></strong></div>
        <div><span>均速</span><strong>{metric(speedKmh, 1)}<small> km/h</small></strong></div>
        <div><span>完成出行</span><strong>{metric(props.snapshot.completed_trips)}<small> 辆</small></strong></div>
      </div>
      <div className="control-queue-trend">
        <span>区域排队趋势</span>
        {points ? <svg aria-label="最近区域排队趋势" preserveAspectRatio="none" role="img" viewBox="0 0 100 34"><polyline points={points} /></svg> : <small>等待实时采样</small>}
      </div>
    </section>}
    <div className="accordion-stack">
      <section className={open === "scene" ? "open" : ""}><button aria-expanded={open === "scene"} className="accordion-trigger" onClick={() => toggle("scene")}><span><TwinIcon name="map" />场景</span><TwinIcon name="chevron" /></button>{open === "scene" && <div className="accordion-content">
        <label>仿真场景<select aria-label="仿真场景" disabled={props.configurationDisabled} onChange={(event) => props.onScenarioChange(event.target.value)} value={props.scenarioId}>{props.scenarios.filter((item) => item.runnable).map((item) => <option key={item.scenario_id} value={item.scenario_id}>{item.display_name}{(scenarioNameCounts.get(item.display_name) ?? 0) > 1 ? ` · ${item.scenario_id}` : ""}</option>)}</select></label>
        <label>仿真工况<select aria-label="仿真工况" disabled={props.configurationDisabled} onChange={(event) => props.onProfileChange(event.target.value)} value={props.scenarioProfile}>{profiles.map((item) => <option key={item.code} value={item.code}>{item.code} · {item.name}</option>)}</select></label>
        <div className="compact-fields"><label>随机种子<input aria-label="随机种子" disabled={props.configurationDisabled} min={0} onChange={(event) => props.onSeedChange(Number(event.target.value))} type="number" value={props.seed} /></label><label>仿真时长<select aria-label="仿真时长" disabled={props.configurationDisabled} onChange={(event) => props.onDurationChange(Number(event.target.value))} value={props.durationS}>{[...new Set([300, 900, 1800, 3600, props.durationS])].sort((left, right) => left - right).map((value) => <option key={value} value={value}>{value}s</option>)}</select></label></div>
        {props.configurationDisabled && <p className="configuration-lock-note"><TwinIcon name="lock" />当前实验配置已锁定，停止或重置后可修改。</p>}
        {props.scene && <div className="scene-facts"><b>{props.scene.metadata.counts.trafficLights ?? props.scene.trafficLights.length}<span>信号路口</span></b><b>{props.scene.metadata.counts.lanes ?? props.scene.lanes.length}<span>SUMO 车道</span></b></div>}
      </div>}</section>
      <section className={open === "algorithm" ? "open" : ""}><button aria-expanded={open === "algorithm"} className="accordion-trigger" onClick={() => toggle("algorithm")}><span><TwinIcon name="activity" />算法</span><TwinIcon name="chevron" /></button>{open === "algorithm" && <div className="accordion-content algorithm-list">{sortAlgorithms(props.algorithms).map((item) => <button className={props.algorithm === item.name ? "active" : ""} disabled={props.algorithmDisabled} key={item.name} onClick={() => props.onAlgorithmChange(item.name)}><i /><span><strong>{algorithmOptionLabel(item.name)}</strong><small>{algorithmDescriptions[item.name] ?? `版本 ${item.version}`}</small></span></button>)}<p>{props.configurationDisabled ? "选择新算法会结束当前实验，并按相同场景配置重新启动。" : "当前选择将在下一次真实实验启动时生效。"}</p></div>}</section>
      <section className={open === "event" ? "open" : ""}><button aria-expanded={open === "event"} className="accordion-trigger" onClick={() => toggle("event")}><span><TwinIcon name="warning" />事件</span><em>{props.activeEventCount}</em><TwinIcon name="chevron" /></button>{open === "event" && <div className="accordion-content event-grid">{supportedEvents.map((item) => <button disabled={props.eventsDisabled} key={item.type} onClick={() => props.onEventOpen(item)}><TwinIcon name="warning" /><span>{item.label}<small>{item.targetLabel}</small></span></button>)}<button className="clear-events" disabled={props.eventsDisabled || !props.activeEventCount} onClick={props.onClearEvents}>清除活动事件</button>{props.eventsDisabled && <p>启动实时实验后可配置并注入扰动。</p>}</div>}</section>
      <section className={open === "layer" ? "open" : ""}><button aria-expanded={open === "layer"} className="accordion-trigger" onClick={() => toggle("layer")}><span><TwinIcon name="layers" />图层</span><TwinIcon name="chevron" /></button>{open === "layer" && <div className="accordion-content layer-groups">{layerGroups.map((group) => <div key={group.label}><p>{group.label}</p>{group.items.map(([key, label]) => <label className="twin-switch" key={key}><span>{label}</span><input checked={props.layers[key]} onChange={() => props.onLayerChange(key)} type="checkbox"/><i /></label>)}</div>)}</div>}</section>
    </div>
  </aside>;
}

export function TwinControlPanel(props: TwinControlPanelProps) {
  return props.viewMode === "3d" ? <ReferenceControlPanel {...props} /> : <LegacyControlPanel {...props} />;
}
