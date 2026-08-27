import type {BenchmarkAggregateStat, BenchmarkRecord, ExperimentEvidence} from "../api";
import {AlgorithmEvaluationCharts} from "./AlgorithmEvaluationCharts";

type Props = {
  benchmark: BenchmarkRecord | null;
  evidenceIssue: string | null;
  evidenceLoading: boolean;
  evidenceRuns: ExperimentEvidence[];
};

const algorithmOrder = [
  "fixed-time",
  "actuated-control",
  "max-pressure",
  "coordinated-max-pressure",
] as const;

const algorithmNames: Record<string, string> = {
  "fixed-time": "固定配时",
  "actuated-control": "感应控制",
  "max-pressure": "最大压力",
  "coordinated-max-pressure": "雄安车路云协同智控",
};

const metrics = [
  {key: "mean_speed", fallback: "mean_speed_m_s", label: "平均速度", unit: "m/s", digits: 2},
  {key: "mean_queue_vehicles", label: "平均排队", unit: "辆", digits: 1},
  {key: "mean_waiting_time", label: "平均等待", unit: "s", digits: 1},
  {key: "completed_vehicles", label: "完成车辆", unit: "辆", digits: 0},
] as const;

function aggregate(
  benchmark: BenchmarkRecord,
  algorithm: string,
  key: string,
  fallback?: string,
): BenchmarkAggregateStat | null {
  const values = benchmark.result?.aggregate_95ci?.[algorithm];
  const direct = values?.[key] ?? (fallback ? values?.[fallback] : undefined);
  if (direct) return direct;
  if (key !== "completed_vehicles") return null;
  const completed = (benchmark.result?.rows ?? []).filter((row) => row.algorithm === algorithm).map((row) => {
    const motor = typeof row.completed_trips === "number" ? row.completed_trips : 0;
    const bicycle = typeof row.bicycle_completed_trips === "number" ? row.bicycle_completed_trips : 0;
    return motor + bicycle;
  });
  if (!completed.length) return null;
  const mean = completed.reduce((sum, value) => sum + value, 0) / completed.length;
  const standardDeviation = completed.length > 1 ? Math.sqrt(completed.reduce((sum, value) => sum + (value - mean) ** 2, 0) / (completed.length - 1)) : 0;
  const halfWidth = completed.length > 1 ? 4.303 * standardDeviation / Math.sqrt(completed.length) : 0;
  return {n: completed.length, mean, standard_deviation: standardDeviation, ci95_low: mean - halfWidth, ci95_high: mean + halfWidth};
}

function formatStat(stat: BenchmarkAggregateStat | null, digits: number, unit: string): string {
  if (!stat) return "--";
  return `${stat.mean.toFixed(digits)} ${unit}`;
}

function formatInterval(stat: BenchmarkAggregateStat | null, digits: number): string {
  if (!stat) return "无有效样本";
  return `95% CI ${stat.ci95_low.toFixed(digits)}-${stat.ci95_high.toFixed(digits)} · n=${stat.n}`;
}

function pairwiseStatus(status: string): string {
  if (status === "significant_improvement") return "显著改善";
  if (status === "observed_improvement") return "观察到改善";
  return "未证明改善";
}

export function AlgorithmEvaluationReport({benchmark, evidenceIssue, evidenceLoading, evidenceRuns}: Props) {
  if (!benchmark?.result) {
    return (
      <section className="evaluation-report-empty" aria-label="算法评估结果">
        <strong>等待真实实验矩阵</strong>
        <span>运行完成后展示四种策略的均值、95%置信区间与逐次证据。</span>
      </section>
    );
  }

  const result = benchmark.result;
  const isDemo = result.actual_run === false;
  const verdict = Object.values(result.fairness_controls).every(Boolean)
    ? result.b3_verdict.label.replaceAll("B3", "雄安车路云协同智控")
    : "公平性校验未通过，暂不输出最优结论";

  return (
    <section className={`evaluation-report ${isDemo ? "demo" : "actual"}`} aria-label="算法评估报告">
      <AlgorithmEvaluationCharts benchmark={benchmark} evidenceRuns={evidenceRuns} />
      <section className="evaluation-band">
        <header className="evaluation-section-heading">
          <span>07</span>
          <div><h2>标准化指标数据</h2><p>{verdict} · {result.seeds.length}个随机种子</p></div>
        </header>
        <div className="evaluation-ranking-table wide">
          <header><div><h3>{isDemo ? "预置场景聚合指标" : "实际 SUMO 聚合指标"}</h3><small>{isDemo ? "五组随机种子的评估窗口汇总" : "所有数值均来自完成的评估窗口"}</small></div></header>
          <div style={{overflowX: "auto"}}>
            <table>
              <thead><tr><th>控制策略</th>{metrics.map((metric) => <th key={metric.key}>{metric.label}</th>)}</tr></thead>
              <tbody>
                {algorithmOrder.map((algorithm) => (
                  <tr key={algorithm}>
                    <th>{algorithmNames[algorithm]}</th>
                    {metrics.map((metric) => {
                      const stat = aggregate(benchmark, algorithm, metric.key, "fallback" in metric ? metric.fallback : undefined);
                      return <td className={algorithm === "coordinated-max-pressure" ? "best" : ""} key={metric.key} title={formatInterval(stat, metric.digits)}>{formatStat(stat, metric.digits, metric.unit)}{algorithm === "coordinated-max-pressure" && stat ? <b>协同</b> : null}</td>;
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section className="evaluation-band">
        <header className="evaluation-section-heading">
          <span>08</span>
          <div><h2>协同智控逐基线检验</h2><p>{isDemo ? "同种子配对比较，正值表示协同智控相对基线改善" : "同种子配对比较，改善比例和显著性均由后端统计结果给出"}</p></div>
        </header>
        <div className="evaluation-ranking-table wide">
          <header><div><h3>雄安车路云协同智控相对改善</h3><small>正值表示协同智控优于对应基线</small></div></header>
          <div style={{overflowX: "auto"}}>
            <table>
              <thead><tr><th>基线策略</th><th>平均速度</th><th>平均排队</th><th>平均等待</th></tr></thead>
              <tbody>
                {algorithmOrder.slice(0, 3).map((algorithm) => (
                  <tr key={algorithm}>
                    <th>{algorithmNames[algorithm]}</th>
                    {["mean_speed", "mean_queue_vehicles", "mean_waiting_time"].map((metric) => {
                      const item = result.b3_pairwise?.[algorithm]?.[metric];
                      return <td key={metric} title={item ? pairwiseStatus(item.status) : "无配对样本"}>{item?.improvement_percent == null ? "--" : `${item.improvement_percent.toFixed(1)}%`}</td>;
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section className="evaluation-band">
        <header className="evaluation-section-heading">
          <span>09</span>
          <div><h2>{isDemo ? "运行记录" : "实验事实证据"}</h2><p>{isDemo ? "每个条目对应一组随机种子及其采样序列" : "每个条目对应一个实际运行实验及其采样序列"}</p></div>
        </header>
        {evidenceLoading ? <div className="evaluation-chart-empty" role="status"><b>正在加载实验事实</b><span>等待证据序列返回</span></div> : null}
        {evidenceIssue ? <p className="benchmark-issue" role="alert">{evidenceIssue}</p> : null}
        {!evidenceLoading && !evidenceIssue && (
          <div className="evaluation-ranking-table wide">
            <header><div><h3>{isDemo ? "数据记录" : "可追溯运行记录"}</h3><small>{evidenceRuns.length} 组{isDemo ? "运行记录" : "真实证据"}</small></div></header>
            <div style={{overflowX: "auto"}}>
              <table>
                <thead><tr><th>算法</th><th>随机种子</th><th>采样点</th><th>实验编号</th></tr></thead>
                <tbody>{evidenceRuns.map((run) => <tr key={run.experiment_id}><th>{algorithmNames[run.algorithm] ?? run.algorithm}</th><td>{run.seed}</td><td>{run.source_sample_count}</td><td title={run.experiment_id}>{run.experiment_id}</td></tr>)}</tbody>
              </table>
            </div>
          </div>
        )}
      </section>
    </section>
  );
}
