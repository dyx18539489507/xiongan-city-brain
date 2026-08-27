import {useEffect, useState} from "react";
import type {DigitalTwinState} from "../../3d/network/digitalTwinTypes";
import type {PairedDigitalTwinStream} from "../../3d/network/comparisonDigitalTwinTypes";
import {algorithmLabel} from "../../algorithmLabels";

export type ComparisonRole = "baseline" | "candidate";

type Props = {
  paired: PairedDigitalTwinStream;
  selectedRole: ComparisonRole;
  onRoleChange: (role: ComparisonRole) => void;
};

type Sample = {
  pairId: string;
  time: number;
  baseline: Record<string, number>;
  candidate: Record<string, number>;
  event: boolean;
};

type MetricDefinition = {
  key: string;
  label: string;
  unit: string;
  higherBetter: boolean;
};

export const comparisonMetrics: MetricDefinition[] = [
  {key: "total_queue_vehicles", label: "全网排队", unit: "辆", higherBetter: false},
  {key: "mean_speed_m_s", label: "平均速度", unit: "m/s", higherBetter: true},
  {key: "waiting_time_s", label: "车辆等待", unit: "s", higherBetter: false},
  {key: "completed_trips", label: "完成出行", unit: "次", higherBetter: true},
  {key: "max_queue_vehicles", label: "最大排队", unit: "辆", higherBetter: false},
  {key: "pedestrian_waiting_time_s", label: "行人等待", unit: "s", higherBetter: false},
  {key: "bicycle_queue_count", label: "骑行排队", unit: "人", higherBetter: false},
  {key: "safety_conflicts", label: "交通冲突", unit: "次", higherBetter: false},
];

const reasonLabels: Record<string, string> = {
  EDGE_AUTONOMOUS: "边缘自主决策",
  CLOUD_TARGET_APPLIED: "采用云端协调目标",
  CURRENT_PRESSURE_DOMINANCE_GUARD: "压力保护门限生效",
  PREDICTIVE_GAIN_BELOW_GATE: "预测收益未过门限",
  SWITCH_AWAITING_CONFIRMATION: "等待切相确认",
  GREEN_WAVE_PHASE_ALIGNMENT: "绿波相位对齐",
  PREDICTION_ENHANCED: "预测增强已启用",
  PREDICTION_FALLBACK_CURRENT_STATE: "预测不可用，回退当前状态",
  NATIVE_CLEARANCE_ACTIVE: "黄灯/全红清空中",
};

export function safetyConflictCount(source: Readonly<Record<string, number>>): number {
  return (source.motor_bicycle_conflict_count ?? 0)
    + (source.motor_pedestrian_conflict_count ?? 0)
    + (source.bicycle_pedestrian_conflict_count ?? 0);
}

function numericMetrics(state: DigitalTwinState): Record<string, number> {
  const output: Record<string, number> = {};
  for (const [key, value] of Object.entries(state.metrics)) {
    if (typeof value === "number" && Number.isFinite(value)) output[key] = value;
  }
  output.safety_conflicts = safetyConflictCount(output);
  return output;
}

function metricValue(source: Record<string, number>, key: string): number | null {
  const value = source[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function format(value: number | null, unit = ""): string {
  if (value === null) return "--";
  const digits = Math.abs(value) >= 100 ? 0 : Math.abs(value) >= 10 ? 1 : 2;
  return `${value.toFixed(digits)}${unit ? ` ${unit}` : ""}`;
}

function linePath(values: Array<number | null>, width: number, height: number, min: number, max: number): string {
  const range = Math.max(1e-6, max - min);
  return values.map((value, index) => {
    if (value === null) return "";
    const x = values.length <= 1 ? width : index / (values.length - 1) * width;
    const y = height - (value - min) / range * height;
    return `${index === 0 ? "M" : "L"}${x.toFixed(2)} ${y.toFixed(2)}`;
  }).join(" ");
}

function ComparisonChart({samples, metric}: {samples: Sample[]; metric: MetricDefinition}) {
  const visible = samples.slice(-90);
  const baseline = visible.map((item) => metricValue(item.baseline, metric.key));
  const candidate = visible.map((item) => metricValue(item.candidate, metric.key));
  const delta = visible.map((item, index) => baseline[index] === null || candidate[index] === null
    ? null
    : (candidate[index] as number) - (baseline[index] as number));
  const all = [...baseline, ...candidate, ...delta].filter((item): item is number => item !== null);
  const min = Math.min(0, ...all);
  const max = Math.max(1, ...all);
  return <div className="comparison-chart-shell">
    <svg aria-label={`${metric.label}基准候选与差值实时曲线`} preserveAspectRatio="none" role="img" viewBox="0 0 520 92">
      <path className="comparison-chart-grid" d="M0 1H520M0 31H520M0 61H520M0 91H520" />
      {visible.map((item, index) => item.event && <line className="comparison-event-marker" key={`${item.time}-${index}`} x1={visible.length <= 1 ? 520 : index / (visible.length - 1) * 520} x2={visible.length <= 1 ? 520 : index / (visible.length - 1) * 520} y1="0" y2="92" />)}
      <path className="baseline-line" d={linePath(baseline, 520, 90, min, max)} />
      <path className="candidate-line" d={linePath(candidate, 520, 90, min, max)} />
      <path className="delta-line" d={linePath(delta, 520, 90, min, max)} />
    </svg>
    <div className="comparison-chart-legend"><span className="baseline">基准</span><span className="candidate">候选</span><span className="delta">差值</span><span className="event">事件</span></div>
  </div>;
}

export function decisionReasons(item: Readonly<Record<string, unknown>> | null): string[] {
  const codes = item?.decision_reason_codes;
  if (!Array.isArray(codes)) return [];
  return codes.slice(0, 3).map((code) => {
    const raw = String(code);
    const [base, detail] = raw.split(":", 2);
    if (base === "POLICY_PORTFOLIO_SELECTED") return `策略组合选择 ${detail || "--"}`;
    return reasonLabels[base] ?? raw;
  });
}

function ComparisonBars({baseline, candidate, metric}: {baseline: number | null; candidate: number | null; metric: MetricDefinition}) {
  const maximum = Math.max(baseline ?? 0, candidate ?? 0, 1);
  const height = (value: number | null) => value === null ? 3 : Math.max(3, Math.min(100, value / maximum * 100));
  return <div aria-label={`${metric.label}基准候选柱状图`} className="reference-comparison-bars" role="img">
    <div className="reference-comparison-chart-grid" aria-hidden="true"><i /><i /><i /></div>
    <div className="baseline"><b>{format(baseline, metric.unit)}</b><span><i style={{height: `${height(baseline)}%`}} /></span><small>基准</small></div>
    <div className="candidate"><b>{format(candidate, metric.unit)}</b><span><i style={{height: `${height(candidate)}%`}} /></span><small>候选</small></div>
  </div>;
}

export function AlgorithmComparisonPanel({paired, selectedRole, onRoleChange}: Props) {
  const [metricKey, setMetricKey] = useState(comparisonMetrics[0].key);
  const [samples, setSamples] = useState<Sample[]>([]);
  const state = paired.state;
  const metric = comparisonMetrics.find((item) => item.key === metricKey) ?? comparisonMetrics[0];

  useEffect(() => {
    if (!state.pairId || !state.initialized) {
      setSamples((current) => current.length ? [] : current);
      return;
    }
    const sample: Sample = {
      pairId: state.pairId,
      time: state.simulationTimeS,
      baseline: numericMetrics(state.baseline),
      candidate: numericMetrics(state.candidate),
      event: [...state.baseline.events, ...state.candidate.events].some((item) => Math.abs(item.simulationTime - state.simulationTimeS) < 0.51),
    };
    setSamples((current) => {
      const samePair = current.filter((item) => item.pairId === sample.pairId && item.time !== sample.time);
      return [...samePair, sample].sort((left, right) => left.time - right.time).slice(-180);
    });
  }, [state.baseline, state.candidate, state.initialized, state.pairId, state.simulationTimeS]);

  const latest = samples.at(-1);
  const baselineMetrics = latest?.baseline ?? numericMetrics(state.baseline);
  const candidateMetrics = latest?.candidate ?? numericMetrics(state.candidate);
  const baselineValue = metricValue(baselineMetrics, metric.key);
  const candidateValue = metricValue(candidateMetrics, metric.key);
  const delta = baselineValue === null || candidateValue === null ? null : candidateValue - baselineValue;
  const beneficial = delta === null ? null : metric.higherBetter ? delta >= 0 : delta <= 0;
  const manifest = state.fairnessManifest;
  const warmupRemaining = state.comparison.warmup_remaining_s ?? 0;
  const warmupProgress = state.comparison.verdict === "warming_up"
    ? Math.max(0, Math.min(100, 100 * (1 - warmupRemaining / Math.max(1, state.comparison.window_s))))
    : 100;
  const fairnessOk = state.comparison.valid && Boolean(state.fairnessFingerprint);

  return <section className="reference-comparison-panel" aria-label="左侧实时算法对照">
    <header className="reference-comparison-heading">
      <div><span>ALGORITHM BENCHMARK</span><strong>同条件算法对比</strong></div>
      <em className={fairnessOk ? "valid" : "invalid"}>{fairnessOk ? "同步" : "校验中"}</em>
    </header>

    <div className="reference-comparison-role-switch" aria-label="三维算法数据源">
        <button aria-pressed={selectedRole === "baseline"} className={selectedRole === "baseline" ? "active baseline" : "baseline"} onClick={() => onRoleChange("baseline")}><span>基准</span><b>{algorithmLabel(state.baselineAlgorithm)}</b></button>
        <button aria-pressed={selectedRole === "candidate"} className={selectedRole === "candidate" ? "active candidate" : "candidate"} onClick={() => onRoleChange("candidate")}><span>候选</span><b>{algorithmLabel(state.candidateAlgorithm)}</b></button>
    </div>

    <div className="reference-comparison-fairness" title={state.fairnessFingerprint || state.comparison.reason || "等待同步数据"}>
      <div><i className={fairnessOk ? "valid" : ""} /><span>{String(manifest.scenario_profile ?? "--")} · seed {String(manifest.seed ?? "--")} · T+{Math.floor(state.simulationTimeS)}s</span></div>
      <b>{state.comparison.verdict === "warming_up" ? `暖机 ${Math.ceil(warmupRemaining)}s` : `窗口 ${state.comparison.window_s}s · ${state.comparison.paired_sample_count} 样本`}</b>
      <span><i style={{width: `${warmupProgress}%`}} /></span>
    </div>

    <div className="reference-comparison-metric-selector" role="tablist" aria-label="实时对照指标">
        {comparisonMetrics.map((item) => <button aria-selected={metric.key === item.key} className={metric.key === item.key ? "active" : ""} key={item.key} onClick={() => setMetricKey(item.key)} role="tab">{item.label}</button>)}
    </div>

    <div className="reference-comparison-values">
      <span>基准<b>{format(baselineValue, metric.unit)}</b></span>
      <span>候选<b>{format(candidateValue, metric.unit)}</b></span>
      <span className={beneficial === null ? "" : beneficial ? "benefit" : "harm"}>差值<b>{delta === null ? "--" : `${delta > 0 ? "+" : ""}${format(delta, metric.unit)}`}</b></span>
    </div>

    <section className="reference-comparison-chart-section"><header><span>{metric.label}</span><b>当前对比</b></header><ComparisonBars baseline={baselineValue} candidate={candidateValue} metric={metric} /></section>
    <section className="reference-comparison-chart-section"><header><span>{metric.label}</span><b>实时趋势</b></header><ComparisonChart metric={metric} samples={samples} /></section>
  </section>;
}
