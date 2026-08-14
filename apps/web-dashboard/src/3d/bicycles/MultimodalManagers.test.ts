import {describe, expect, it} from "vitest";
import {CoordinateService} from "../core/CoordinateService";
import type {PedestrianEntity, VehicleEntity} from "../network/digitalTwinTypes";
import {PedestrianManager} from "../pedestrians/PedestrianManager";
import {BicycleManager} from "./BicycleManager";

const coordinates = new CoordinateService({
  units: "m",
  projection: "+proj=utm +zone=50",
  utmZone: 50,
  northernHemisphere: true,
  netOffset: {x: 0, y: 0},
  worldOriginSumo: {x: 50, y: 50},
});
const bounds = {minX: 0, minY: 0, maxX: 100, maxY: 100};

const bicycle: VehicleEntity = {
  id: "bike-1",
  type: "bicycle",
  vehicleClass: "bicycle",
  x: 20,
  y: 30,
  angle: 15,
  speed: 3,
  acceleration: 0.2,
  laneId: "bike_0",
  edgeId: "bike",
  routeId: "route",
  signals: 0,
  color: "#20aa88",
  brake: false,
  status: "moving",
};

const pedestrian: PedestrianEntity = {
  id: "ped-1",
  type: "pedestrian",
  x: 22,
  y: 34,
  angle: 90,
  speed: 1.2,
  laneId: "walk_0",
  edgeId: "walk",
  crossingId: null,
  waitingAreaId: null,
  status: "walking",
};

describe("multimodal managers", () => {
  it("allocates, animates, and returns real bicycle and pedestrian entities to pools", () => {
    const bicycles = new BicycleManager(coordinates, bounds);
    const pedestrians = new PedestrianManager(coordinates, bounds);
    bicycles.applySnapshot(new Map([[bicycle.id, bicycle]]), 10, 0);
    pedestrians.applySnapshot(new Map([[pedestrian.id, pedestrian]]), 10, 0);
    bicycles.update(33);
    pedestrians.update(33);
    expect(bicycles.count()).toBe(1);
    expect(pedestrians.count()).toBe(1);

    bicycles.applySnapshot(new Map(), 10, 100);
    pedestrians.applySnapshot(new Map(), 10, 100);
    expect(bicycles.count()).toBe(0);
    expect(pedestrians.count()).toBe(0);
    bicycles.dispose();
    pedestrians.dispose();
  });
});
