import {useEffect, useMemo, useState} from "react";
import {selectOperationalTimelineEvents} from "../../2d/timeline";
import type {RealtimeSnapshot, TimelineEvent} from "../../types";
import {TrendChart} from "../TrendChart";
import {TwinIcon} from "./TwinIcon";

type SparkMetric = {key: string; label: string; unit: string; values: number[]; current: string; color: string};
export type RealComparison = {baselineLabel: string; candidateLabel: string; baseline?: Record<string, number | string | boolean | null>; candidate?: Record<string, number | string | boolean | null>};

type Props = {
  history: RealtimeSnapshot[];
  events: TimelineEvent[];
  simulationTimeS: number;
  durationS: number;
  sourceMode: "live" | "replay";
  replayLoaded: boolean;
  onSeek: (value: number) => void;
  coreIntersectionIds: string[];
  comparison: RealComparison | null;
};

function valueSeries(history: RealtimeSnapshot[], getter: (item: RealtimeSnapshot) => number | undefined): number[] {
  return history.map(getter).filter((value): value is number => typeof value === "number" && Number.isFinite(value)).slice(-60);
}

function Sparkline({values, color}: {values: number[]; color: string}) {
  if (values.length < 2) return <div className="spark-empty">等待采样</div>;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = Math.max(.001, max - min);
  const points = values.map((value, index) => `${(index / (values.length - 1)) * 100},${28 - ((value - min) / range) * 23}`).join(" ");
  return <svg aria-hidden="true" className="sparkline" preserveAspectRatio="none" viewBox="0 0 100 32"><defs><linearGradient id={`spark-${color.replace(/[^a-z0-9]/gi, "")}`} x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor={color} stopOpacity=".28"/><stop offset="1" stopColor={color} stopOpacity="0"/></linearGradient></defs><polygon fill={`url(#spark-${color.replace(/[^a-z0-9]/gi, "")})`} points={`0,32 ${points} 100,32`} /><polyline fill="none" points={points} stroke={color} strokeWidth="1.8" vectorEffect="non-scaling-stroke" /></svg>;
}

function eventPosition(event: TimelineEvent, duration: number): number {
  return Math.max(0, Math.min(100, ((event.simulationTime ?? 0) / Math.max(1, duration)) * 100));
}

export function TrendDock({history, events, simulationTimeS, durationS, sourceMode, replayLoaded, onSeek, coreIntersectionIds, comparison}: Props) {
  const [expanded, setExpanded] = useState(false);
  const [analysisReady, setAnalysisReady] = useState(false);
  useEffect(() => {
    if (!expanded) {
      setAnalysisReady(false);
      return;
    }
    const timer = window.setTimeout(() => setAnalysisReady(true), 320);
    return () => window.clearTimeout(timer);
  }, [expanded]);
  const metrics = useMemo<SparkMetric[]>(() => {
    const speed = valueSeries(history, (item) => item.mean_speed_m_s === undefined ? undefined : item.mean_speed_m_s * 3.6);
    const queue = valueSeries(history, (item) => item.total_queue_m ?? item.total_queue_vehicles);
    const delay = valueSeries(history, (item) => item.waiting_time_s);
    const throughput = valueSeries(history, (item) => item.throughput_vehicles ?? item.completed_trips);
    return [
      {key: "speed", label: "平均速度", unit: "km/h", values: speed, current: speed.at(-1)?.toFixed(1) ?? "—", color: "var(--traffic-free)"},
      {key: "queue", label: "区域排队", unit: "m", values: queue, current: queue.at(-1)?.toFixed(0) ?? "—", color: "var(--traffic-congested)"},
      {key: "delay", label: "平均等待", unit: "s", values: delay, current: delay.at(-1)?.toFixed(1) ?? "—", color: "var(--warning)"},
      {key: "throughput", label: "累计通行", unit: "辆", values: throughput, current: throughput.at(-1)?.toFixed(0) ?? "—", color: "var(--cloud)"},
    ];
  }, [history]);
  const timelineDuration = Math.max(durationS, simulationTimeS, 1);
  const currentPercent = Math.max(0, Math.min(100, simulationTimeS / timelineDuration * 100));
  const displayedEvents = useMemo(() => selectOperationalTimelineEvents(events), [events]);
  return <section className={`trend-dock ${expanded ? "expanded" : ""}`}>
    <button aria-expanded={expanded} className="trend-expand" onClick={() => setExpanded((value) => !value)}><TwinIcon name={expanded ? "close" : "expand"} /><span>{expanded ? "收起分析" : "展开分析"}</span></button>
    <div className="spark-grid">{metrics.map((metric) => <article key={metric.key}><header><span>{metric.label}</span><strong>{metric.current}<small>{metric.unit}</small></strong></header><Sparkline color={metric.color} values={metric.values} /></article>)}</div>
    <div className="simulation-timeline">
      <div className="timeline-label"><span>仿真时间轴</span><b>T+{simulationTimeS.toFixed(0)}s</b></div>
      <div className="timeline-track">
        <div className="timeline-progress" style={{width: `${currentPercent}%`}} />
        {displayedEvents.map((event) => <button aria-label={`${event.title}，T+${event.simulationTime?.toFixed(0) ?? "—"} 秒`} className={`timeline-marker ${event.type}`} key={event.id} onClick={() => event.simulationTime !== null && sourceMode === "replay" && onSeek(event.simulationTime)} style={{left: `${eventPosition(event, timelineDuration)}%`}} title={`${event.title} · ${event.detail}`} />)}
        <input aria-label="仿真回放时间" disabled={sourceMode !== "replay" || !replayLoaded} max={timelineDuration} min={0} onChange={(event) => onSeek(Number(event.target.value))} step={1} type="range" value={Math.min(simulationTimeS, timelineDuration)} />
      </div>
      <div className="timeline-scale"><span>0s</span><span>{timelineDuration.toFixed(0)}s</span></div>
    </div>
    {expanded && <div className="expanded-analysis"><div className="expanded-chart">{analysisReady && <TrendChart coreIntersectionIds={coreIntersectionIds} history={history} />}</div><div className="comparison-summary"><span>真实实验对比</span>{comparison?.baseline && comparison.candidate ? <><strong>{comparison.baselineLabel} / {comparison.candidateLabel}</strong><p>仅展示 result.json 中标记为实际运行的记录；差异不解释为因果收益。</p>{[["mean_speed_m_s", "平均速度"], ["mean_waiting_time", "平均等待"], ["mean_queue_vehicles", "平均排队"], ["completed_trips", "完成出行"]].map(([key, label]) => { const before = comparison.baseline?.[key]; const after = comparison.candidate?.[key]; return <div key={key}><span>{label}</span><b>{typeof before === "number" ? before.toFixed(2) : "—"}</b><i>→</i><b>{typeof after === "number" ? after.toFixed(2) : "—"}</b></div>; })}</> : <p>暂无可配对的真实基线与当前算法实验结果。</p>}</div></div>}
  </section>;
}
