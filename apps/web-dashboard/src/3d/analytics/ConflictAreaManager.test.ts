import {describe, expect, it} from "vitest";
import {
  CoordinateService,
  type SceneCoordinateSystem,
} from "../core/CoordinateService";
import {ConflictAreaManager} from "./ConflictAreaManager";

const coordinateSystem: SceneCoordinateSystem = {
  units: "m",
  projection: "+proj=utm +zone=50 +datum=WGS84 +units=m +no_defs",
  utmZone: 50,
  northernHemisphere: true,
  netOffset: {x: 0, y: 0},
  worldOriginSumo: {x: 50, y: 50},
};

describe("ConflictAreaManager", () => {
  it("renders only observed conflicts and exposes click identity", () => {
    const manager = new ConflictAreaManager(new CoordinateService(coordinateSystem));
    manager.applySnapshot([
      {
        id: "conflict-1",
        participantAId: "car-1",
        participantBId: "person-1",
        conflictType: "motor_pedestrian",
        x: 55,
        y: 60,
        minimumDistanceM: 1.2,
        relativeSpeedMS: 4,
        ttcS: 2,
        petS: null,
        severity: "warning",
      },
    ]);
    expect(manager.count()).toBe(1);
    expect(manager.root.children[0]?.userData.entityKind).toBe("conflict");
    expect(manager.root.children[0]?.position.toArray()).toEqual([5, 0.19, -10]);
    manager.applySnapshot([]);
    expect(manager.count()).toBe(0);
    manager.dispose();
  });
});
