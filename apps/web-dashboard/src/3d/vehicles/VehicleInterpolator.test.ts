import * as THREE from "three";
import {describe, expect, it} from "vitest";
import {VehicleInterpolator} from "./VehicleInterpolator";

describe("VehicleInterpolator", () => {
  it("interpolates position across a SUMO tick", () => {
    const interpolator = new VehicleInterpolator();
    const identity = new THREE.Quaternion();
    interpolator.snap(new THREE.Vector3(0, 0, 0), identity, 1_000);
    interpolator.retarget(new THREE.Vector3(10, 0, 0), identity, 1_000, 1_000);
    const output = {position: new THREE.Vector3(), quaternion: new THREE.Quaternion()};
    interpolator.sample(1_500, output);
    expect(output.position.x).toBeCloseTo(5, 8);
  });

  it("uses quaternion slerp for the shortest 359 to 1 degree turn", () => {
    const interpolator = new VehicleInterpolator();
    const start = new THREE.Quaternion().setFromAxisAngle(
      new THREE.Vector3(0, 1, 0),
      THREE.MathUtils.degToRad(359),
    );
    const end = new THREE.Quaternion().setFromAxisAngle(
      new THREE.Vector3(0, 1, 0),
      THREE.MathUtils.degToRad(1),
    );
    interpolator.snap(new THREE.Vector3(), start, 0);
    interpolator.retarget(new THREE.Vector3(), end, 0, 1_000);
    const output = {position: new THREE.Vector3(), quaternion: new THREE.Quaternion()};
    interpolator.sample(500, output);
    expect(output.quaternion.angleTo(new THREE.Quaternion())).toBeLessThan(
      THREE.MathUtils.degToRad(0.01),
    );
  });
});

