import {useEffect, useState} from "react";
import {TwinIcon} from "./TwinIcon";

export type SupportedEvent = {
  type: string;
  label: string;
  description: string;
  target: string;
  targetLabel: string;
  durationS: number;
  parameters?: Record<string, number | string | boolean>;
  severity: "warning" | "danger";
};

export const supportedEvents: SupportedEvent[] = [
  {type: "roadwork", label: "施工占道", description: "使用场景中预配置的下游车道实施占道", target: "configured_downstream_lane", targetLabel: "场景预配置下游车道", durationS: 60, severity: "warning"},
  {type: "incident", label: "交通事故", description: "在真实瓶颈位置注入事故车辆占道", target: "downstream_bottleneck", targetLabel: "场景瓶颈路段", durationS: 60, severity: "danger"},
  {type: "large_event", label: "大型活动", description: "触发项目已配置的北部活动散场需求", target: "north_activity", targetLabel: "北部活动影响区", durationS: 120, parameters: {flow_multiplier: 2.5}, severity: "warning"},
  {type: "flow_surge", label: "流量突增", description: "按现有实验控制器增加局部交通需求", target: "network_local", targetLabel: "场景局部路网", durationS: 90, parameters: {flow_multiplier: 1.8}, severity: "warning"},
  {type: "communication_latency", label: "通信延迟", description: "向云边通信仿真器注入端到端延迟", target: "cloud_edge", targetLabel: "云—边通信链路", durationS: 30, parameters: {latency_ms: 500}, severity: "warning"},
  {type: "packet_loss", label: "RSU 通信异常", description: "向现有通信链路注入 10% 丢包", target: "cloud_edge", targetLabel: "云—边通信链路", durationS: 30, parameters: {packet_loss_rate: .1}, severity: "warning"},
  {type: "cloud_offline", label: "云端离线", description: "触发现有边缘自治降级与恢复逻辑", target: "cloud", targetLabel: "云端控制服务", durationS: 30, severity: "danger"},
];

type Props = {
  event: SupportedEvent | null;
  disabled: boolean;
  onClose: () => void;
  onConfirm: (event: SupportedEvent, durationS: number) => void;
};

export function EventDrawer({event, disabled, onClose, onConfirm}: Props) {
  const [durationS, setDurationS] = useState(30);
  useEffect(() => { if (event) setDurationS(event.durationS); }, [event]);
  if (!event) return null;
  return (
    <div className="event-drawer-backdrop" onMouseDown={(mouseEvent) => { if (mouseEvent.target === mouseEvent.currentTarget) onClose(); }}>
      <section aria-labelledby="event-drawer-title" aria-modal="true" className="event-drawer" role="dialog">
        <header>
          <div className={`drawer-event-mark ${event.severity}`}><TwinIcon name="warning" /></div>
          <div><span>扰动事件配置</span><h2 id="event-drawer-title">{event.label}</h2></div>
          <button aria-label="关闭事件配置" className="icon-button" onClick={onClose}><TwinIcon name="close" /></button>
        </header>
        <p className="drawer-description">{event.description}</p>
        <div className="drawer-form">
          <label>作用对象<input disabled readOnly value={event.targetLabel} /></label>
          <label>持续时间
            <select onChange={(changeEvent) => setDurationS(Number(changeEvent.target.value))} value={durationS}>
              {[30, 60, 90, 120, 300, 600].map((value) => <option key={value} value={value}>{value} 秒</option>)}
            </select>
          </label>
          {event.parameters && <div className="drawer-parameters"><span>真实控制参数</span>{Object.entries(event.parameters).map(([key, value]) => <b key={key}>{key}<em>{String(value)}</em></b>)}</div>}
        </div>
        <aside><TwinIcon name="activity" /><p>事件将在确认后发送到现有 FastAPI 故障接口，并由实验控制器作用于 SUMO/通信仿真；前端不生成交通结果。</p></aside>
        <footer><button onClick={onClose}>取消</button><button className={event.severity === "danger" ? "danger-action" : "primary-action"} disabled={disabled} onClick={() => onConfirm(event, durationS)}>确认注入</button></footer>
      </section>
    </div>
  );
}
