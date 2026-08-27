import {describe, expect, it} from "vitest";
import {
  applyPairedDigitalTwinMessage,
  emptyPairedDigitalTwinState,
  parsePairedDigitalTwinMessage,
} from "./ComparisonDigitalTwinStore";

function inner(experimentId: string, simulationTimeS: number) {
  return {
    type: "init",
    protocolVersion: "1.0",
    sequence: 1,
    status: "running",
    experimentId,
    scenarioId: "scene",
    simulationTimeS,
    tickHz: 1,
    scene: {sceneId: "scene", schemaVersion: "1.1", url: "/scene", sha256: "a", bytes: 1, counts: {}},
    vehicleTypes: [],
    entities: {vehicles: [], bicycles: [], pedestrians: []},
    trafficLights: [],
    activeEvents: [],
    metrics: {},
    intersectionMetrics: [],
  };
}

function message(baselineTime = 1, candidateTime = 1) {
  return {
    type: "comparison-init",
    protocolVersion: "1.0",
    sequence: 1,
    status: "running",
    pairId: "pair-1",
    simulationTimeS: baselineTime,
    fairnessFingerprint: "fingerprint",
    fairnessManifest: {seed: 42},
    baseline: {role: "baseline", algorithm: "fixed-time", experimentId: "base", message: inner("base", baselineTime)},
    candidate: {role: "candidate", algorithm: "max-pressure", experimentId: "candidate", message: inner("candidate", candidateTime)},
    comparison: {valid: true, reason: "建立对照基线", verdict: "warming_up", window_s: 60, paired_sample_count: 1, network: {}, intersections: []},
  };
}

describe("paired digital-twin store", () => {
  it("applies both streams from one atomic initialization", () => {
    const parsed = parsePairedDigitalTwinMessage(message());
    const state = applyPairedDigitalTwinMessage(emptyPairedDigitalTwinState, parsed);

    expect(state.initialized).toBe(true);
    expect(state.baseline.experimentId).toBe("base");
    expect(state.candidate.experimentId).toBe("candidate");
    expect(state.fairnessManifest.seed).toBe(42);
  });

  it("rejects streams from different simulation times", () => {
    expect(() => parsePairedDigitalTwinMessage(message(1, 2))).toThrow(
      "do not share one simulation time",
    );
  });
});
