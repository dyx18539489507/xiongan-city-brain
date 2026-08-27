import {describe, expect, it} from "vitest";
import {comparisonMetrics, decisionReasons, safetyConflictCount} from "./AlgorithmComparisonDock";

describe("AlgorithmComparisonDock evidence helpers", () => {
  it("keeps every requested comparison metric in the left analysis panel", () => {
    expect(comparisonMetrics.map((item) => item.label)).toEqual([
      "全网排队",
      "平均速度",
      "车辆等待",
      "完成出行",
      "最大排队",
      "行人等待",
      "骑行排队",
      "交通冲突",
    ]);
  });

  it("combines vulnerable-road-user conflict indicators without inventing missing values", () => {
    expect(safetyConflictCount({
      motor_bicycle_conflict_count: 2,
      motor_pedestrian_conflict_count: 3,
      bicycle_pedestrian_conflict_count: 1,
    })).toBe(6);
    expect(safetyConflictCount({})).toBe(0);
  });

  it("turns algorithm reason codes into concise operator evidence", () => {
    expect(decisionReasons({
      decision_reason_codes: [
        "CLOUD_TARGET_APPLIED",
        "POLICY_PORTFOLIO_SELECTED:B3",
        "CURRENT_PRESSURE_DOMINANCE_GUARD",
        "EXTRA_REASON",
      ],
    })).toEqual(["采用云端协调目标", "策略组合选择 B3", "压力保护门限生效"]);
  });
});
