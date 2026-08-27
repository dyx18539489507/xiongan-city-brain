import {describe, expect, it} from "vitest";
import {resolveScenarioRuntimeParameters} from "./scenarioRuntime";
import {isActiveRealtimeSnapshot} from "./realtimeSnapshot";
import {comparisonStartBlocked, liveConfigurationLocked, liveStartBlocked, pairedRuntimeOnline, replayOptionLabel, startupPhaseLabel} from "./components/SimulationCommandCenter";
import {congestionColor} from "./components/TopologyView";
import type {Scenario} from "./types";

const scenario = (input: Partial<Scenario> & Pick<Scenario, "scenario_id">): Scenario => ({
  display_name: input.scenario_id,
  provenance: "openstreetmap_plus_modeled_parameters",
  is_real_measured_network: false,
  runnable: true,
  profiles: [],
  ...input,
});

describe("scenario runtime parameters", () => {
  it("keeps generated OSM scenes on their authoritative random seed and 180 second duration", () => {
    const runtime = resolveScenarioRuntimeParameters(
      [scenario({scenario_id: "generated-osm", seed: 1752234584, duration_s: 180})],
      "generated-osm",
      {seed: 42, durationS: 1800},
      {seed: 7, durationS: 3600},
    );

    expect(runtime).toEqual({seed: 1752234584, durationS: 180});
  });

  it("preserves configurable runtime controls for non-generated scenarios", () => {
    const runtime = resolveScenarioRuntimeParameters(
      [scenario({scenario_id: "reference", seed: 42, duration_s: 1800})],
      "reference",
      {seed: 42, durationS: 1800},
      {seed: 9, durationS: 900},
    );

    expect(runtime).toEqual({seed: 9, durationS: 900});
  });
});

describe("realtime snapshot ownership", () => {
  it("ignores stale global frames after a runtime reset", () => {
    expect(isActiveRealtimeSnapshot(null, "exp-old")).toBe(false);
    expect(isActiveRealtimeSnapshot("exp-current", "exp-old")).toBe(false);
    expect(isActiveRealtimeSnapshot("exp-current", "exp-current")).toBe(true);
  });
});

describe("traffic state colors", () => {
  it("keeps unrun and congestion levels distinguishable", () => {
    expect(congestionColor(null)).toBe("#54717f");
    expect(congestionColor(0.2)).toBe("#35d5b3");
    expect(congestionColor(0.7)).toBe("#e7ba63");
    expect(congestionColor(0.9)).toBe("#ff8b5c");
  });
});

describe("live experiment start guard", () => {
  it("blocks duplicate starts while a created experiment is becoming live", () => {
    expect(liveStartBlocked("exp-1", "idle")).toBe(true);
    expect(liveStartBlocked("exp-1", "starting")).toBe(true);
    expect(liveStartBlocked("exp-1", "running")).toBe(true);
  });

  it("allows resume or a new experiment after a terminal state", () => {
    expect(liveStartBlocked("exp-1", "paused")).toBe(false);
    expect(liveStartBlocked("exp-1", "completed")).toBe(false);
    expect(liveStartBlocked(null, "idle")).toBe(false);
  });
});

describe("live configuration guard", () => {
  it("keeps the launched configuration locked through pause", () => {
    expect(liveConfigurationLocked("exp-1", "starting")).toBe(true);
    expect(liveConfigurationLocked("exp-1", "running")).toBe(true);
    expect(liveConfigurationLocked("exp-1", "paused")).toBe(true);
  });

  it("unlocks after the run reaches a terminal state", () => {
    expect(liveConfigurationLocked("exp-1", "stopped")).toBe(false);
    expect(liveConfigurationLocked("exp-1", "completed")).toBe(false);
    expect(liveConfigurationLocked("exp-1", "invalid")).toBe(false);
    expect(liveConfigurationLocked(null, "idle")).toBe(false);
  });
});

describe("paired comparison start guard", () => {
  it("allows a configured pair to start after page reconnection", () => {
    expect(comparisonStartBlocked("pair-1", "configured")).toBe(false);
    expect(comparisonStartBlocked("pair-1", "created")).toBe(false);
  });

  it("blocks duplicate starts after either SUMO begins advancing", () => {
    expect(comparisonStartBlocked("pair-1", "starting")).toBe(true);
    expect(comparisonStartBlocked("pair-1", "running")).toBe(true);
  });

  it("allows a replacement pair after the previous comparison becomes invalid", () => {
    expect(comparisonStartBlocked("pair-1", "invalid")).toBe(false);
  });
});

describe("paired comparison startup feedback", () => {
  it("uses concise labels for startup and first-frame waiting phases", () => {
    expect(startupPhaseLabel("准备运行环境")).toBe("启动中");
    expect(startupPhaseLabel("启动双路 SUMO")).toBe("启动中");
    expect(startupPhaseLabel("等待 TraCI 首帧")).toBe("等待中");
  });

  it("does not report online before both SUMO streams initialize", () => {
    expect(pairedRuntimeOnline("online", false)).toBe(false);
    expect(pairedRuntimeOnline("connecting", true)).toBe(false);
    expect(pairedRuntimeOnline("online", true)).toBe(true);
  });
});

describe("replay option labels", () => {
  it("remain unique when algorithm, profile and seed repeat", () => {
    const shared = {
      scenarioId: "xiongan_rongdong_20",
      simulationTimeS: 60,
      status: "completed",
      frameCount: 10,
      bytes: 1024,
      createdAt: "2026-08-23T10:30:00+08:00",
      url: "/replay",
      algorithm: "fixed-time",
      profile: "BASE",
      seed: 42,
    };
    const first = replayOptionLabel({...shared, experimentId: "exp-abcdef-one"});
    const second = replayOptionLabel({...shared, experimentId: "exp-123456-two"});
    expect(first).not.toBe(second);
    expect(first).toContain("abcdef");
    expect(second).toContain("123456");
  });
});
