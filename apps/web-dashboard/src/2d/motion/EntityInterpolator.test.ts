import {describe, expect, it} from "vitest";
import type {VehicleEntity} from "../../3d/network/digitalTwinTypes";
import {EntityInterpolator} from "./EntityInterpolator";

function vehicle(x: number, angle = 90): VehicleEntity {
  return {
    id: "vehicle-1",
    type: "passenger",
    vehicleClass: "passenger",
    x,
    y: 0,
    angle,
    speed: 10,
    acceleration: 0,
    laneId: "lane-1",
    edgeId: "edge-1",
    routeId: "route-1",
    signals: 0,
    color: "#fff",
    brake: false,
    status: "moving",
  };
}

function states(entity: VehicleEntity): ReadonlyMap<string, VehicleEntity> {
  return new Map([[entity.id, entity]]);
}

describe("EntityInterpolator", () => {
  it("moves at constant visual speed between two SUMO truth frames", () => {
    const interpolator = new EntityInterpolator<VehicleEntity>();
    interpolator.update(states(vehicle(0)), 0, 1);
    interpolator.update(states(vehicle(10)), 1000, 1);

    expect(interpolator.sample(1250)[0].renderX).toBeCloseTo(2.5, 8);
    expect(interpolator.sample(1500)[0].renderX).toBeCloseTo(5, 8);
    expect(interpolator.sample(1750)[0].renderX).toBeCloseTo(7.5, 8);
  });

  it("adapts immediately when the real frame cadence becomes faster", () => {
    const interpolator = new EntityInterpolator<VehicleEntity>();
    interpolator.update(states(vehicle(0)), 0, 1);
    interpolator.update(states(vehicle(10)), 1000, 1);
    interpolator.update(states(vehicle(20)), 1125, 1);

    const halfway = interpolator.sample(1187.5)[0].renderX;
    expect(halfway).toBeGreaterThan(10);
    expect(halfway).toBeLessThan(11);
  });

  it("coalesces MAX-throughput updates into one browser-visible frame window", () => {
    const interpolator = new EntityInterpolator<VehicleEntity>();
    interpolator.update(states(vehicle(0)), 0, 1);
    interpolator.update(states(vehicle(10)), 1000, 1);
    interpolator.update(states(vehicle(20)), 1008, 1);

    const start = interpolator.sample(1008)[0].renderX;
    const halfway = interpolator.sample(1024)[0].renderX;
    expect(halfway).toBeCloseTo(start + (20 - start) / 2, 8);
  });

  it("uses the shortest angle path and snaps discontinuous teleports", () => {
    const turning = new EntityInterpolator<VehicleEntity>();
    turning.update(states(vehicle(0, 359)), 0, 1);
    turning.update(states(vehicle(10, 1)), 1000, 1);
    expect(turning.sample(1500)[0].renderAngle).toBeCloseTo(360, 8);

    const teleporting = new EntityInterpolator<VehicleEntity>();
    teleporting.update(states(vehicle(0)), 0, 1);
    teleporting.update(states(vehicle(100)), 1000, 1);
    expect(teleporting.sample(1001)[0].renderX).toBe(100);
  });

  it("reuses render objects between animation frames and removes departed entities", () => {
    const interpolator = new EntityInterpolator<VehicleEntity>();
    interpolator.update(states(vehicle(0)), 0, 1);
    const firstArray = interpolator.sample(100);
    const firstEntity = firstArray[0];

    interpolator.update(states(vehicle(10)), 1000, 1);
    expect(interpolator.sample(1250)).toBe(firstArray);
    expect(interpolator.sample(1250)[0]).toBe(firstEntity);

    interpolator.update(new Map(), 2000, 1);
    expect(interpolator.sample(2100)).toHaveLength(0);
  });
});
