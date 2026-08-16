import {BarChart, LineChart} from "echarts/charts";
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import {CanvasRenderer} from "echarts/renderers";

let registered = false;

/** Register only the chart modules used by this dashboard and create one chart. */
export function initTrendChart(element: HTMLDivElement): echarts.EChartsType {
  if (!registered) {
    echarts.use([
      LineChart,
      BarChart,
      GridComponent,
      LegendComponent,
      TooltipComponent,
      CanvasRenderer,
    ]);
    registered = true;
  }
  return echarts.init(element, undefined, {renderer: "canvas"});
}

export const initTrafficChart = initTrendChart;
