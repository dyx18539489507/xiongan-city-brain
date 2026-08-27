import {describe, expect, it} from "vitest";
import type {ExperimentState} from "./api";
import {canReuseExperiment} from "./experimentReuse";

function state(status: string, scenarioId = "generated-osm"): ExperimentState {
  return {
    id: "exp-1",
    status,
    request: {
      scenario_id: scenarioId,
      profile: "BASE",
      algorithm: "fixed-time",
      seed: 42,
      duration_s: 180,
    },
  };
}

describe("canReuseExperiment", () => {
  it.each(["starting", "running", "paused"])("reuses a %s run for the same scene", (status) => {
    expect(canReuseExperiment(state(status), "generated-osm")).toBe(true);
  });

  it("does not reuse a completed run or a different scene", () => {
    expect(canReuseExperiment(state("completed"), "generated-osm")).toBe(false);
    expect(canReuseExperiment(state("running", "other"), "generated-osm")).toBe(false);
  });
});
