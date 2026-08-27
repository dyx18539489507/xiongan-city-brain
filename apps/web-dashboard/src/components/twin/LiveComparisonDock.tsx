import type {
  IntersectionComparison,
  LiveComparisonSummary,
  MetricComparison,
} from "../../3d/network/comparisonDigitalTwinTypes";
import {algorithmLabel} from "../../algorithmLabels";
import type {IntersectionNode} from "../../types";

type Props = {
  summary: LiveComparisonSummary;
  baselineAlgorithm: string;
  candidateAlgorithm: string;
  selectedIntersectionId: string | null;
  simulationTimeS: number;
  nodes: IntersectionNode[];
};

const metricDefinitions: Array<[string, string]> = [
  ["total_queue_vehicles", "全网平均排队"],
  ["mean_speed_m_s", "全网平均速度"],
  ["waiting_time_s", "累计等待"],
  ["completed_trips", "完成出行"],
];

export function comparisonVerdictCopy(summary: LiveComparisonSummary): {
  title: string;
  detail: string;
  tone: string;
} {
  if (!summary.valid || summary.verdict === "invalid") {
    return {title: "对照无效", detail: summary.reason ?? "两路状态不能公平配对", tone: "invalid"};
  }
  if (summary.verdict === "warming_up") {
    return {
      title: "建立对照基线",
      detail: `还需 ${Math.ceil(summary.warmup_remaining_s ?? summary.window_s)} 仿真秒`,
      tone: "warming",
    };
  }
  if (summary.verdict === "improved") return {title: "整体呈改善趋势", detail: "当前窗口有利指标占优", tone: "improved"};
  if (summary.verdict === "mixed") return {title: "改善与退化并存", detail: "请检查恶化路口与进口道", tone: "mixed"};
  if (summary.verdict === "worse") return {title: "整体呈退化趋势", detail: "候选算法当前窗口不占优", tone: "worse"};
  return {title: "暂无明显差异", detail: "当前窗口差值低于工程阈值", tone: "stable"};
}

function value(value: number, unit: string): string {
  const digits = Math.abs(value) >= 100 ? 0 : Math.abs(value) >= 10 ? 1 : 2;
  return `${value.toFixed(digits)} ${unit}`;
}

function benefitLabel(metric: MetricComparison): string {
  if (metric.trend === "stable") return `≈ 差值 ${value(metric.delta, metric.unit)}`;
  const arrow = metric.trend === "improved" ? "↓" : "↑";
  const word = metric.trend === "improved" ? "有利" : "不利";
  const percent = metric.benefit_percent === null ? "" : ` · ${Math.abs(metric.benefit_percent).toFixed(1)}%`;
  return `${arrow} ${word} ${value(Math.abs(metric.benefit), metric.unit)}${percent}`;
}

function selectedIntersection(
  summary: LiveComparisonSummary,
  selectedIntersectionId: string | null,
): IntersectionComparison | null {
  return summary.intersections.find((item) => item.intersection_id === selectedIntersectionId)
    ?? summary.intersections.find((item) => item.verdict === "worse")
    ?? summary.intersections[0]
    ?? null;
}

function approachName(direction: string, movement: string): string {
  if (direction === "inbound") return `进口道 · 相位 ${movement || "—"}`;
  return `${direction || "车道"}${movement ? ` · ${movement}` : ""}`;
}

export function LiveComparisonDock({summary, baselineAlgorithm, candidateAlgorithm, selectedIntersectionId, simulationTimeS, nodes}: Props) {
  const verdict = comparisonVerdictCopy(summary);
  const selected = selectedIntersection(summary, selectedIntersectionId);
  const selectedNode = selected
    ? nodes.find((node) => node.intersection_id === selected.intersection_id)
    : null;
  const selectedLabel = selectedNode
    ? `${selectedNode.display_id} · ${selectedNode.display_name}`
    : selected?.intersection_id ?? "";
  const counts = summary.counts ?? {improved_intersections: 0, stable_intersections: 0, worse_intersections: 0};
  const warmupProgress = summary.verdict === "warming_up"
    ? Math.max(0, Math.min(100, 100 * (1 - (summary.warmup_remaining_s ?? summary.window_s) / summary.window_s)))
    : 100;

  return <section className="live-comparison-dock" aria-label="实时算法改善证据">
    <div className={`comparison-verdict ${verdict.tone}`}>
      <header><span>本次运行实时趋势</span><time>T+{Math.floor(simulationTimeS)}s</time></header>
      <strong>{verdict.title}</strong>
      <small>{verdict.detail}</small>
      <div className="comparison-warmup"><i style={{width: `${warmupProgress}%`}} /></div>
      <p>{algorithmLabel(baselineAlgorithm)} <b>↔</b> {algorithmLabel(candidateAlgorithm)}</p>
    </div>

    <div className="comparison-metric-grid">
      {metricDefinitions.map(([key, label]) => {
        const metric = summary.network[key];
        return <article className={metric?.trend ?? "unavailable"} key={key}>
          <span>{label}</span>
          {metric ? <><strong><em>基 {value(metric.baseline, metric.unit)}</em><b>→</b><em>候 {value(metric.candidate, metric.unit)}</em></strong><small>{summary.verdict === "warming_up" ? "≈ 正在积累 60 秒窗口" : benefitLabel(metric)}</small></> : <><strong>—</strong><small>等待 SUMO 指标</small></>}
        </article>;
      })}
    </div>

    <div className="comparison-location-detail">
      <header><span>路口差值定位</span><small>{summary.intersections.length} 个已配对</small></header>
      <div className="comparison-counts"><b className="improved">↓ 改善 {counts.improved_intersections}</b><b className="stable">≈ 持平 {counts.stable_intersections}</b><b className="worse">↑ 恶化 {counts.worse_intersections}</b></div>
      {selected ? <div className="selected-delta">
        <strong title={selected.intersection_id}>{selectedLabel} · {summary.verdict === "warming_up" ? "建立基线" : selected.label}</strong>
        <div>{selected.approaches.slice(0, 3).map((approach) => <span className={summary.verdict === "warming_up" ? "stable" : approach.verdict} key={approach.lane_id} title={approach.lane_id}><em>{approachName(approach.direction, approach.movement)}</em><b>基 {approach.baseline.queue_vehicles?.toFixed(1) ?? "—"} → 候 {approach.candidate.queue_vehicles?.toFixed(1) ?? "—"}</b><small>{summary.verdict === "warming_up" ? "≈ 累积中" : approach.label}</small></span>)}</div>
      </div> : <p className="comparison-empty">等待首个同步路口样本</p>}
    </div>
  </section>;
}
