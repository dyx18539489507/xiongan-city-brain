import {describe, expect, it} from "vitest";
import {CoordinateService} from "./CoordinateService";

const service = new CoordinateService({
  units: "m",
  projection:
    "+proj=utm +zone=50 +ellps=WGS84 +datum=WGS84 +units=m +no_defs",
  utmZone: 50,
  northernHemisphere: true,
  netOffset: {x: -402358.92, y: -4317416.65},
  worldOriginSumo: {x: 3691.65, y: 6515.815},
});

describe("CoordinateService", () => {
  it("round-trips SUMO and Three coordinates without drift", () => {
    const world = service.sumoToWorld(4005.52, 5451.76, 1.2);
    expect(world.x).toBeCloseTo(313.87, 9);
    expect(world.y).toBe(1.2);
    expect(world.z).toBeCloseTo(1064.055, 9);
    const sumo = service.worldToSumo(world.x, world.z);
    expect(sumo.x).toBeCloseTo(4005.52, 9);
    expect(sumo.y).toBeCloseTo(5451.76, 9);
  });

  it("round-trips the registered K06 WGS84 coordinate", () => {
    const lonLat = service.sumoToLonLat(4005.52, 5451.76);
    expect(lonLat.lon).toBeCloseTo(115.9179083104, 6);
    expect(lonLat.lat).toBeCloseTo(39.049875348, 6);
    const sumo = service.lonLatToSumo(lonLat.lon, lonLat.lat);
    expect(sumo.x).toBeCloseTo(4005.52, 3);
    expect(sumo.y).toBeCloseTo(5451.76, 3);
  });

  it("maps SUMO heading to the shortest Three yaw", () => {
    expect(service.sumoAngleToThree(0)).toBeCloseTo(0, 12);
    expect(service.sumoAngleToThree(90)).toBeCloseTo(-Math.PI / 2, 12);
    expect(service.worldAngleToSumo(service.sumoAngleToThree(359))).toBeCloseTo(
      359,
      10,
    );
  });
});
