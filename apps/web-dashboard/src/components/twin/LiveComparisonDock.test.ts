import {describe, expect, it} from "vitest";
import type {LiveComparisonSummary} from "../../3d/network/comparisonDigitalTwinTypes";
import {comparisonVerdictCopy} from "./LiveComparisonDock";

function summary(verdict: LiveComparisonSummary["verdict"], valid = true): LiveComparisonSummary {
  return {valid, reason: valid ? null : "失步", verdict, window_s: 60, paired_sample_count: 2, network: {}, intersections: []};
}

describe("live comparison verdict copy", () => {
  it("does not claim improvement during warmup", () => {
    expect(comparisonVerdictCopy({...summary("warming_up"), warmup_remaining_s: 31}).title)
      .toBe("建立对照基线");
  });

  it("surfaces invalid pairs instead of retaining an old conclusion", () => {
    expect(comparisonVerdictCopy(summary("invalid", false))).toEqual({
      title: "对照无效",
      detail: "失步",
      tone: "invalid",
    });
  });
});
