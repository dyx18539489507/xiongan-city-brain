import {describe, expect, it} from "vitest";
import {appendSimulationRateSample, calculateEffectiveSimulationRate} from "./simulationRate";

describe("simulation rate measurement", () => {
  it("derives achieved simulation speed from simulation and wall-clock deltas", () => {
    expect(calculateEffectiveSimulationRate([
      {simulationTimeS: 10, wallTimeMs: 1_000},
      {simulationTimeS: 26, wallTimeMs: 3_000},
    ])).toBe(8);
  });

  it("resets the measurement window when simulation time moves backwards", () => {
    const samples = appendSimulationRateSample(
      [{simulationTimeS: 30, wallTimeMs: 2_000}],
      {simulationTimeS: 0, wallTimeMs: 3_000},
    );
    expect(samples).toEqual([{simulationTimeS: 0, wallTimeMs: 3_000}]);
    expect(calculateEffectiveSimulationRate(samples)).toBeNull();
  });

  it("ignores repeated renders of the same simulation frame", () => {
    const original = [{simulationTimeS: 4, wallTimeMs: 1_000}];
    expect(appendSimulationRateSample(original, {simulationTimeS: 4, wallTimeMs: 2_000}))
      .toEqual(original);
  });
});
