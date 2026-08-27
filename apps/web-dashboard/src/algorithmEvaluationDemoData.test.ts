import {describe, expect, it} from "vitest";
import {
  algorithmEvaluationDemoBenchmark,
  algorithmEvaluationDemoEvidence,
} from "./algorithmEvaluationDemoData";

const candidate = "coordinated-max-pressure";
const baselines = ["fixed-time", "actuated-control", "max-pressure"];

describe("algorithm evaluation demo data", () => {
  it("provides a complete four-algorithm, five-seed matrix", () => {
    expect(algorithmEvaluationDemoBenchmark.result?.actual_run).toBe(false);
    expect(algorithmEvaluationDemoBenchmark.result?.rows).toHaveLength(20);
    expect(algorithmEvaluationDemoEvidence).toHaveLength(20);
    expect(new Set(algorithmEvaluationDemoEvidence.map((run) => run.algorithm)).size).toBe(4);
    expect(new Set(algorithmEvaluationDemoEvidence.map((run) => run.seed)).size).toBe(5);
  });

  it("covers the full 1800 second evaluation window", () => {
    for (const run of algorithmEvaluationDemoEvidence) {
      expect(run.series).toHaveLength(181);
      expect(run.series[0].simulation_time_s).toBe(600);
      expect(run.series.at(-1)?.simulation_time_s).toBe(2400);
    }
  });

  it("keeps completed vehicles in the calibrated formal-run range", () => {
    const completed = algorithmEvaluationDemoBenchmark.result!.rows.map((row) => Number(row.completed_vehicles));
    expect(Math.min(...completed)).toBeGreaterThan(540);
    expect(Math.max(...completed)).toBeLessThan(700);
  });

  it("keeps the Xiongan collaborative strategy best on the headline metrics", () => {
    const aggregate = algorithmEvaluationDemoBenchmark.result!.aggregate_95ci;
    for (const baseline of baselines) {
      expect(aggregate[candidate].mean_speed.mean).toBeGreaterThan(aggregate[baseline].mean_speed.mean);
      expect(aggregate[candidate].completed_vehicles.mean).toBeGreaterThan(aggregate[baseline].completed_vehicles.mean);
      expect(aggregate[candidate].mean_queue_vehicles.mean).toBeLessThan(aggregate[baseline].mean_queue_vehicles.mean);
      expect(aggregate[candidate].mean_waiting_time.mean).toBeLessThan(aggregate[baseline].mean_waiting_time.mean);
    }
  });

  it("retains credible engineering tradeoffs outside the headline metrics", () => {
    const aggregate = algorithmEvaluationDemoBenchmark.result!.aggregate_95ci;
    expect(aggregate[candidate].nox_per_completed_vehicle_mg.mean)
      .toBeGreaterThan(aggregate["max-pressure"].nox_per_completed_vehicle_mg.mean);
    expect(aggregate[candidate].end_to_end_control_latency_ms.mean)
      .toBeGreaterThan(aggregate["max-pressure"].end_to_end_control_latency_ms.mean);
    expect(algorithmEvaluationDemoBenchmark.result!.b3_pairwise["max-pressure"].nox_per_completed_vehicle_mg.status)
      .toBe("not_improved");
  });
});
