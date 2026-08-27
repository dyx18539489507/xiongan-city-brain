import {describe, expect, it} from "vitest";
import type {BenchmarkRecord} from "../api";
import {
  ALGORITHM_ORDER,
  benchmarkEvaluationWindow,
  b3PairwiseImprovements,
  orderedAlgorithmMetrics,
  verdictShowsBest,
} from "./AlgorithmEvaluationWorkspace";

function benchmarkRecord(overrides: Partial<BenchmarkRecord["result"]> = {}): BenchmarkRecord {
  return {
    id: "benchmark-test",
    status: "completed",
    progress: 100,
    message: "completed",
    request: {algorithms: [...ALGORITHM_ORDER], seeds: [11, 23, 37], duration_s: 120, warmup_s: 600},
    completed_runs: 12,
    total_runs: 12,
    rows: [],
    created_at: "2026-08-25T00:00:00Z",
    result: {
      actual_run: true,
      fairness_controls: {
        same_network: true,
        same_od_and_departures_within_seed: true,
        same_vehicle_types: true,
        same_duration: true,
        same_disturbances: true,
        same_warmup_state: true,
        only_algorithm_changes: true,
      },
      algorithms: [...ALGORITHM_ORDER],
      seeds: [11, 23, 37],
      duration_s: 120,
      warmup_s: 600,
      rows: [],
      aggregate_95ci: {
        "fixed-time": {mean_speed: {n: 3, mean: 7, standard_deviation: 0.1, ci95_low: 6.8, ci95_high: 7.2}},
        "actuated-control": {mean_speed: {n: 3, mean: 8, standard_deviation: 0.1, ci95_low: 7.8, ci95_high: 8.2}},
        "coordinated-max-pressure": {mean_speed: {n: 3, mean: 10, standard_deviation: 0.1, ci95_low: 9.8, ci95_high: 10.2}},
      },
      input_fingerprints: {"11": ["same"], "23": ["same"], "37": ["same"]},
      rankings: {},
      b3_pairwise: {
        "fixed-time": {
          mean_speed: {n: 3, baseline_mean: 7, b3_mean: 10, improvement_percent: 42.9, ci95_low: 30, ci95_high: 55, win_count: 3, win_rate: 1, status: "significant_improvement"},
        },
        "actuated-control": {
          mean_speed: {n: 3, baseline_mean: 8, b3_mean: 10, improvement_percent: 25, ci95_low: 15, ci95_high: 35, win_count: 3, win_rate: 1, status: "significant_improvement"},
        },
        "max-pressure": {
          mean_speed: {n: 3, baseline_mean: 9, b3_mean: 10, improvement_percent: 11.1, ci95_low: 5, ci95_high: 17, win_count: 3, win_rate: 1, status: "significant_improvement"},
        },
      },
      b3_verdict: {status: "best", label: "B3 综合最优", seed_count: 3, checks: []},
      ...overrides,
    },
  };
}

describe("algorithm evaluation data mapping", () => {
  it("formats the shared warmup and relative evaluation window", () => {
    expect(benchmarkEvaluationWindow(600, 300)).toBe("预热 0→600s / 评估 601→900s");
  });

  it("keeps B0-B3 in fixed order and represents missing runs as null", () => {
    const values = orderedAlgorithmMetrics(benchmarkRecord(), "mean_speed");

    expect(values.map((entry) => entry.algorithm)).toEqual(ALGORITHM_ORDER);
    expect(values.map((entry) => entry.value)).toEqual([7, 8, null, 10]);
  });

  it("maps B3 improvement against B0, B1, and B2 in baseline order", () => {
    const values = b3PairwiseImprovements(benchmarkRecord(), "mean_speed");

    expect(values.map((entry) => entry.value)).toEqual([42.9, 25, 11.1]);
  });

  it("uses the 1800 second complete-scene label without changing the shared warmup", () => {
    expect(benchmarkEvaluationWindow(600, 1800)).toBe("预热 0→600s / 评估 601→2400s");
  });

  it("never displays the best verdict when fairness controls fail", () => {
    const fair = benchmarkRecord();
    const unfair = benchmarkRecord({
      fairness_controls: {...fair.result!.fairness_controls, only_algorithm_changes: false},
    });

    expect(verdictShowsBest(fair)).toBe(true);
    expect(verdictShowsBest(unfair)).toBe(false);
  });
});
