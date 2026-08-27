import {useMemo, useState} from "react";
import type {RealtimeSnapshot, ScenarioProfile} from "../../types";
import {algorithmOptionLabel, sortAlgorithms} from "../../algorithmLabels";
import {supportedEvents} from "./EventDrawer";
import {AlgorithmComparisonPanel} from "./AlgorithmComparisonDock";
import {layerGroups, type TwinControlPanelProps} from "./TwinControlPanel";
import {TwinIcon, type TwinIconName} from "./TwinIcon";

type ToolKey = "scene" | "traffic" | "signal" | "event" | "layer";
type SignalTab = "control" | "phase" | "detector";

const tools: Array<{key: ToolKey; label: string; title: string; icon: TwinIconName}> = [
  {key: "scene", label: "场景", title: "仿真场景", icon: "map"},
  {key: "traffic", label: "态势", title: "运行态势", icon: "activity"},
  {key: "signal", label: "信控", title: "信号控制", icon: "signal"},
  {key: "event", label: "事件", title: "扰动事件", icon: "warning"},
  {key: "layer", label: "图层", title: "场景图层", icon: "layers"},
];

function metric(value: number | undefined, digits = 0): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "--";
}

function seriesPoints(history: RealtimeSnapshot[], selector: (item: RealtimeSnapshot) => number | undefined): string {
  const values = history.map(selector).filter((value): value is number => typeof value === "number" && Number.isFinite(value)).slice(-28);
  if (!values.length) return "";
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const range = Math.max(maximum - minimum, maximum * .08, 1);
  return values.map((value, index) => {
    const x = values.length === 1 ? 50 : 3 + index / (values.length - 1) * 94;
    const y = 32 - (value - minimum) / range * 27;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
}

function directionLabel(direction: string): string {
  const value = direction.toLowerCase();
  if (value.includes("north") || value === "n" || direction.includes("北")) return "北向";
  if (value.includes("east") || value === "e" || direction.includes("东")) return "东向";
  if (value.includes("south") || value === "s" || direction.includes("南")) return "南向";
  if (value.includes("west") || value === "w" || direction.includes("西")) return "西向";
  return direction.slice(0, 3) || "进口";
}

function SignalDiagram({phaseId, phaseState}: {phaseId?: string; phaseState?: string}) {
  const hasLivePhase = Boolean(phaseId || phaseState);
  return <svg aria-label="当前路口信号相位图" className="reference-phase-diagram" role="img" viewBox="0 0 220 74">
    <path className="phase-road" d="M0 27h83V0h54v27h83v20h-83v27H83V47H0Z" />
    <path className="phase-lane" d="M0 34h83M137 34h83M101 0v27M101 47v27M119 0v27M119 47v27M0 41h83M137 41h83" />
    <path className={hasLivePhase ? "phase-flow active" : "phase-flow"} d="M110 66V47m0-20V8" />
    <path className={hasLivePhase ? "phase-flow secondary" : "phase-flow"} d="M74 37H18m184 0h-56" />
    <circle className={hasLivePhase ? "phase-lamp green" : "phase-lamp"} cx="76" cy="52" r="3" />
    <circle className="phase-lamp red" cx="144" cy="22" r="3" />
    <text x="7" y="14">W</text><text x="204" y="14">E</text><text x="90" y="10">N</text><text x="90" y="70">S</text>
    <text className="phase-id" x="110" y="43">{phaseId || "--"}</text>
  </svg>;
}

function QueueBars({lanes}: {lanes: NonNullable<NonNullable<RealtimeSnapshot["intersections"]>[number]>["lane_states"]}) {
  const grouped = new Map<string, number>();
  lanes.forEach((lane) => {
    const label = directionLabel(lane.direction);
    grouped.set(label, (grouped.get(label) ?? 0) + lane.queue_vehicle_count);
  });
  const values = [...grouped.entries()].slice(0, 6);
  const visible = values.length ? values : [["北向", 0], ["东向", 0], ["南向", 0], ["西向", 0]];
  const maximum = Math.max(...visible.map(([, value]) => Number(value)), 1);
  return <div aria-label="进口道排队柱状图" className="reference-bar-chart" role="img">
    <div className="reference-chart-grid" aria-hidden="true"><i /><i /><i /></div>
    {visible.map(([label, value]) => <div key={String(label)}><span style={{height: `${Math.max(4, Number(value) / maximum * 92)}%`}} /><b>{label}</b></div>)}
  </div>;
}

function TrendChart({history}: {history: RealtimeSnapshot[]}) {
  const queue = seriesPoints(history, (item) => item.total_queue_vehicles);
  const speed = seriesPoints(history, (item) => item.mean_speed_m_s === undefined ? undefined : item.mean_speed_m_s * 3.6);
  return <div className="reference-trend-wrap">
    <svg aria-label="区域排队与速度趋势图" className="reference-trend-chart" preserveAspectRatio="none" role="img" viewBox="0 0 100 36">
      <path className="chart-grid-line" d="M3 5h94M3 14h94M3 23h94M3 32h94" />
      {queue && <polyline className="queue-line" points={queue} />}
      {speed && <polyline className="speed-line" points={speed} />}
    </svg>
    {!queue && !speed && <span>等待实时采样</span>}
    <div className="reference-chart-legend"><i className="queue" />排队<i className="speed" />速度</div>
  </div>;
}

function PanelSection({title, value, children}: {title: string; value?: string; children: React.ReactNode}) {
  return <section className="reference-data-section"><header><span>{title}</span>{value && <b>{value}</b>}</header>{children}</section>;
}

export function ReferenceControlPanel(props: TwinControlPanelProps) {
  const [activeTool, setActiveTool] = useState<ToolKey>("traffic");
  const [signalTab, setSignalTab] = useState<SignalTab>("control");
  const currentScenario = props.scenarios.find((item) => item.scenario_id === props.scenarioId);
  const profiles: ScenarioProfile[] = useMemo(() => [{code: "BASE", name: "基础配置", flow_multiplier: 1, communication_profile: "configured", disturbance_types: []}, ...(currentScenario?.profiles ?? [])], [currentScenario]);
  const scenarioNameCounts = useMemo(() => props.scenarios.reduce((counts, item) => counts.set(item.display_name, (counts.get(item.display_name) ?? 0) + 1), new Map<string, number>()), [props.scenarios]);
  const selectedRealtime = props.snapshot.intersections?.find((item) => item.intersection_id === props.selectedIntersectionId);
  const queueVehicles = selectedRealtime?.queue_vehicles ?? props.snapshot.total_queue_vehicles;
  const speedMps = selectedRealtime?.mean_speed_m_s ?? props.snapshot.mean_speed_m_s;
  const speedKmh = speedMps === undefined ? undefined : speedMps * 3.6;
  const phaseId = selectedRealtime?.phase_id;
  const phaseState = selectedRealtime?.phase_state;
  const currentTool = tools.find((item) => item.key === activeTool) ?? tools[1];
  const laneCount = selectedRealtime?.lane_states.reduce((sum, lane) => sum + lane.vehicle_count, 0);

  if (props.collapsed) return <aside className="control-panel collapsed reference-control-collapsed"><button aria-label="展开控制面板" className="panel-collapse-button" onClick={props.onCollapsed}><TwinIcon name="settings" /><TwinIcon className="chevron" name="chevron" /></button></aside>;

  const intersectionField = <label className="reference-field"><span>控制路口</span><select aria-label="选择三维监测路口" onChange={(event) => props.onIntersectionChange(event.target.value || null)} value={props.selectedIntersectionId ?? ""}><option value="">B01 · 参考展示区</option>{props.nodes.map((item) => <option key={item.intersection_id} value={item.intersection_id}>{item.display_id} · {item.display_name}</option>)}</select></label>;

  const algorithmSelector = <PanelSection title={props.comparisonMode ? "候选控制算法" : "控制方案"} value={phaseState || "待机"}>
    <div className="reference-algorithm-grid">{sortAlgorithms(props.algorithms).map((item) => {
      const [code, name = algorithmOptionLabel(item.name)] = algorithmOptionLabel(item.name).split(" · ");
      return <button className={props.algorithm === item.name ? "active" : ""} disabled={props.algorithmDisabled} key={item.name} onClick={() => props.onAlgorithmChange(item.name)} title={algorithmOptionLabel(item.name)}><i /><span><b>{code}</b>{name}</span></button>;
    })}</div>
  </PanelSection>;

  const metrics = <div className="reference-metric-matrix">
    <div><span>当前排队</span><b>{metric(queueVehicles)}<small> 辆</small></b></div>
    <div><span>平均速度</span><b>{metric(speedKmh, 1)}<small> km/h</small></b></div>
    <div><span>进口车辆</span><b>{metric(laneCount)}<small> 辆</small></b></div>
    <div><span>完成出行</span><b>{metric(props.snapshot.completed_trips)}<small> 辆</small></b></div>
    <div><span>行人等待</span><b>{metric(selectedRealtime?.pedestrian_waiting_count)}<small> 人</small></b></div>
    <div><span>非机排队</span><b>{metric(selectedRealtime?.bicycle_queue_count)}<small> 辆</small></b></div>
  </div>;

  const signalPane = <>
    {intersectionField}
    <label className="reference-field"><span>运行工况</span><select aria-label="信号控制运行工况" disabled={props.configurationDisabled} onChange={(event) => props.onProfileChange(event.target.value)} value={props.scenarioProfile}>{profiles.map((item) => <option key={item.code} value={item.code}>{item.code} · {item.name}</option>)}</select></label>
    <nav aria-label="信号控制视图" className="reference-subtabs">
      {[{key: "control", label: "运行控制"}, {key: "phase", label: "相位状态"}, {key: "detector", label: "检测数据"}].map((item) => <button aria-pressed={signalTab === item.key} className={signalTab === item.key ? "active" : ""} key={item.key} onClick={() => setSignalTab(item.key as SignalTab)}>{item.label}</button>)}
    </nav>
    {signalTab === "control" && <>
      {algorithmSelector}
      {metrics}
      <PanelSection title="路口信号状态" value={phaseId || "--"}><SignalDiagram phaseId={phaseId} phaseState={phaseState} /></PanelSection>
      <PanelSection title="进口道排队"><QueueBars lanes={selectedRealtime?.lane_states ?? []} /></PanelSection>
      <PanelSection title="区域运行趋势"><TrendChart history={props.history} /></PanelSection>
    </>}
    {signalTab === "phase" && <>
      <PanelSection title="实时相位" value={phaseState || "等待数据"}><SignalDiagram phaseId={phaseId} phaseState={phaseState} /></PanelSection>
      {metrics}
      <div className="reference-phase-ledger">
        <div><span>控制模式</span><b>{selectedRealtime?.control_mode || "--"}</b></div>
        <div><span>拥堵指数</span><b>{metric(selectedRealtime?.congestion_level, 2)}</b></div>
        <div><span>溢出风险</span><b>{metric(selectedRealtime?.spillback_risk, 2)}</b></div>
        <div><span>事件状态</span><b>{selectedRealtime?.incident_state || "正常"}</b></div>
      </div>
      <PanelSection title="相位周期趋势"><TrendChart history={props.history} /></PanelSection>
    </>}
    {signalTab === "detector" && <>
      {metrics}
      <PanelSection title="进口道检测"><QueueBars lanes={selectedRealtime?.lane_states ?? []} /></PanelSection>
      <div className="reference-detector-table"><header><span>进口方向</span><span>车辆</span><span>排队</span><span>占有率</span></header>{(selectedRealtime?.lane_states ?? []).slice(0, 5).map((lane) => <div key={lane.lane_id}><span>{directionLabel(lane.direction)}</span><b>{lane.vehicle_count}</b><b>{lane.queue_vehicle_count}</b><b>{metric(lane.occupancy * 100, 0)}%</b></div>)}{!selectedRealtime?.lane_states.length && <p>等待检测器数据</p>}</div>
      <PanelSection title="检测数据趋势"><TrendChart history={props.history} /></PanelSection>
    </>}
  </>;

  const trafficPane = <>{intersectionField}{props.comparisonMode ? <>{algorithmSelector}<AlgorithmComparisonPanel onRoleChange={props.onComparisonRoleChange} paired={props.pairedDigitalTwin} selectedRole={props.comparisonRole} /></> : <>{metrics}<PanelSection title="进口道排队"><QueueBars lanes={selectedRealtime?.lane_states ?? []} /></PanelSection><PanelSection title="区域排队与速度"><TrendChart history={props.history} /></PanelSection><div className="reference-phase-ledger"><div><span>区域最大排队</span><b>{metric(props.snapshot.max_queue_vehicles)} 辆</b></div><div><span>累计通行</span><b>{metric(props.snapshot.throughput_vehicles)} 辆</b></div><div><span>下游占有率</span><b>{metric(props.snapshot.downstream_occupancy === undefined ? undefined : props.snapshot.downstream_occupancy * 100, 0)}%</b></div><div><span>当前状态</span><b>{props.snapshot.status || "idle"}</b></div></div></>}</>;

  const scenePane = <><label className="reference-field"><span>仿真场景</span><select aria-label="仿真场景" disabled={props.configurationDisabled} onChange={(event) => props.onScenarioChange(event.target.value)} value={props.scenarioId}>{props.scenarios.filter((item) => item.runnable).map((item) => <option key={item.scenario_id} value={item.scenario_id}>{item.display_name}{(scenarioNameCounts.get(item.display_name) ?? 0) > 1 ? ` · ${item.scenario_id}` : ""}</option>)}</select></label><label className="reference-field"><span>仿真工况</span><select aria-label="仿真工况" disabled={props.configurationDisabled} onChange={(event) => props.onProfileChange(event.target.value)} value={props.scenarioProfile}>{profiles.map((item) => <option key={item.code} value={item.code}>{item.code} · {item.name}</option>)}</select></label><div className="reference-compact-fields"><label><span>随机种子</span><input aria-label="随机种子" disabled={props.configurationDisabled} min={0} onChange={(event) => props.onSeedChange(Number(event.target.value))} type="number" value={props.seed} /></label><label><span>仿真时长</span><select aria-label="仿真时长" disabled={props.configurationDisabled} onChange={(event) => props.onDurationChange(Number(event.target.value))} value={props.durationS}>{[...new Set([300, 900, 1800, 3600, props.durationS])].sort((left, right) => left - right).map((value) => <option key={value} value={value}>{value}s</option>)}</select></label></div>{props.configurationDisabled && <p className="reference-lock-note"><TwinIcon name="lock" />实验配置已锁定</p>}<div className="reference-scene-facts"><div><b>{props.scene?.metadata.counts.trafficLights ?? props.scene?.trafficLights.length ?? "--"}</b><span>信号路口</span></div><div><b>{props.scene?.metadata.counts.lanes ?? props.scene?.lanes.length ?? "--"}</b><span>SUMO 车道</span></div><div><b>{props.scene?.buildings.length ?? "--"}</b><span>建筑实体</span></div><div><b>{props.nodes.length || "--"}</b><span>控制节点</span></div></div><PanelSection title="场景运行趋势"><TrendChart history={props.history} /></PanelSection></>;

  const eventPane = <><div className="reference-event-status"><span>活动事件</span><b>{props.activeEventCount}</b><button disabled={props.eventsDisabled || !props.activeEventCount} onClick={props.onClearEvents}>全部清除</button></div><div className="reference-event-grid">{supportedEvents.map((item) => <button disabled={props.eventsDisabled} key={item.type} onClick={() => props.onEventOpen(item)}><TwinIcon name="warning" /><span><b>{item.label}</b><small>{item.targetLabel}</small></span></button>)}</div>{props.eventsDisabled && <p className="reference-empty-note">启动实时实验后可注入扰动事件</p>}</>;

  const layerPane = <div className="reference-layer-groups">{layerGroups.map((group) => <section key={group.label}><header>{group.label}</header>{group.items.map(([key, label]) => <label className="reference-switch" key={key}><span>{label}</span><input checked={props.layers[key]} onChange={() => props.onLayerChange(key)} type="checkbox"/><i /></label>)}</section>)}</div>;

  return <aside className="control-panel floating-panel has-live reference-control-panel">
    <nav aria-label="三维控制工具" className="reference-tool-rail">
      <div className="reference-rail-mark"><TwinIcon name="focus" /></div>
      {tools.map((item) => <button aria-label={item.title} aria-pressed={activeTool === item.key} className={activeTool === item.key ? "active" : ""} key={item.key} onClick={() => setActiveTool(item.key)} title={item.title}><TwinIcon name={item.icon} /><span>{item.label}</span>{item.key === "event" && props.activeEventCount > 0 && <em>{props.activeEventCount}</em>}</button>)}
      <button aria-label="收起控制面板" className="reference-collapse" onClick={props.onCollapsed} title="收起控制面板"><TwinIcon name="chevron" /><span>收起</span></button>
    </nav>
    <section className="reference-panel-main">
      <header className="reference-panel-header"><div><span>TRAFFIC SIMULATION</span><strong>{currentTool.title}</strong></div><i className={["running", "paused"].includes(props.snapshot.status) ? "online" : ""} title={props.snapshot.status || "idle"} /></header>
      <div className="reference-panel-scroll">
        <div hidden={activeTool !== "scene"}>{scenePane}</div>
        <div hidden={activeTool !== "traffic"}>{trafficPane}</div>
        <div hidden={activeTool !== "signal"}>{signalPane}</div>
        <div hidden={activeTool !== "event"}>{eventPane}</div>
        <div hidden={activeTool !== "layer"}>{layerPane}</div>
      </div>
    </section>
  </aside>;
}
