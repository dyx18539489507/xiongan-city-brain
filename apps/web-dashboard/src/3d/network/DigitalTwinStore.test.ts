import {describe, expect, it} from "vitest";
import {
  applyDigitalTwinMessage,
  DigitalTwinSequenceGapError,
  emptyDigitalTwinState,
  parseDigitalTwinMessage,
} from "./DigitalTwinStore";
import type {
  DigitalTwinDelta,
  DigitalTwinInit,
  PedestrianEntity,
  VehicleEntity,
} from "./digitalTwinTypes";

const car: VehicleEntity = {
  id: "car-1",
  type: "passenger_car",
  vehicleClass: "passenger",
  x: 10,
  y: 20,
  angle: 359,
  speed: 8,
  acceleration: -0.8,
  laneId: "edge-a_0",
  edgeId: "edge-a",
  routeId: "route-a",
  signals: 8,
  color: "#123456",
  brake: true,
  status: "moving",
};

const bicycle: VehicleEntity = {
  ...car,
  id: "bike-1",
  type: "electric_bicycle",
  vehicleClass: "bicycle",
};

const pedestrian: PedestrianEntity = {
  id: "person-1",
  type: "pedestrian",
  x: 4,
  y: 6,
  angle: 90,
  speed: 1.2,
  laneId: ":tls_c0_0",
  edgeId: ":tls_c0",
  crossingId: ":tls_c0",
  waitingAreaId: null,
  status: "walking",
};

function init(): DigitalTwinInit {
  return {
    type: "init",
    protocolVersion: "1.0",
    sequence: 7,
    status: "running",
    experimentId: "exp-1",
    scenarioId: "xiongan_rongdong_20",
    simulationTimeS: 10,
    tickHz: 1,
    scene: {
      sceneId: "xiongan_rongdong_20",
      schemaVersion: "1.1",
      url: "/api/v1/scenes/xiongan_rongdong_20/3d",
      sha256: "abc",
      bytes: 100,
      counts: {trafficLights: 20},
    },
    vehicleTypes: ["passenger_car", "electric_bicycle"],
    entities: {vehicles: [car], bicycles: [bicycle], pedestrians: [pedestrian]},
    trafficLights: [
      {id: "tls-a", phaseIndex: 0, state: "Gr", phaseDurationS: 30, remainingS: 5},
    ],
    conflicts: [
      {
        id: "conflict-1",
        participantAId: "car-1",
        participantBId: "person-1",
        conflictType: "motor_pedestrian",
        x: 11,
        y: 17.5,
        minimumDistanceM: 1.2,
        relativeSpeedMS: 4.1,
        ttcS: 2.3,
        petS: null,
        severity: "warning",
      },
    ],
    activeEvents: [
      {
        eventId: "active-roadwork",
        simulationTime: 9,
        event: "ROADWORK_LANE_CLOSED",
        detail: "edge-a_0",
        payload: {disturbance_id: "roadwork-1"},
      },
    ],
  };
}

function delta(sequence = 8): DigitalTwinDelta {
  return {
    type: "delta",
    protocolVersion: "1.0",
    sequence,
    experimentId: "exp-1",
    simulationTimeS: 11,
    spawn: {vehicles: [], bicycles: [], pedestrians: []},
    update: {vehicles: [{...car, x: 18}], bicycles: [], pedestrians: []},
    remove: {vehicles: [], bicycles: ["bike-1"], pedestrians: []},
    trafficLights: [
      {id: "tls-a", phaseIndex: 1, state: "yr", phaseDurationS: 3, remainingS: 2},
    ],
    conflicts: [],
    events: [
      {
        eventId: "event-1",
        simulationTime: 11,
        event: "ROADWORK_LANE_CLOSED",
        detail: "edge-a_0",
        payload: {},
      },
    ],
  };
}

describe("DigitalTwinStore", () => {
  it("replaces state from init and applies spawn/update/remove deltas", () => {
    const initialized = applyDigitalTwinMessage(emptyDigitalTwinState, init());
    expect(initialized.vehicles.get("car-1")?.x).toBe(10);
    expect(initialized.bicycles.size).toBe(1);
    expect(initialized.pedestrians.size).toBe(1);
    expect(initialized.events[0]?.event).toBe("ROADWORK_LANE_CLOSED");
    expect(initialized.conflicts[0]?.conflictType).toBe("motor_pedestrian");

    const updated = applyDigitalTwinMessage(initialized, delta());
    expect(updated.sequence).toBe(8);
    expect(updated.vehicles.get("car-1")?.x).toBe(18);
    expect(updated.bicycles.size).toBe(0);
    expect(updated.trafficLights.get("tls-a")?.state).toBe("yr");
    expect(updated.events).toHaveLength(2);
    expect(updated.conflicts).toHaveLength(0);
  });

  it("rejects sequence gaps so the socket can reconnect for a fresh init", () => {
    const initialized = applyDigitalTwinMessage(emptyDigitalTwinState, init());
    expect(() => applyDigitalTwinMessage(initialized, delta(10))).toThrow(
      DigitalTwinSequenceGapError,
    );
  });

  it("rejects malformed or incompatible wire messages", () => {
    expect(() => parseDigitalTwinMessage({...init(), protocolVersion: "2.0"})).toThrow(
      "unsupported digital-twin protocol version",
    );
    expect(() => parseDigitalTwinMessage({...delta(), spawn: {}})).toThrow(
      "spawn.vehicles must be an array",
    );
  });
});
