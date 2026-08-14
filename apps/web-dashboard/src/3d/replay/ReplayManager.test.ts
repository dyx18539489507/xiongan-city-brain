import {describe, expect, it} from "vitest";
import type {DigitalTwinDelta, DigitalTwinInit} from "../network/digitalTwinTypes";
import {ReplayManager} from "./ReplayManager";

const entities = {vehicles: [], bicycles: [], pedestrians: []};
const init: DigitalTwinInit = {
  type: "init",
  protocolVersion: "1.0",
  sequence: 1,
  status: "running",
  experimentId: "exp-replay",
  scenarioId: "xiongan_rongdong_20",
  simulationTimeS: 1,
  tickHz: 10,
  scene: {
    sceneId: "xiongan_rongdong_20",
    schemaVersion: "1.1",
    url: "/scene",
    sha256: "abc",
    bytes: 1,
    counts: {},
  },
  vehicleTypes: [],
  entities,
  trafficLights: [],
  metrics: {mean_speed_m_s: 4.5},
  intersectionMetrics: [{intersection_id: "K01", queue_vehicles: 3}],
};
const delta: DigitalTwinDelta = {
  type: "delta",
  protocolVersion: "1.0",
  sequence: 2,
  experimentId: "exp-replay",
  simulationTimeS: 2,
  spawn: entities,
  update: entities,
  remove: {vehicles: [], bicycles: [], pedestrians: []},
  trafficLights: [],
  events: [],
  metrics: {mean_speed_m_s: 5.5},
  intersectionMetrics: [{intersection_id: "K01", queue_vehicles: 2}],
};

describe("ReplayManager", () => {
  it("uses the live protocol reducer for seek, step and timed playback", () => {
    const manager = new ReplayManager();
    manager.loadText(`${JSON.stringify(init)}\n${JSON.stringify(delta)}\n`);
    expect(manager.currentState().simulationTimeS).toBe(1);
    expect(manager.snapshot().frameCount).toBe(2);
    manager.play(2);
    expect(manager.advance(0.5).simulationTimeS).toBe(2);
    expect(manager.currentState().metrics.mean_speed_m_s).toBe(5.5);
    expect(manager.currentState().intersectionMetrics[0]?.queue_vehicles).toBe(2);
    expect(manager.snapshot().playing).toBe(false);
    expect(manager.seek(0).simulationTimeS).toBe(1);
    expect(manager.step().simulationTimeS).toBe(2);
  });

  it("accumulates browser frame time until the next SUMO frame", () => {
    const manager = new ReplayManager();
    manager.loadText(`${JSON.stringify(init)}\n${JSON.stringify(delta)}\n`);
    manager.play(1);
    expect(manager.advance(0.4).simulationTimeS).toBe(1);
    expect(manager.advance(0.6).simulationTimeS).toBe(2);
    expect(manager.snapshot().playing).toBe(false);
  });

  it("rejects a replay without an init truth snapshot", () => {
    const manager = new ReplayManager();
    expect(() => manager.loadText(`${JSON.stringify(delta)}\n`)).toThrow(
      "must start with an init",
    );
  });
});
