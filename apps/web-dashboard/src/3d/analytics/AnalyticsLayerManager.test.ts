import {describe, expect, it} from "vitest";
import {CoordinateService} from "../core/CoordinateService";
import type {VehicleEntity} from "../network/digitalTwinTypes";
import type {SceneLane} from "../scene/types";
import {AnalyticsLayerManager} from "./AnalyticsLayerManager";

const coordinates = new CoordinateService({
  units: "m",
  projection: "+proj=utm +zone=50",
  utmZone: 50,
  northernHemisphere: true,
  netOffset: {x: 0, y: 0},
  worldOriginSumo: {x: 0, y: 0},
});
const lane: SceneLane = {
  sceneId: "lane:edge_0",
  sumoLaneId: "edge_0",
  sumoEdgeId: "edge",
  index: 0,
  edgeFunction: "ordinary",
  laneKind: "motor",
  shape: [{x: 0, y: 0}, {x: 20, y: 0}],
  widthM: 3.2,
};

function vehicle(id: string, speed: number, status: VehicleEntity["status"]): VehicleEntity {
  return {
    id,
    type: "passenger",
    vehicleClass: "passenger",
    x: 10,
    y: 0,
    angle: 90,
    speed,
    acceleration: 0,
    laneId: "edge_0",
    edgeId: "edge",
    routeId: "route",
    signals: 0,
    color: "255,255,255",
    brake: status === "waiting",
    status,
  };
}

describe("AnalyticsLayerManager", () => {
  it("derives congestion and queue markers only from real entity state", () => {
    const manager = new AnalyticsLayerManager(coordinates, [lane]);
    manager.applySnapshot(new Map([
      ["a", vehicle("a", 0.1, "waiting")],
      ["b", vehicle("b", 0.2, "waiting")],
      ["c", vehicle("c", 1.1, "moving")],
    ]));
    expect(manager.stats.activeLanes).toBe(1);
    expect(manager.stats.severeLanes).toBe(1);
    expect(manager.stats.queuedVehicles).toBe(2);
    expect(manager.stats.lineSegments).toBe(3);
    expect(manager.stats.queueMarkers).toBe(1);
    expect(manager.stats.greenWaveSegments).toBe(0);

    manager.applySnapshot(new Map());
    expect(manager.stats.activeLanes).toBe(0);
    expect(manager.stats.lineSegments).toBe(0);
    expect(manager.stats.queueMarkers).toBe(0);
    manager.dispose();
  });
});
