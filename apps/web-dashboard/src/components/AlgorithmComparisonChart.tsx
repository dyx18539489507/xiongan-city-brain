import {useEffect, useMemo, useRef} from "react";

type Metrics = Record<string, number | string | boolean | null> | undefined;

type Props = {
  baselineLabel: string;
  candidateLabel: string;
  baseline: Metrics;
  candidate: Metrics;
};

const dimensions = [
  ["mean_speed_m_s", "平均速度"],
  ["mean_waiting_time", "平均等待"],
  ["mean_queue_vehicles", "平均排队"],
  ["completed_trips", "完成出行"],
] as const;

export function AlgorithmComparisonChart({baselineLabel, candidateLabel, baseline, candidate}: Props) {
  const elementRef = useRef<HTMLDivElement>(null);
  const chartData = useMemo(() => dimensions.flatMap(([key, label]) => {
    const left = baseline?.[key];
    const right = candidate?.[key];
    if (typeof left !== "number" || typeof right !== "number" || left === 0) return [];
    return [{label, candidateIndex: right / left * 100}];
  }), [baseline, candidate]);

  useEffect(() => {
    const element = elementRef.current;
    if (!element || !chartData.length) return;
    let cancelled = false;
    let chart: import("echarts/core").EChartsType | null = null;
    let observer: ResizeObserver | null = null;
    void import("./echartsRuntime").then(({initTrafficChart}) => {
      if (cancelled) return;
      chart = initTrafficChart(element);
      chart.setOption({
        animationDuration: 420,
        backgroundColor: "transparent",
        grid: {left: 42, right: 16, top: 34, bottom: 28},
        legend: {top: 0, right: 0, textStyle: {color: "#607887", fontSize: 9}},
        tooltip: {
          trigger: "axis",
          backgroundColor: "rgba(255,255,255,.98)",
          borderColor: "rgba(43,78,94,.18)",
          textStyle: {color: "#17364d", fontSize: 9},
          valueFormatter: (item: unknown) => typeof item === "number" ? `${item.toFixed(1)}%` : String(item),
        },
        xAxis: {
          type: "category",
          data: chartData.map((item) => item.label),
          axisLine: {lineStyle: {color: "rgba(43,78,94,.18)"}},
          axisLabel: {color: "#607887", fontSize: 8},
        },
        yAxis: {
          type: "value",
          name: "Baseline = 100",
          nameTextStyle: {color: "#607887", fontSize: 8},
          axisLabel: {color: "#607887", fontSize: 8},
          splitLine: {lineStyle: {color: "rgba(43,78,94,.10)"}},
        },
        series: [
          {name: baselineLabel || "Baseline", type: "bar", data: chartData.map(() => 100), barMaxWidth: 16, itemStyle: {color: "#8da1aa"}},
          {name: candidateLabel || "Candidate", type: "bar", data: chartData.map((item) => item.candidateIndex), barMaxWidth: 16, itemStyle: {color: "#0b9d91"}},
        ],
      });
      observer = new ResizeObserver(() => chart?.resize());
      observer.observe(element);
    });
    return () => { cancelled = true; observer?.disconnect(); chart?.dispose(); };
  }, [baselineLabel, candidateLabel, chartData]);

  if (!chartData.length) return <p className="comparison-chart-empty">选择两个含真实汇总指标的实验后生成对比图</p>;
  return <div className="algorithm-comparison-chart" ref={elementRef} role="img" aria-label="真实实验算法指标相对对比图" />;
}
