import type {MapSelection} from "../../2d/model";
import type {DigitalTwinState} from "../../3d/network/digitalTwinTypes";
import type {StaticSceneDocument} from "../../3d/scene/types";
import type {IntersectionNode, RealtimeSnapshot} from "../../types";
import {TwinIcon} from "./TwinIcon";

type Props = {scene: StaticSceneDocument | null; state: DigitalTwinState; snapshot: RealtimeSnapshot; nodes: IntersectionNode[]; selection: MapSelection | null};
type Metric = [label: string, value: unknown, unit?: string, digits?: number];

function present(value: unknown, unit = "", digits = 1): string {
  if (typeof value === "number" && Number.isFinite(value)) return `${value.toFixed(digits)}${unit}`;
  if (typeof value === "string" && value) return value;
  if (typeof value === "boolean") return value ? "是" : "否";
  return "—";
}

function MetricList({items}: {items: Metric[]}) {
  return <dl className="twin-metric-list">{items.map(([label, value, unit, digits]) => <div key={label}><dt>{label}</dt><dd>{present(value, unit, digits)}</dd></div>)}</dl>;
}

function EmptyInspector() {
  return <div className="inspector-empty"><span><TwinIcon name="focus" /></span><strong>选择交通对象</strong><p>点击路口、道路或交通主体，查看来自 SUMO 的实时状态。</p></div>;
}

export function TwinInspector({scene, state, snapshot, nodes, selection}: Props) {
  if (!selection) return <EmptyInspector />;

  if (selection.kind === "junction") {
    const junction = scene?.junctions.find((item) => item.sumoJunctionId === selection.id);
    const node = nodes.find((item) => item.intersection_id === selection.id);
    const realtime = snapshot.intersections?.find((item) => item.intersection_id === selection.id);
    const definition = scene?.trafficLights.find((item) => item.controlledJunctionId === selection.id);
    const light = state.trafficLights.get(definition?.sumoTlsId ?? selection.id) ?? state.trafficLights.get(selection.id);
    const queueM = realtime?.lane_states.reduce((sum, lane) => sum + lane.queue_length_m, 0);
    const inbound = realtime?.lane_states.reduce((sum, lane) => sum + lane.vehicle_count, 0);
    const signal = light ? (/[Gg]/.test(light.state) ? "green" : /[Yy]/.test(light.state) ? "yellow" : "red") : "off";
    return <div className="twin-inspector-content">
      <header><span>受控路口</span><h3>{junction?.displayName ?? node?.display_name ?? junction?.displayId ?? "路口"}</h3><small>{junction?.displayId ?? node?.display_id ?? "SUMO 控制节点"}</small></header>
      <div className="signal-summary"><span className={`signal-lamp ${signal}`} /><div><small>当前相位</small><b>{light?.phaseIndex ?? realtime?.phase_id ?? "—"}</b></div><div><small>相位剩余</small><b>{light ? `${light.remainingS.toFixed(1)}s` : "—"}</b></div></div>
      <MetricList items={[["进口车辆", inbound, " 辆", 0], ["当前排队", realtime?.queue_vehicles, " 辆", 0], ["排队长度", queueM, " m", 0], ["平均速度", realtime?.mean_speed_m_s !== undefined ? realtime.mean_speed_m_s * 3.6 : undefined, " km/h", 1], ["拥堵指数", realtime?.congestion_level, "", 2], ["溢出风险", realtime?.spillback_risk, "", 2], ["控制策略", realtime?.control_mode], ["事件状态", realtime?.incident_state]]} />
    </div>;
  }

  if (selection.kind === "edge") {
    const edge = scene?.edges.find((item) => item.sumoEdgeId === selection.id);
    const road = edge?.roadId ? scene?.roads?.find((item) => item.sceneId === edge.roadId) : null;
    const moving = [...state.vehicles.values(), ...state.bicycles.values()].filter((item) => item.edgeId === selection.id);
    const meanSpeed = moving.length ? moving.reduce((sum, item) => sum + item.speed, 0) / moving.length : undefined;
    const waiting = moving.filter((item) => item.status === "waiting").length;
    const laneMetrics = (snapshot.intersections ?? []).flatMap((item) => item.lane_states).filter((item) => edge?.laneIds.includes(item.lane_id));
    const queueM = laneMetrics.reduce((sum, item) => sum + item.queue_length_m, 0);
    const occupancy = laneMetrics.length ? laneMetrics.reduce((sum, item) => sum + item.occupancy, 0) / laneMetrics.length : undefined;
    return <div className="twin-inspector-content">
      <header><span>道路运行状态</span><h3>{road?.name ?? edge?.roadType ?? "SUMO 道路"}</h3><small>{road?.roadClass ?? "路网路段"}</small></header>
      <MetricList items={[["长度", edge?.lengthM, " m", 0], ["车道数", edge?.laneIds.length, "", 0], ["当前主体", moving.length, "", 0], ["平均速度", meanSpeed !== undefined ? meanSpeed * 3.6 : undefined, " km/h", 1], ["排队主体", waiting, "", 0], ["排队长度", queueM || undefined, " m", 0], ["平均占有率", occupancy !== undefined ? occupancy * 100 : undefined, "%", 1]]} />
    </div>;
  }

  if (selection.kind === "event") {
    const event = state.events.find((item) => item.eventId === selection.id);
    return <div className="twin-inspector-content event"><header><span>仿真事件</span><h3>{event?.event ?? "事件已结束"}</h3><small>来自实验事件流</small></header><p className="event-detail-copy">{event?.detail ?? "事件已不在当前活动窗口中。"}</p><MetricList items={[["发生时间", event?.simulationTime, " s", 1]]} /></div>;
  }

  const entity = selection.kind === "pedestrian" ? state.pedestrians.get(selection.id) : selection.kind === "bicycle" ? state.bicycles.get(selection.id) : state.vehicles.get(selection.id);
  if (!entity) return <div className="inspector-empty"><span><TwinIcon name="route" /></span><strong>主体已离开路网</strong><p>SUMO 已移除该交通主体，请重新选择。</p></div>;
  const edge = scene?.edges.find((item) => item.sumoEdgeId === entity.edgeId);
  const road = edge?.roadId ? scene?.roads?.find((item) => item.sceneId === edge.roadId) : null;
  const kind = selection.kind === "pedestrian" ? "行人" : selection.kind === "bicycle" ? "非机动车" : "机动车";
  return <div className="twin-inspector-content">
    <header><span>{kind}</span><h3>{entity.id}</h3><small>SUMO 实时主体</small></header>
    <div className="entity-hero"><strong>{(entity.speed * 3.6).toFixed(1)}</strong><span>km/h</span><i className={entity.status === "waiting" ? "waiting" : "moving"}>{entity.status === "waiting" ? "等待" : "行驶"}</i></div>
    <MetricList items={[["类型", "vehicleClass" in entity ? entity.vehicleClass : entity.type], ["当前道路", road?.name ?? edge?.roadType ?? "—"], ["方向角", entity.angle, "°", 0], ...( "acceleration" in entity ? [["加速度", entity.acceleration, " m/s²", 1] as Metric] : []), ...( "routeId" in entity ? [["路线", entity.routeId] as Metric] : []), ...( "crossingId" in entity ? [["过街设施", entity.crossingId ? "正在过街" : "—"] as Metric] : [])]} />
  </div>;
}
