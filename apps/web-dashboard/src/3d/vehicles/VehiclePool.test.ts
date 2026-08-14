import {describe, expect, it} from "vitest";
import * as THREE from "three";
import type {AssetManager} from "../assets/AssetManager";
import {VehiclePool} from "./VehiclePool";

describe("VehiclePool far instances", () => {
  it("batches far vehicles while preserving per-instance selection metadata", () => {
    const pool = new VehiclePool(
      8,
      [90, 260],
      {
        asset: "/unused.glb",
        baseYawRad: 0,
        groundOffsetM: 0,
        dimensionsM: [4.6, 1.8, 2],
      },
      {} as AssetManager,
    );
    pool.beginFarFrame();
    pool.appendFarInstance(
      "veh-1",
      new THREE.Vector3(10, 0, 20),
      new THREE.Quaternion(),
      new THREE.Vector3(1, 1, 1),
      "#ff0000",
    );
    pool.appendFarInstance(
      "veh-2",
      new THREE.Vector3(30, 0, 40),
      new THREE.Quaternion(),
      new THREE.Vector3(1, 1, 1),
      "#00ff00",
    );
    pool.endFarFrame();

    expect(pool.farInstances.count).toBe(2);
    expect(pool.farInstances.userData.instanceEntities).toEqual([
      {kind: "vehicle", id: "veh-1"},
      {kind: "vehicle", id: "veh-2"},
    ]);
    const matrix = new THREE.Matrix4();
    pool.farInstances.getMatrixAt(1, matrix);
    const position = new THREE.Vector3();
    position.setFromMatrixPosition(matrix);
    expect(position.x).toBeCloseTo(30);
    expect(position.z).toBeCloseTo(40);

    pool.beginFarFrame();
    pool.endFarFrame();
    expect(pool.farInstances.count).toBe(0);
    expect(pool.farInstances.userData.instanceEntities).toEqual([]);
    pool.dispose();
  });
});
