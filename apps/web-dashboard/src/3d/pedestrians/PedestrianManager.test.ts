import {describe, expect, it} from "vitest";
import * as THREE from "three";
import {CoordinateService} from "../core/CoordinateService";
import type {PedestrianEntity} from "../network/digitalTwinTypes";
import {PedestrianManager} from "./PedestrianManager";

const coordinates = new CoordinateService({
  units: "m",
  projection: "+proj=utm +zone=50",
  utmZone: 50,
  northernHemisphere: true,
  netOffset: {x: 0, y: 0},
  worldOriginSumo: {x: 0, y: 0},
});

describe("PedestrianManager", () => {
  it("uses a bounded near-field skeleton while retaining SUMO as pose truth", () => {
    const manager = new PedestrianManager(
      coordinates,
      {minX: -100, minY: -100, maxX: 100, maxY: 100},
    );
    const entity: PedestrianEntity = {
      id: "person-1",
      type: "pedestrian",
      x: 5,
      y: 8,
      angle: 90,
      speed: 1.2,
      laneId: "walk_0",
      edgeId: "walk",
      crossingId: null,
      waitingAreaId: null,
      status: "walking",
    };
    manager.applySnapshot(new Map([[entity.id, entity]]), 1, 0);
    manager.update(250);

    const skinnedMeshes: THREE.SkinnedMesh[] = [];
    const lods: THREE.LOD[] = [];
    manager.root.traverse((object) => {
      if ((object as THREE.SkinnedMesh).isSkinnedMesh) {
        skinnedMeshes.push(object as THREE.SkinnedMesh);
      }
      if ((object as THREE.LOD).isLOD) lods.push(object as THREE.LOD);
    });
    expect(skinnedMeshes).toHaveLength(4);
    expect(skinnedMeshes.every((mesh) => mesh.skeleton.bones.length === 2)).toBe(true);
    expect(lods[0]?.levels.map((level) => level.distance)).toEqual([0, 25]);
    expect(manager.count()).toBe(1);
    manager.dispose();
  });
});
