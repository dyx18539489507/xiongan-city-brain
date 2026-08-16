import {useMemo, useState} from "react";
import type {LayerKey, LayerVisibility} from "../../2d/model";
import type {StaticSceneDocument} from "../../3d/scene/types";
import type {Algorithm, Scenario, ScenarioProfile} from "../../types";
import {supportedEvents, type SupportedEvent} from "./EventDrawer";
import {TwinIcon} from "./TwinIcon";

type Props = {
  collapsed: boolean;
  scene: StaticSceneDocument | null;
  scenarios: Scenario[];
  algorithms: Algorithm[];
  scenarioId: string;
  scenarioProfile: string;
  algorithm: string;
  seed: number;
  durationS: number;
  layers: LayerVisibility;
  activeEventCount: number;
  eventsDisabled: boolean;
  onCollapsed: () => void;
  onProfileChange: (value: string) => void;
  onAlgorithmChange: (value: string) => void;
  onSeedChange: (value: number) => void;
  onDurationChange: (value: number) => void;
  onLayerChange: (key: LayerKey) => void;
  onEventOpen: (event: SupportedEvent) => void;
  onClearEvents: () => void;
};

type AccordionKey = "scene" | "algorithm" | "event" | "layer";
const layerGroups: Array<{label: string; items: Array<[LayerKey, string]>}> = [
  {label: "城市空间", items: [["baseMap", "基础路网"], ["buildings", "建筑地块"], ["roadMarkings", "车道标线"], ["corridor", "核心走廊"], ["rsu", "路侧设备"]]},
  {label: "交通主体", items: [["vehicles", "小汽车"], ["buses", "公交车"], ["trucks", "货车"], ["bicycles", "非机动车"], ["pedestrians", "行人"]]},
  {label: "运行态势", items: [["signals", "信号灯"], ["trafficState", "交通状态"], ["queues", "排队长度"], ["trails", "车辆轨迹"], ["algorithm", "算法控制"], ["events", "扰动事件"], ["labels", "路口标注"]]},
];

const algorithmDescriptions: Record<string, string> = {
  "fixed-time": "固定配时基线控制",
  "actuated": "基于检测状态的感应控制",
  "max-pressure": "路口最大压力控制",
  "coordinated-max-pressure": "核心走廊云边协同最大压力",
};

export function TwinControlPanel(props: Props) {
  const [open, setOpen] = useState<AccordionKey | null>("scene");
  const currentScenario = props.scenarios.find((item) => item.scenario_id === props.scenarioId);
  const profiles: ScenarioProfile[] = useMemo(() => [{code: "BASE", name: "基础配置", flow_multiplier: 1, communication_profile: "configured", disturbance_types: []}, ...(currentScenario?.profiles ?? [])], [currentScenario]);
  const toggle = (key: AccordionKey) => setOpen((current) => current === key ? null : key);
  if (props.collapsed) return <aside className="control-panel collapsed"><button aria-label="展开控制面板" className="panel-collapse-button" onClick={props.onCollapsed}><TwinIcon name="settings" /><TwinIcon className="chevron" name="chevron" /></button></aside>;
  return <aside className="control-panel floating-panel">
    <header className="floating-panel-header"><div><span>CONTROL</span><h2>协同管控</h2></div><button aria-label="收起控制面板" className="icon-button collapse-left" onClick={props.onCollapsed}><TwinIcon name="chevron" /></button></header>
    <div className="accordion-stack">
      <section className={open === "scene" ? "open" : ""}><button aria-expanded={open === "scene"} className="accordion-trigger" onClick={() => toggle("scene")}><span><TwinIcon name="map" />场景</span><TwinIcon name="chevron" /></button>{open === "scene" && <div className="accordion-content">
        <label>仿真工况<select onChange={(event) => props.onProfileChange(event.target.value)} value={props.scenarioProfile}>{profiles.map((item) => <option key={item.code} value={item.code}>{item.code} · {item.name}</option>)}</select></label>
        <div className="compact-fields"><label>随机种子<input min={0} onChange={(event) => props.onSeedChange(Number(event.target.value))} type="number" value={props.seed} /></label><label>仿真时长<select onChange={(event) => props.onDurationChange(Number(event.target.value))} value={props.durationS}>{[300, 900, 1800, 3600].map((value) => <option key={value} value={value}>{value}s</option>)}</select></label></div>
        {props.scene && <div className="scene-facts"><b>{props.scene.metadata.counts.trafficLights ?? props.scene.trafficLights.length}<span>信号路口</span></b><b>{props.scene.metadata.counts.lanes ?? props.scene.lanes.length}<span>SUMO 车道</span></b></div>}
      </div>}</section>
      <section className={open === "algorithm" ? "open" : ""}><button aria-expanded={open === "algorithm"} className="accordion-trigger" onClick={() => toggle("algorithm")}><span><TwinIcon name="activity" />算法</span><TwinIcon name="chevron" /></button>{open === "algorithm" && <div className="accordion-content algorithm-list">{props.algorithms.filter((item) => item.name !== "predictive-controller-placeholder").map((item) => <button className={props.algorithm === item.name ? "active" : ""} key={item.name} onClick={() => props.onAlgorithmChange(item.name)}><i /><span><strong>{item.name}</strong><small>{algorithmDescriptions[item.name] ?? `版本 ${item.version}`}</small></span></button>)}<p>当前选择将在下一次真实实验启动时生效。</p></div>}</section>
      <section className={open === "event" ? "open" : ""}><button aria-expanded={open === "event"} className="accordion-trigger" onClick={() => toggle("event")}><span><TwinIcon name="warning" />事件</span><em>{props.activeEventCount}</em><TwinIcon name="chevron" /></button>{open === "event" && <div className="accordion-content event-grid">{supportedEvents.map((item) => <button disabled={props.eventsDisabled} key={item.type} onClick={() => props.onEventOpen(item)}><TwinIcon name="warning" /><span>{item.label}<small>{item.targetLabel}</small></span></button>)}<button className="clear-events" disabled={!props.activeEventCount} onClick={props.onClearEvents}>清除活动事件</button>{props.eventsDisabled && <p>启动实时实验后可配置并注入扰动。</p>}</div>}</section>
      <section className={open === "layer" ? "open" : ""}><button aria-expanded={open === "layer"} className="accordion-trigger" onClick={() => toggle("layer")}><span><TwinIcon name="layers" />图层</span><TwinIcon name="chevron" /></button>{open === "layer" && <div className="accordion-content layer-groups">{layerGroups.map((group) => <div key={group.label}><p>{group.label}</p>{group.items.map(([key, label]) => <label className="twin-switch" key={key}><span>{label}</span><input checked={props.layers[key]} onChange={() => props.onLayerChange(key)} type="checkbox"/><i /></label>)}</div>)}</div>}</section>
    </div>
  </aside>;
}
