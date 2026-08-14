import {useEffect, useRef, useState} from "react";
import type {RealtimeSnapshot} from "../types";

type Props = {
  history: RealtimeSnapshot[];
  coreIntersectionIds: string[];
};

type ViewMode = "traffic" | "corridor" | "coordination";

const colors = ["#35d5b3", "#e7ba63", "#8bbcf0", "#ff8b5c", "#bd9df5"];

function commonAxes(history: RealtimeSnapshot[]) {
  return {
    xAxis: {
      type: "category",
      boundaryGap: false,
      data: history.map((item) => item.simulation_time_s?.toFixed(0) ?? ""),
      axisLine: {lineStyle: {color: "#284657"}},
      axisLabel: {color: "#6f8c9b"},
      splitLine: {show: false},
    },
    tooltip: {
      trigger: "axis",
      backgroundColor: "#0b2331",
      borderColor: "#315367",
      textStyle: {color: "#d8eaf2", fontSize: 10},
    },
  };
}

export function TrendChart({history, coreIntersectionIds}: Props) {
  const elementRef = useRef<HTMLDivElement>(null);
  const [mode, setMode] = useState<ViewMode>("traffic");

  useEffect(() => {
    const element = elementRef.current;
    if (!element || !history.length) return;
    let cancelled = false;
    let chart: import("echarts/core").EChartsType | null = null;
    let observer: ResizeObserver | null = null;
    const render = async () => {
      const {initTrendChart} = await import("./echartsRuntime");
      if (cancelled) return;
      const instance = initTrendChart(element);
      chart = instance;
    const base = {
      ...commonAxes(history),
      animationDuration: 380,
      backgroundColor: "transparent",
      grid: {left: 45, right: 55, top: 38, bottom: 28},
      legend: {
        top: 0,
        right: 0,
        textStyle: {color: "#8da9b8", fontSize: 10},
      },
    };

    if (mode === "corridor") {
      instance.setOption({
        ...base,
        yAxis: {
          type: "value",
          name: "veh",
          nameTextStyle: {color: "#6f8c9b"},
          axisLabel: {color: "#6f8c9b"},
          splitLine: {lineStyle: {color: "rgba(88,130,150,.13)"}},
        },
        series: coreIntersectionIds.map((id, index) => ({
          name: `核心 ${index + 1}`,
          type: "line",
          data: history.map(
            (snapshot) =>
              snapshot.intersections?.find(
                (item) => item.intersection_id === id,
              )?.queue_vehicles ?? null,
          ),
          showSymbol: false,
          smooth: 0.18,
          lineStyle: {width: 1.8, color: colors[index % colors.length]},
        })),
      });
    } else if (mode === "coordination") {
      instance.setOption({
        ...base,
        yAxis: [
          {
            type: "value",
            name: "%",
            max: 100,
            axisLabel: {color: "#6f8c9b"},
            splitLine: {lineStyle: {color: "rgba(88,130,150,.13)"}},
          },
          {
            type: "value",
            name: "ms",
            axisLabel: {color: "#6f8c9b"},
            splitLine: {show: false},
          },
        ],
        series: [
          {
            name: "下游占有率",
            type: "line",
            data: history.map((item) =>
              item.downstream_occupancy === undefined
                ? null
                : item.downstream_occupancy * 100,
            ),
            showSymbol: false,
            lineStyle: {width: 2.2, color: colors[1]},
          },
          {
            name: "端到端时延",
            type: "line",
            yAxisIndex: 1,
            data: history.map(
              (item) => item.end_to_end_control_latency_ms ?? null,
            ),
            showSymbol: false,
            lineStyle: {width: 2, color: colors[3]},
          },
          {
            name: "云端决策",
            type: "line",
            yAxisIndex: 1,
            data: history.map(
              (item) => item.cloud_decision_latency_ms ?? null,
            ),
            showSymbol: false,
            lineStyle: {width: 1.4, color: colors[2]},
          },
          {
            name: "边缘决策",
            type: "line",
            yAxisIndex: 1,
            data: history.map(
              (item) => item.edge_decision_latency_ms ?? null,
            ),
            showSymbol: false,
            lineStyle: {width: 1.4, color: colors[0]},
          },
        ],
      });
    } else {
      instance.setOption({
        ...base,
        yAxis: [
          {
            type: "value",
            name: "m/s · veh",
            axisLabel: {color: "#6f8c9b"},
            splitLine: {lineStyle: {color: "rgba(88,130,150,.13)"}},
          },
          {
            type: "value",
            name: "trip",
            axisLabel: {color: "#6f8c9b"},
            splitLine: {show: false},
          },
        ],
        series: [
          {
            name: "平均速度",
            type: "line",
            data: history.map((item) => item.mean_speed_m_s ?? null),
            showSymbol: false,
            smooth: 0.2,
            lineStyle: {width: 2.4, color: colors[0]},
            areaStyle: {color: "rgba(53,213,179,.06)"},
          },
          {
            name: "总排队",
            type: "line",
            data: history.map((item) => item.total_queue_vehicles ?? null),
            showSymbol: false,
            smooth: 0.16,
            lineStyle: {width: 2, color: colors[1]},
          },
          {
            name: "吞吐量",
            type: "line",
            yAxisIndex: 1,
            data: history.map((item) => item.throughput_vehicles ?? null),
            showSymbol: false,
            lineStyle: {width: 1.8, color: colors[2]},
          },
        ],
      });
    }
      observer = new ResizeObserver(() => instance.resize());
      observer.observe(element);
    };
    void render();
    return () => {
      cancelled = true;
      observer?.disconnect();
      chart?.dispose();
    };
  }, [coreIntersectionIds, history, mode]);

  return (
    <div className="trend-chart-shell">
      <div className="trend-tabs" aria-label="趋势图选择">
        <button
          className={mode === "traffic" ? "active" : ""}
          onClick={() => setMode("traffic")}
        >
          交通效率
        </button>
        <button
          className={mode === "corridor" ? "active" : ""}
          onClick={() => setMode("corridor")}
        >
          核心路口
        </button>
        <button
          className={mode === "coordination" ? "active" : ""}
          onClick={() => setMode("coordination")}
        >
          协同通信
        </button>
      </div>
      <div
        ref={elementRef}
        className="trend-chart"
        aria-label="真实交通、核心走廊与协同通信趋势"
      />
    </div>
  );
}
