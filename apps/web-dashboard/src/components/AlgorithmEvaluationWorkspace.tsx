import {useEffect, useMemo, useState} from "react";
import type {ReplayItem} from "../3d/replay/useDigitalTwinPlayback";
import {
  createBenchmark,
  describeRequestError,
  loadBenchmark,
  loadBenchmarks,
  loadExperimentEvidence,
  type BenchmarkRecord,
  type ExperimentEvidence,
} from "../api";
import type {Algorithm} from "../types";
import {AlgorithmEvaluationReport} from "./AlgorithmEvaluationReport";

type Props = {
  algorithms: Algorithm[];
  replays: ReplayItem[];
  baselineId: string;
  candidateId: string;
  onBaselineChange: (id: string) => void;
  onCandidateChange: (id: string) => void;
  onRefresh: () => Promise<void>;
};

type NumericMetrics = Record<string, number | string | boolean | null>;

export const ALGORITHM_ORDER = [
  "fixed-time",
  "actuated-control",
  "max-pressure",
  "coordinated-max-pressure",
] as const;

export type EvaluationAlgorithm = (typeof ALGORITHM_ORDER)[number];

export const evaluationAlgorithmNames: Record<EvaluationAlgorithm, string> = {
  "fixed-time": "固定配时",
  "actuated-control": "感应控制",
  "max-pressure": "最大压力",
  "coordinated-max-pressure": "雄安车路云协同智控",
};

const benchmarkPollLimit = 14_400;
const matrixWarmupS = 600;

function numberMetric(metrics: NumericMetrics | undefined, key: string, fallback?: string): number | null {
  const value = metrics?.[key] ?? (fallback ? metrics?.[fallback] : undefined);
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function benchmarkMetric(record: BenchmarkRecord | null, algorithm: string, key: string, fallback?: string): number | null {
  const aggregate = record?.result?.aggregate_95ci?.[algorithm];
  const aggregateValue = aggregate?.[key]?.mean ?? (fallback ? aggregate?.[fallback]?.mean : undefined);
  if (typeof aggregateValue === "number" && Number.isFinite(aggregateValue)) return aggregateValue;
  const values = (record?.result?.rows ?? record?.rows ?? [])
    .filter((row) => row.algorithm === algorithm)
    .map((row) => numberMetric(row, key, fallback))
    .filter((value): value is number => value !== null);
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
}

export function orderedAlgorithmMetrics(
  record: BenchmarkRecord | null,
  key: string,
  fallback?: string,
): Array<{algorithm: EvaluationAlgorithm; value: number | null}> {
  return ALGORITHM_ORDER.map((algorithm) => ({
    algorithm,
    value: benchmarkMetric(record, algorithm, key, fallback),
  }));
}

export function b3PairwiseImprovements(
  record: BenchmarkRecord | null,
  metric: string,
): Array<{baseline: EvaluationAlgorithm; value: number | null}> {
  return ALGORITHM_ORDER.slice(0, 3).map((baseline) => {
    const value = record?.result?.b3_pairwise?.[baseline]?.[metric]?.improvement_percent;
    return {baseline, value: typeof value === "number" && Number.isFinite(value) ? value : null};
  });
}

export function verdictShowsBest(record: BenchmarkRecord | null): boolean {
  return record?.status === "completed" &&
    record.result?.b3_verdict?.status === "best" &&
    Object.values(record.result.fairness_controls).every(Boolean);
}

export function benchmarkEvaluationWindow(warmupS: number, durationS: number): string {
  const evaluationStartS = warmupS > 0 ? warmupS + 1 : 1;
  return `预热 0→${warmupS}s / 评估 ${evaluationStartS}→${warmupS + durationS}s`;
}

function formatElapsed(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60).toString().padStart(2, "0");
  const remainder = Math.floor(seconds % 60).toString().padStart(2, "0");
  return hours ? `${hours}:${minutes}:${remainder}` : `${minutes}:${remainder}`;
}

function benchmarkMessage(message: string): string {
  let localized = message;
  for (const algorithm of ALGORITHM_ORDER) {
    localized = localized.replaceAll(algorithm, evaluationAlgorithmNames[algorithm]);
  }
  return localized
    .replaceAll("Formal paired benchmark completed", "正式公平配对实验已完成")
    .replaceAll("Formal paired benchmark failed", "正式公平配对实验失败")
    .replaceAll("Preparing the formal paired benchmark matrix", "正在准备正式公平配对实验矩阵")
    .replaceAll("Completed", "已完成")
    .replaceAll("B0", evaluationAlgorithmNames["fixed-time"])
    .replaceAll("B1", evaluationAlgorithmNames["actuated-control"])
    .replaceAll("B2", evaluationAlgorithmNames["max-pressure"])
    .replaceAll("B3", evaluationAlgorithmNames["coordinated-max-pressure"])
    .replaceAll("seed", "随机种子");
}

const fairnessLabels: Record<string, string> = {
  same_warmup_state: "统一预热状态",
  same_network: "相同路网",
  same_od_and_departures_within_seed: "相同OD与发车序列",
  same_vehicle_types: "相同交通参与者",
  same_duration: "相同评估时长",
  same_disturbances: "相同扰动",
  only_algorithm_changes: "仅改变控制算法",
};

export function AlgorithmEvaluationWorkspace(props: Props) {
  const [matrixSeeds, setMatrixSeeds] = useState([11, 23, 37, 41, 59]);
  const [matrixDuration, setMatrixDuration] = useState(1800);
  const [benchmark, setBenchmark] = useState<BenchmarkRecord | null>(null);
  const [benchmarkBusy, setBenchmarkBusy] = useState(false);
  const [benchmarksLoading, setBenchmarksLoading] = useState(true);
  const [benchmarkElapsedS, setBenchmarkElapsedS] = useState(0);
  const [benchmarkIssue, setBenchmarkIssue] = useState<string | null>(null);
  const [evidenceRuns, setEvidenceRuns] = useState<ExperimentEvidence[]>([]);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [evidenceIssue, setEvidenceIssue] = useState<string | null>(null);

  const installedAlgorithms = useMemo(() => new Set(props.algorithms.map((item) => item.name)), [props.algorithms]);
  const matrixReady = ALGORITHM_ORDER.every((name) => installedAlgorithms.has(name));
  const benchmarkRows = benchmark?.result?.rows ?? benchmark?.rows ?? [];
  const evidenceIds = useMemo(
    () => [...new Set(benchmarkRows.map((row) => row.experiment_id).filter(Boolean))],
    [benchmarkRows],
  );
  const evidenceKey = evidenceIds.join("|");
  const fairness = benchmark?.result?.fairness_controls ?? {};
  const fairnessPassed = Boolean(benchmark?.result && Object.values(fairness).every(Boolean));
  const benchmarkRunning = benchmark?.status === "queued" || benchmark?.status === "running";
  const benchmarkActive = benchmarkBusy || benchmarkRunning;
  const benchmarkControlsDisabled = benchmarkActive || benchmarksLoading;

  useEffect(() => {
    let cancelled = false;
    setBenchmarksLoading(true);
    loadBenchmarks()
      .then((payload) => { if (!cancelled) setBenchmark(payload.items[0] ?? null); })
      .catch((reason: unknown) => { if (!cancelled) setBenchmarkIssue(describeRequestError(reason)); })
      .finally(() => { if (!cancelled) setBenchmarksLoading(false); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!benchmarkActive) return;
    const recordedStart = benchmark?.created_at ? Date.parse(benchmark.created_at) : Number.NaN;
    const startedAt = Number.isFinite(recordedStart) ? recordedStart : Date.now();
    setBenchmarkElapsedS(Math.max(0, Math.floor((Date.now() - startedAt) / 1000)));
    const timer = window.setInterval(
      () => setBenchmarkElapsedS(Math.floor((Date.now() - startedAt) / 1000)),
      1000,
    );
    return () => window.clearInterval(timer);
  }, [benchmark?.created_at, benchmarkActive]);

  useEffect(() => {
    if (!benchmarkRunning || benchmarkBusy || !benchmark) return;
    let cancelled = false;
    let polling = false;
    const refresh = async () => {
      if (polling) return;
      polling = true;
      try {
        const record = await loadBenchmark(benchmark.id);
        if (cancelled) return;
        setBenchmark(record);
        setBenchmarkIssue(record.status === "failed" ? record.error ?? "算法实验矩阵运行失败" : null);
        if (record.status === "completed") await props.onRefresh();
      } catch (reason) {
        if (!cancelled) setBenchmarkIssue(describeRequestError(reason));
      } finally {
        polling = false;
      }
    };
    const timer = window.setInterval(refresh, 1000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [benchmark?.id, benchmarkBusy, benchmarkRunning, props.onRefresh]);

  useEffect(() => {
    let cancelled = false;
    setEvidenceRuns([]);
    setEvidenceIssue(null);
    if (!evidenceIds.length) return () => { cancelled = true; };
    setEvidenceLoading(true);
    Promise.all(evidenceIds.map(loadExperimentEvidence))
      .then((items) => { if (!cancelled) setEvidenceRuns(items.filter((item) => item.actual_run)); })
      .catch((reason: unknown) => { if (!cancelled) setEvidenceIssue(describeRequestError(reason)); })
      .finally(() => { if (!cancelled) setEvidenceLoading(false); });
    return () => { cancelled = true; };
  }, [evidenceKey]);

  const launchBenchmark = async () => {
    setBenchmarkBusy(true);
    setBenchmarkIssue(null);
    setBenchmark(null);
    setEvidenceRuns([]);
    try {
      const created = await createBenchmark({
        algorithms: [...ALGORITHM_ORDER],
        seeds: matrixSeeds,
        duration_s: matrixDuration,
        warmup_s: matrixWarmupS,
      });
      let record: BenchmarkRecord | null = null;
      for (let attempt = 0; attempt < benchmarkPollLimit; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        record = await loadBenchmark(created.id);
        setBenchmark(record);
        if (record.status !== "queued" && record.status !== "running") break;
      }
      if (!record || record.status === "queued" || record.status === "running") {
        throw new Error("算法实验运行超时，后台任务可能仍在继续，请稍后重新进入评估页");
      }
      if (record.status === "failed") setBenchmarkIssue(record.error ?? "算法实验矩阵运行失败");
      else await props.onRefresh();
    } catch (reason) {
      setBenchmarkIssue(describeRequestError(reason));
    } finally {
      setBenchmarkBusy(false);
    }
  };

  return (
    <section className="workspace-page algorithm-workspace" aria-label="算法评估工作区">
      <section className="benchmark-runner evaluation-runner" aria-label="四种控制策略实际实验矩阵">
        <div className="benchmark-intro">
          <span>实验配置与公平性</span>
          <h2>同一交通输入下的四策略完整证据链</h2>
          <p>{benchmarkEvaluationWindow(matrixWarmupS, matrixDuration)} · 完成车辆包含机动车与非机动车</p>
        </div>
        <div className="benchmark-algorithm-locks">
          {ALGORITHM_ORDER.map((algorithm) => (
            <span className={installedAlgorithms.has(algorithm) ? "ready" : "missing"} key={algorithm}>
              {evaluationAlgorithmNames[algorithm]}
            </span>
          ))}
        </div>
        <label><span>随机种子组</span><select disabled={benchmarkControlsDisabled} value={matrixSeeds.join(",")} onChange={(event) => setMatrixSeeds(event.target.value.split(",").map(Number))}><option value="11,23,37">3个 · 最低证明门槛</option><option value="11,23,37,41,59">5个 · 正式评测</option></select></label>
        <label><span>评估时长</span><select disabled={benchmarkControlsDisabled} value={matrixDuration} onChange={(event) => setMatrixDuration(Number(event.target.value))}><option value={300}>300秒诊断</option><option value={900}>900秒压力测试</option><option value={1800}>1800秒完整场景</option></select></label>
        <button aria-busy={benchmarkActive} className="workspace-primary" disabled={benchmarkControlsDisabled || !matrixReady} onClick={launchBenchmark}>{benchmarksLoading ? "正在读取实验状态" : benchmarkActive ? `SUMO运行中 ${formatElapsed(benchmarkElapsedS)}` : !matrixReady ? "等待四种策略注册" : `运行${ALGORITHM_ORDER.length * matrixSeeds.length}组真实实验`}</button>
        {benchmarksLoading && !benchmark && <div className="benchmark-catalog-state" role="status"><i className="factory-spinner" aria-hidden="true" /><span>正在读取最近一次实验矩阵</span></div>}
        {benchmark && <div aria-live="polite" className={`benchmark-progress ${benchmark.status}`}><div><i style={{width: `${benchmark.progress}%`}} /></div><b>{benchmark.progress}% · {benchmarkMessage(benchmark.message)}</b><span>{benchmark.completed_runs}/{benchmark.total_runs}组{benchmarkActive ? ` · ${formatElapsed(benchmarkElapsedS)}` : ""}</span>{benchmark.status === "completed" && <nav><a href={`/api/v1/benchmarks/${benchmark.id}/artifacts/benchmark.html`} target="_blank" rel="noreferrer">HTML报告</a><a href={`/api/v1/benchmarks/${benchmark.id}/artifacts/benchmark.csv`}>CSV</a><a href={`/api/v1/benchmarks/${benchmark.id}/artifacts/benchmark.json`}>JSON</a></nav>}</div>}
        {benchmarkIssue && <p className="benchmark-issue" role="alert">{benchmarkIssue}</p>}
      </section>

      {benchmark?.result && <section className="fairness-strip" aria-label="公平性校验">
        <strong className={fairnessPassed ? "passed" : "failed"}>{fairnessPassed ? "公平性校验通过" : "公平性校验未通过"}</strong>
        {Object.entries(fairness).map(([key, passed]) => <span className={passed ? "passed" : "failed"} key={key}><i />{fairnessLabels[key] ?? key}</span>)}
      </section>}

      <AlgorithmEvaluationReport
        benchmark={benchmark}
        evidenceIssue={evidenceIssue}
        evidenceLoading={evidenceLoading}
        evidenceRuns={evidenceRuns}
      />
    </section>
  );
}
