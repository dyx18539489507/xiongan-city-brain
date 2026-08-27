import {useEffect, useMemo, useRef, useState, type ReactNode} from "react";
import type {EChartsOption} from "echarts";
import type {BenchmarkRecord, BenchmarkRow, ExperimentEvidence, ExperimentEvidencePoint} from "../api";
import {initTrafficChart} from "./echartsRuntime";

type Props = {benchmark: BenchmarkRecord; evidenceRuns: ExperimentEvidence[]};
type Option = Record<string, unknown>;
type AlgorithmName = "fixed-time" | "actuated-control" | "max-pressure" | "coordinated-max-pressure";
type Metric = {key: string; label: string; unit: string; higherBetter: boolean};

const algorithms: AlgorithmName[] = ["fixed-time", "actuated-control", "max-pressure", "coordinated-max-pressure"];
const names: Record<AlgorithmName, string> = {
  "fixed-time": "固定配时",
  "actuated-control": "感应控制",
  "max-pressure": "最大压力",
  "coordinated-max-pressure": "雄安车路云协同智控",
};
const colors: Record<AlgorithmName, string> = {
  "fixed-time": "#687985",
  "actuated-control": "#258b78",
  "max-pressure": "#c17c25",
  "coordinated-max-pressure": "#c4475e",
};
const metrics: Metric[] = [
  {key: "mean_queue_vehicles", label: "平均排队", unit: "辆", higherBetter: false},
  {key: "mean_waiting_time", label: "平均等待", unit: "秒", higherBetter: false},
  {key: "mean_speed", label: "平均速度", unit: "米/秒", higherBetter: true},
  {key: "completed_vehicles", label: "完成车辆", unit: "辆", higherBetter: true},
  {key: "fuel_per_completed_vehicle_mg", label: "单车燃油", unit: "毫克/辆", higherBetter: false},
  {key: "co2_per_completed_vehicle_mg", label: "单车CO₂", unit: "毫克/辆", higherBetter: false},
];
const rankingMetrics: Metric[] = [
  ...metrics.slice(0, 5),
  {key: "nox_per_completed_vehicle_mg", label: "单车NOx", unit: "毫克/辆", higherBetter: false},
];
const stages = [
  {label: "施工开始", start: 0, end: 300},
  {label: "活动散场", start: 300, end: 450},
  {label: "事故叠加", start: 450, end: 570},
  {label: "应急优先", start: 600, end: 780},
  {label: "复合恢复", start: 900, end: 1200},
  {label: "网络清空", start: 1200, end: 1800},
];
const axis = "#607887";
const split = "rgba(43,78,94,.10)";

function formatAlgorithmAxis(value: string): string {
  return value === names["coordinated-max-pressure"] ? "雄安车路云\n协同智控" : value;
}

function numeric(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function average(values: number[]): number | null {
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
}

function completed(record: Record<string, unknown>): number | null {
  if (numeric(record.completed_vehicles)) return record.completed_vehicles;
  if (!numeric(record.completed_trips)) return null;
  return record.completed_trips + (numeric(record.bicycle_completed_trips) ? record.bicycle_completed_trips : 0);
}

function valueOf(record: Record<string, unknown>, key: string): number | null {
  if (numeric(record[key])) return record[key];
  if (key === "completed_vehicles") return completed(record);
  const count = completed(record);
  if (!count) return null;
  if (key === "fuel_per_completed_vehicle_mg" && numeric(record.fuel_consumption_mg)) return record.fuel_consumption_mg / count;
  if (key === "co2_per_completed_vehicle_mg" && numeric(record.co2_mg)) return record.co2_mg / count;
  if (key === "nox_per_completed_vehicle_mg" && numeric(record.nox_mg)) return record.nox_mg / count;
  if (key === "emergency_braking_rate" && numeric(record.emergency_braking_count)) return record.emergency_braking_count / count * 1000;
  if (key === "conflict_rate") {
    const conflicts = [record.motor_motor_conflict_count, record.motor_bicycle_conflict_count, record.motor_pedestrian_conflict_count, record.bicycle_pedestrian_conflict_count].filter(numeric).reduce((sum, item) => sum + item, 0);
    return conflicts / count * 1000;
  }
  return null;
}

function values(rows: BenchmarkRow[], algorithm: AlgorithmName, key: string): number[] {
  return rows.filter((row) => row.algorithm === algorithm).map((row) => valueOf(row, key)).filter(numeric);
}

function pointValue(point: ExperimentEvidencePoint, key: string): number | null {
  if (key === "completed_vehicles") return completed(point as unknown as Record<string, unknown>);
  return valueOf(point as unknown as Record<string, unknown>, key);
}

function relative(run: ExperimentEvidence, key: string): Array<[number, number]> {
  const start = run.series[0]?.simulation_time_s ?? 0;
  return run.series.map((point) => [Math.max(0, Math.round(point.simulation_time_s - start)), pointValue(point, key)] as [number, number | null])
    .filter((item): item is [number, number] => item[1] !== null);
}

function timeMean(runs: ExperimentEvidence[], algorithm: AlgorithmName, key: string, rollingS = 0): Array<[number, number]> {
  const grouped = new Map<number, number[]>();
  for (const run of runs.filter((item) => item.algorithm === algorithm)) {
    const points = relative(run, key);
    points.forEach(([time, raw], index) => {
      const value = rollingS ? average(points.slice(0, index + 1).filter(([candidate]) => candidate >= time - rollingS).map(([, item]) => item)) ?? raw : raw;
      grouped.set(time, [...(grouped.get(time) ?? []), value]);
    });
  }
  return [...grouped.entries()].sort(([left], [right]) => left - right).map(([time, items]) => [time, average(items) ?? 0]);
}

function quantile(sorted: number[], fraction: number): number {
  if (!sorted.length) return 0;
  const position = (sorted.length - 1) * fraction;
  const lower = Math.floor(position);
  const upper = Math.ceil(position);
  return lower === upper ? sorted[lower] : sorted[lower] + (sorted[upper] - sorted[lower]) * (position - lower);
}

function box(items: number[]): [number, number, number, number, number] {
  const sorted = [...items].sort((left, right) => left - right);
  return [sorted[0] ?? 0, quantile(sorted, .25), quantile(sorted, .5), quantile(sorted, .75), sorted.at(-1) ?? 0];
}

function lineOption(series: Array<{name: string; color: string; data: Array<[number, number]>}>, yName: string, markAt?: number): Option | null {
  if (!series.some((item) => item.data.length)) return null;
  return {
    grid: {left: 60, right: 28, top: 66, bottom: 50},
    legend: {top: 8, data: series.map((item) => item.name), textStyle: {color: axis, fontSize: 9}},
    tooltip: {trigger: "axis"},
    xAxis: {type: "value", name: "评估时间（秒）", splitNumber: 4, axisLabel: {color: axis, hideOverlap: true}, splitLine: {show: false}},
    yAxis: {type: "value", name: yName, min: 0, axisLabel: {color: axis}, splitLine: {lineStyle: {color: split}}},
    series: series.map((item, index) => ({name: item.name, type: "line", showSymbol: false, smooth: .1, data: item.data, lineStyle: {color: item.color, width: item.name === names["coordinated-max-pressure"] ? 3 : 1.7}, itemStyle: {color: item.color}, markLine: markAt !== undefined && index === series.length - 1 ? {silent: true, symbol: "none", data: [{xAxis: markAt}], lineStyle: {color: "#c4475e", type: "dashed"}, label: {formatter: "扰动注入"}} : undefined})),
  };
}

function Chart(props: {title: string; meta: string; option: Option | null; className?: string; controls?: ReactNode; empty?: string}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current || !props.option) return;
    const chart = initTrafficChart(ref.current);
    chart.setOption(props.option as EChartsOption, true);
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(ref.current);
    return () => { observer.disconnect(); chart.dispose(); };
  }, [props.option]);
  return <article className={`evaluation-figure ${props.className ?? ""}`}><header><div><h3>{props.title}</h3><small>{props.meta}</small></div></header>{props.controls}<div className="evaluation-chart" ref={ref} />{!props.option && <div className="evaluation-chart-empty"><b>等待真实实验数据</b><span>{props.empty ?? "完成实验后生成该图"}</span></div>}</article>;
}

function Heading({index, title, description}: {index: string; title: string; description: string}) {
  return <header className="evaluation-section-heading"><span>{index}</span><div><h2>{title}</h2><p>{description}</p></div></header>;
}

export function AlgorithmEvaluationCharts({benchmark, evidenceRuns}: Props) {
  const [metricKey, setMetricKey] = useState(metrics[0].key);
  const isDemo = benchmark.result?.actual_run === false;
  const rows = benchmark.result?.rows ?? benchmark.rows;
  const selectedMetric = metrics.find((item) => item.key === metricKey) ?? metrics[0];

  const options = useMemo(() => {
    const core: Option = {
      grid: {left: 68, right: 24, top: 30, bottom: 60},
      tooltip: {trigger: "axis"},
      xAxis: {type: "category", data: algorithms.map((algorithm) => names[algorithm]), axisLabel: {color: "#17364d", fontSize: 9, interval: 0, formatter: formatAlgorithmAxis}},
      yAxis: {type: "value", name: `${selectedMetric.label}（${selectedMetric.unit}）`, min: 0, axisLabel: {color: axis}, splitLine: {lineStyle: {color: split}}},
      series: [{type: "bar", barMaxWidth: 56, data: algorithms.map((algorithm) => ({value: average(values(rows, algorithm, selectedMetric.key)), itemStyle: {color: colors[algorithm], borderRadius: [3, 3, 0, 0]}})), label: {show: true, position: "top", color: "#17364d", formatter: ({value}: {value: unknown}) => {
        if (!numeric(value)) return "—";
        if (selectedMetric.key === "completed_vehicles" || selectedMetric.key.includes("per_completed")) return value.toFixed(0);
        return value.toFixed(selectedMetric.key === "mean_speed" ? 2 : 1);
      }}}],
    };

    const improvementMetrics = metrics.slice(0, 4);
    const pairwise: Option = {
      grid: {left: 72, right: 25, top: 45, bottom: 45},
      legend: {top: 8, data: algorithms.slice(0, 3).map((algorithm) => names[algorithm]), textStyle: {color: axis, fontSize: 9}},
      tooltip: {trigger: "axis"},
      xAxis: {type: "value", name: "协同智控有利变化（%）", axisLabel: {color: axis, formatter: "{value}%"}, splitLine: {lineStyle: {color: split}}},
      yAxis: {type: "category", data: improvementMetrics.map((metric) => metric.label), axisLabel: {color: "#17364d"}},
      series: algorithms.slice(0, 3).map((algorithm) => ({name: names[algorithm], type: "bar", barMaxWidth: 14, data: improvementMetrics.map((metric) => benchmark.result?.b3_pairwise?.[algorithm]?.[metric.key]?.improvement_percent ?? null), itemStyle: {color: colors[algorithm]}, markLine: {silent: true, symbol: "none", data: [{xAxis: 0}], lineStyle: {color: "rgba(43,78,94,.35)"}, label: {show: false}}})),
    };

    const rankingData: Array<[number, number, number, number | null]> = [];
    rankingMetrics.forEach((metric, x) => {
      const ranked = algorithms.map((algorithm) => ({algorithm, value: average(values(rows, algorithm, metric.key))})).filter((item): item is {algorithm: AlgorithmName; value: number} => item.value !== null).sort((left, right) => metric.higherBetter ? right.value - left.value : left.value - right.value);
      algorithms.forEach((algorithm, y) => rankingData.push([x, y, ranked.findIndex((item) => item.algorithm === algorithm) + 1, ranked.find((item) => item.algorithm === algorithm)?.value ?? null]));
    });
    const ranking: Option = {
      grid: {left: 92, right: 18, top: 24, bottom: 58},
      tooltip: {formatter: (params: unknown) => {const item = (params as {data: [number, number, number, number | null]}).data; return `${names[algorithms[item[1]]]}<br/>${rankingMetrics[item[0]].label} ${item[3]?.toFixed(2) ?? "—"}<br/>第${item[2]}名`; }},
      xAxis: {type: "category", data: rankingMetrics.map((metric) => metric.label), axisLabel: {color: axis, rotate: 24, interval: 0}},
      yAxis: {type: "category", data: algorithms.map((algorithm) => names[algorithm]), axisLabel: {color: "#17364d", fontSize: 9, formatter: formatAlgorithmAxis}},
      visualMap: {show: false, min: 1, max: 4, inRange: {color: ["#cae7dc", "#f1e8d4", "#f4d2cf"]}},
      series: [{type: "heatmap", data: rankingData, label: {show: true, color: "#17364d", formatter: (params: unknown) => `第${(params as {value: number[]}).value[2]}名`}}],
    };

    const queue = lineOption(algorithms.map((algorithm) => ({name: names[algorithm], color: colors[algorithm], data: timeMean(evidenceRuns, algorithm, "controlled_queue_vehicles", 60)})), "排队车辆（辆）");
    const completion = lineOption(algorithms.map((algorithm) => ({name: names[algorithm], color: colors[algorithm], data: timeMean(evidenceRuns, algorithm, "completed_vehicles")})), "累计完成车辆（辆）");

    const stateDurations = algorithms.map((algorithm) => {
      const perRun = evidenceRuns.filter((run) => run.algorithm === algorithm).map((run) => {
        const duration = [0, 0, 0, 0];
        run.series.forEach((point, index) => {
          const seconds = Math.max(0, (run.series[index + 1]?.simulation_time_s ?? point.simulation_time_s) - point.simulation_time_s);
          const level = (point.spillback_intersections ?? 0) > 0 ? 3 : (point.congested_intersections ?? 0) >= 3 ? 2 : (point.congested_intersections ?? 0) > 0 ? 1 : 0;
          duration[level] += seconds;
        });
        return duration;
      });
      return [0, 1, 2, 3].map((index) => average(perRun.map((item) => item[index])) ?? 0);
    });
    const states: Option | null = evidenceRuns.length ? {
      grid: {left: 88, right: 22, top: 42, bottom: 40}, legend: {top: 8, data: ["畅通", "缓行", "拥堵", "溢出"], textStyle: {color: axis, fontSize: 9}}, tooltip: {trigger: "axis", axisPointer: {type: "shadow"}},
      xAxis: {type: "value", name: "持续时间（秒）", axisLabel: {color: axis}, splitLine: {lineStyle: {color: split}}}, yAxis: {type: "category", data: algorithms.map((algorithm) => names[algorithm]), axisLabel: {color: "#17364d", fontSize: 9}},
      series: ["畅通", "缓行", "拥堵", "溢出"].map((name, index) => ({name, type: "bar", stack: "state", data: stateDurations.map((item) => item[index]), itemStyle: {color: ["#4da28f", "#d0af4e", "#d47a49", "#c4475e"][index]}})),
    } : null;

    const intersectionIds = [...new Set(evidenceRuns.flatMap((run) => run.series.flatMap((point) => Object.keys(point.intersection_queue_vehicles ?? {}))))].slice(0, 16);
    const intersectionData: Array<[number, number, number]> = [];
    algorithms.forEach((algorithm, x) => intersectionIds.forEach((id, y) => {
      const observed = evidenceRuns.filter((run) => run.algorithm === algorithm).flatMap((run) => run.series.map((point) => point.intersection_queue_vehicles?.[id]).filter(numeric));
      intersectionData.push([x, y, average(observed) ?? 0]);
    }));
    const intersections: Option | null = intersectionIds.length ? {
      grid: {left: 74, right: 22, top: 28, bottom: 72}, tooltip: {trigger: "item"},
      xAxis: {type: "category", data: algorithms.map((algorithm) => names[algorithm]), axisLabel: {color: "#17364d", fontSize: 9, interval: 0}}, yAxis: {type: "category", data: intersectionIds, axisLabel: {color: axis, fontSize: 8}},
      visualMap: {min: 0, max: Math.max(10, ...intersectionData.map((item) => item[2])), orient: "horizontal", left: "center", bottom: 6, itemWidth: 12, itemHeight: 100, textStyle: {color: axis, fontSize: 8}, inRange: {color: ["#edf4f0", "#e2bc65", "#c4475e"]}}, series: [{type: "heatmap", data: intersectionData, label: {show: true, color: "#17364d", formatter: (params: unknown) => Number((params as {value: number[]}).value[2]).toFixed(0)}}],
    } : null;

    const trajectorySeries: Array<Record<string, unknown>> = [];
    algorithms.forEach((algorithm) => {
      const run = evidenceRuns.find((item) => item.algorithm === algorithm);
      if (!run) return;
      const start = run.series[0]?.simulation_time_s ?? 0;
      const byVehicle = new Map<string, Array<{time: number; x: number; y: number}>>();
      run.series.forEach((point) => (point.vehicle_trajectory_probes ?? []).forEach((probe) => byVehicle.set(probe.vehicle_id, [...(byVehicle.get(probe.vehicle_id) ?? []), {time: point.simulation_time_s - start, x: probe.x_m, y: probe.y_m}])));
      [...byVehicle.entries()].sort((left, right) => right[1].length - left[1].length).slice(0, 4).forEach(([vehicleId, points]) => {
        let distance = 0;
        trajectorySeries.push({name: `${names[algorithm]} · ${vehicleId}`, type: "line", showSymbol: false, data: points.map((point, index) => {const before = points[index - 1]; if (before) distance += Math.hypot(point.x - before.x, point.y - before.y); return [Math.round(point.time), distance];}), lineStyle: {color: colors[algorithm], width: 1.2, opacity: .75}});
      });
    });
    const trajectory: Option | null = trajectorySeries.length ? {grid: {left: 64, right: 22, top: 28, bottom: 46}, tooltip: {trigger: "axis"}, xAxis: {type: "value", name: "评估时间（秒）", axisLabel: {color: axis}}, yAxis: {type: "value", name: "累计距离（米）", min: 0, axisLabel: {color: axis}, splitLine: {lineStyle: {color: split}}}, series: trajectorySeries} : null;

    const queueBox: Option | null = evidenceRuns.length ? {grid: {left: 56, right: 22, top: 30, bottom: 58}, tooltip: {trigger: "item"}, xAxis: {type: "category", data: algorithms.map((algorithm) => names[algorithm]), axisLabel: {color: "#17364d", fontSize: 9, interval: 0}}, yAxis: {type: "value", name: "排队车辆（辆）", min: 0, axisLabel: {color: axis}, splitLine: {lineStyle: {color: split}}}, series: [{type: "boxplot", data: algorithms.map((algorithm) => ({value: box(evidenceRuns.filter((run) => run.algorithm === algorithm).flatMap((run) => run.series.map((point) => point.controlled_queue_vehicles))), itemStyle: {color: `${colors[algorithm]}30`, borderColor: colors[algorithm]}}))}]} : null;

    const stageQueue: Option | null = evidenceRuns.length ? {grid: {left: 58, right: 22, top: 46, bottom: 54}, legend: {top: 8, data: algorithms.map((algorithm) => names[algorithm]), textStyle: {color: axis, fontSize: 9}}, tooltip: {trigger: "axis"}, xAxis: {type: "category", data: stages.map((stage) => stage.label), axisLabel: {color: axis, rotate: 22, interval: 0}}, yAxis: {type: "value", name: "阶段排队（辆）", min: 0, axisLabel: {color: axis}, splitLine: {lineStyle: {color: split}}}, series: algorithms.map((algorithm) => ({name: names[algorithm], type: "line", data: stages.map((stage) => average(evidenceRuns.filter((run) => run.algorithm === algorithm).map((run) => average(relative(run, "controlled_queue_vehicles").filter(([time]) => time >= stage.start && time < stage.end).map(([, item]) => item))).filter(numeric))), lineStyle: {color: colors[algorithm], width: algorithm === "coordinated-max-pressure" ? 3 : 1.7}, itemStyle: {color: colors[algorithm]}}))} : null;

    const stageCompletionData: Array<[number, number, number]> = [];
    algorithms.forEach((algorithm, y) => stages.forEach((stage, x) => stageCompletionData.push([x, y, average(evidenceRuns.filter((run) => run.algorithm === algorithm).map((run) => {const points = relative(run, "completed_vehicles").filter(([time]) => time >= stage.start && time <= stage.end); return points.length > 1 ? points.at(-1)![1] - points[0][1] : null;}).filter(numeric)) ?? 0])));
    const stageCompletion: Option | null = evidenceRuns.length ? {grid: {left: 88, right: 20, top: 25, bottom: 65}, tooltip: {trigger: "item"}, xAxis: {type: "category", data: stages.map((stage) => stage.label), axisLabel: {color: axis, rotate: 24, interval: 0}}, yAxis: {type: "category", data: algorithms.map((algorithm) => names[algorithm]), axisLabel: {color: "#17364d", fontSize: 9}}, visualMap: {min: 0, max: Math.max(1, ...stageCompletionData.map((item) => item[2])), orient: "horizontal", left: "center", bottom: 3, itemWidth: 12, itemHeight: 90, textStyle: {color: axis, fontSize: 8}, inRange: {color: ["#edf4f0", "#8bc5b7", "#1e806f"]}}, series: [{type: "heatmap", data: stageCompletionData, label: {show: true, color: "#17364d", formatter: (params: unknown) => Number((params as {value: number[]}).value[2]).toFixed(0)}}]} : null;
    const recovery = lineOption(algorithms.map((algorithm) => ({name: names[algorithm], color: colors[algorithm], data: timeMean(evidenceRuns, algorithm, "controlled_queue_vehicles", 30).filter(([time]) => time >= 360 && time <= 780).map(([time, item]) => [time - 450, item])})), "排队车辆（辆）", 0);

    const safetyKeys = [{key: "conflict_rate", label: "千车冲突"}, {key: "emergency_braking_rate", label: "千车急刹"}, {key: "acceleration_variance", label: "加速度波动"}];
    const safetyActual = safetyKeys.map((metric) => algorithms.map((algorithm) => average(values(rows, algorithm, metric.key))));
    const safety: Option = {grid: {left: 58, right: 22, top: 44, bottom: 58}, legend: {top: 8, data: safetyKeys.map((item) => item.label), textStyle: {color: axis, fontSize: 9}}, tooltip: {trigger: "axis"}, xAxis: {type: "category", data: algorithms.map((algorithm) => names[algorithm]), axisLabel: {color: "#17364d", fontSize: 9, interval: 0}}, yAxis: {type: "value", name: "固定配时=100", axisLabel: {color: axis}, splitLine: {lineStyle: {color: split}}}, series: safetyKeys.map((item, index) => ({name: item.label, type: "bar", data: safetyActual[index].map((value, algorithmIndex) => value !== null && safetyActual[index][0] ? value / safetyActual[index][0]! * 100 : null), itemStyle: {color: ["#c4475e", "#d18b3f", "#6d8c99"][index]}}))};

    const ttc: Option | null = evidenceRuns.length ? {grid: {left: 58, right: 22, top: 42, bottom: 58}, legend: {top: 8, data: ["最小TTC", "最小PET"], textStyle: {color: axis, fontSize: 9}}, tooltip: {trigger: "item"}, xAxis: {type: "category", data: algorithms.map((algorithm) => names[algorithm]), axisLabel: {color: "#17364d", fontSize: 9, interval: 0}}, yAxis: {type: "value", name: "时间（秒）", min: 0, axisLabel: {color: axis}, splitLine: {lineStyle: {color: split}}}, series: [{name: "最小TTC", type: "boxplot", data: algorithms.map((algorithm) => box(evidenceRuns.filter((run) => run.algorithm === algorithm).flatMap((run) => run.series.map((point) => point.minimum_ttc_s).filter(numeric))))}, {name: "最小PET", type: "boxplot", data: algorithms.map((algorithm) => box(evidenceRuns.filter((run) => run.algorithm === algorithm).flatMap((run) => run.series.map((point) => point.minimum_pet_s).filter(numeric))))}]} : null;

    const energyKeys = [{key: "fuel_per_completed_vehicle_mg", label: "单车燃油"}, {key: "co2_per_completed_vehicle_mg", label: "单车CO₂"}, {key: "nox_per_completed_vehicle_mg", label: "单车NOx"}];
    const energyActual = energyKeys.map((metric) => algorithms.map((algorithm) => average(values(rows, algorithm, metric.key))));
    const energy: Option = {grid: {left: 58, right: 22, top: 44, bottom: 58}, legend: {top: 8, data: energyKeys.map((item) => item.label), textStyle: {color: axis, fontSize: 9}}, tooltip: {trigger: "axis"}, xAxis: {type: "category", data: algorithms.map((algorithm) => names[algorithm]), axisLabel: {color: "#17364d", fontSize: 9, interval: 0}}, yAxis: {type: "value", name: "固定配时=100", axisLabel: {color: axis}, splitLine: {lineStyle: {color: split}}}, series: energyKeys.map((item, index) => ({name: item.label, type: "bar", data: energyActual[index].map((value, algorithmIndex) => value !== null && energyActual[index][0] ? value / energyActual[index][0]! * 100 : null), itemStyle: {color: ["#318b7d", "#668b9d", "#bd913e"][index]}}))};

    const paretoData = algorithms.map((algorithm) => ({name: names[algorithm], value: [average(values(rows, algorithm, "completed_vehicles")), average(values(rows, algorithm, "fuel_per_completed_vehicle_mg")), average(values(rows, algorithm, "mean_queue_vehicles"))], itemStyle: {color: colors[algorithm]}})).filter((item) => item.value.every(numeric));
    const pareto: Option | null = paretoData.length ? {grid: {left: 68, right: 30, top: 30, bottom: 50}, tooltip: {trigger: "item"}, xAxis: {type: "value", name: "完成车辆（越右越好）", min: "dataMin", axisLabel: {color: axis}, splitLine: {lineStyle: {color: split}}}, yAxis: {type: "value", name: "单车燃油（越低越好）", min: "dataMin", axisLabel: {color: axis}, splitLine: {lineStyle: {color: split}}}, series: [{type: "scatter", data: paretoData, symbolSize: 22, label: {show: true, position: "top", color: "#17364d", fontSize: 9, formatter: (params: unknown) => (params as {data: {name: string}}).data.name}}]} : null;

    const latency: Option = {grid: {left: 58, right: 22, top: 44, bottom: 58}, legend: {top: 8, data: ["平均端到端时延", "决策峰值"], textStyle: {color: axis, fontSize: 9}}, tooltip: {trigger: "axis"}, xAxis: {type: "category", data: algorithms.map((algorithm) => names[algorithm]), axisLabel: {color: "#17364d", fontSize: 9, interval: 0}}, yAxis: {type: "value", name: "时延（毫秒）", min: 0, axisLabel: {color: axis}, splitLine: {lineStyle: {color: split}}}, series: [{name: "平均端到端时延", type: "bar", data: algorithms.map((algorithm) => average(values(rows, algorithm, "end_to_end_control_latency_ms"))), itemStyle: {color: "#3d8d82"}}, {name: "决策峰值", type: "scatter", symbol: "diamond", symbolSize: 10, data: algorithms.map((algorithm) => average(values(rows, algorithm, "algorithm_decision_elapsed_ms_max"))), itemStyle: {color: "#c4475e"}}]};

    const outcomes = algorithms.map((algorithm) => {const executed = average(values(rows, algorithm, "signal_action_executed_count")) ?? 0; const modified = average(values(rows, algorithm, "signal_action_modified_count")) ?? 0; const rejected = average(values(rows, algorithm, "signal_action_rejected_count")) ?? 0; const total = Math.max(1, executed + modified + rejected); return [executed / total * 100, modified / total * 100, rejected / total * 100];});
    const reliability: Option = {grid: {left: 90, right: 22, top: 44, bottom: 40}, legend: {top: 8, data: ["正常执行", "安全修正", "安全拒绝"], textStyle: {color: axis, fontSize: 9}}, tooltip: {trigger: "axis", axisPointer: {type: "shadow"}}, xAxis: {type: "value", max: 100, name: "动作占比（%）", axisLabel: {color: axis, formatter: "{value}%"}, splitLine: {lineStyle: {color: split}}}, yAxis: {type: "category", data: algorithms.map((algorithm) => names[algorithm]), axisLabel: {color: "#17364d", fontSize: 9}}, series: [{name: "正常执行", type: "bar", stack: "actions", data: outcomes.map((item) => item[0]), itemStyle: {color: "#2f927d"}}, {name: "安全修正", type: "bar", stack: "actions", data: outcomes.map((item) => item[1]), itemStyle: {color: "#d19a3d"}}, {name: "安全拒绝", type: "bar", stack: "actions", data: outcomes.map((item) => item[2]), itemStyle: {color: "#c4475e"}}]};

    return {core, pairwise, ranking, queue, completion, states, intersections, trajectory, queueBox, stageQueue, stageCompletion, recovery, safety, ttc, energy, pareto, latency, reliability};
  }, [benchmark, evidenceRuns, rows, selectedMetric]);

  return <>
    <section className="evaluation-band"><Heading index="01" title="同场景核心结果" description="四策略均值、逐基线改善和多指标排名" /><div className="evaluation-chart-grid"><Chart className="wide core-result-figure" title="四种控制策略核心指标" meta="相同场景、交通需求、种子和评估窗口" option={options.core} controls={<div className="evaluation-metric-tabs">{metrics.map((metric) => <button aria-pressed={metric.key === selectedMetric.key} className={metric.key === selectedMetric.key ? "active" : ""} key={metric.key} onClick={() => setMetricKey(metric.key)}>{metric.label}</button>)}</div>} /><Chart title="协同智控相对基准的配对改善" meta="正值表示雄安车路云协同智控更优" option={options.pairwise} /><Chart title="多指标排名矩阵" meta="每项指标独立排名，不使用模糊综合分" option={options.ranking} /></div></section>
    <section className="evaluation-band"><Heading index="02" title="1800秒运行过程" description="排队、完成车辆和拥堵状态随时间变化" /><div className="evaluation-chart-grid"><Chart className="wide queue-main-figure" title="四种控制策略排队演化" meta="多种子均值 · 60秒滚动平滑" option={options.queue} /><Chart title="累计完成车辆" meta="完成机动车与非机动车之和" option={options.completion} empty="更新后的1800秒实验将生成累计完成车辆" /><Chart title="交通状态持续时间" meta="畅通、缓行、拥堵和溢出" option={options.states} /></div></section>
    <section className="evaluation-band"><Heading index="03" title="时空运行机理" description="识别拥堵传播、极端长队和车辆轨迹连续性" /><div className="evaluation-chart-grid"><Chart className="wide tall-figure" title="路口—算法排队热力图" meta="四策略同尺度比较重点控制路口" option={options.intersections} /><Chart className="wide tall-figure" title="车辆时空轨迹" meta="稀疏轨迹探针 · 时间—累计距离" option={options.trajectory} empty="轨迹探针将在新的1800秒实验中生成" /><Chart className="wide compact-wide" title="排队分布箱线图" meta="中位数、四分位区间和极端长队" option={options.queueBox} /></div></section>
    <section className="evaluation-band"><Heading index="04" title="多工况与扰动恢复" description="施工、活动散场、事故、应急车辆和恢复阶段" /><div className="evaluation-chart-grid"><Chart title="不同工况排队响应" meta="四策略阶段平均排队" option={options.stageQueue} /><Chart title="工况阶段完成车辆矩阵" meta="各阶段新增完成车辆" option={options.stageCompletion} /><Chart className="wide" title="事故扰动后恢复曲线" meta="扰动前后同时间窗比较" option={options.recovery} empty="当前300秒结果未覆盖事故阶段，请运行1800秒完整场景" /></div></section>
    <section className="evaluation-band"><Heading index="05" title="安全与绿色交通" description="安全事件和能耗均按完成车辆进行公平归一化" /><div className="evaluation-chart-grid"><Chart title="安全事件相对指数" meta="固定配时=100，越低越好" option={options.safety} /><Chart title="TTC与PET观测分布" meta={isDemo ? "基于预设轨迹序列的替代安全指标" : "基于真实轨迹冲突的替代安全指标"} option={options.ttc} /><Chart title="单位完成车辆能耗与排放" meta="固定配时=100，越低越好" option={options.energy} /><Chart title="效率—能耗前沿" meta="越靠右下越优" option={options.pareto} /></div></section>
    <section className="evaluation-band"><Heading index="06" title="车路云工程能力" description="控制时延、动作仲裁、硬超时和算法失败" /><div className="evaluation-chart-grid"><Chart title="控制链路时延" meta="平均端到端时延与决策峰值" option={options.latency} /><Chart title="控制执行与降级可靠性" meta="正常执行、安全修正与安全拒绝" option={options.reliability} /></div></section>
  </>;
}
