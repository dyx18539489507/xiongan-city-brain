import {describe, expect, it} from "vitest";
import * as THREE from "three";
import {CameraManager} from "./CameraManager";

describe("CameraManager", () => {
  it("uses a duration-based pose transition and reaches the exact endpoint", () => {
    const camera = new THREE.PerspectiveCamera(43, 1, 1, 1000);
    const controls = {target: new THREE.Vector3()};
    const manager = new CameraManager(camera, controls);
    manager.transitionTo({
      position: [10, 20, 30],
      target: [1, 2, 3],
      fov: 50,
      transitionDuration: 1000,
    });
    expect(manager.update(400)).toBe(true);
    expect(camera.position.x).toBeGreaterThan(0);
    expect(manager.update(600)).toBe(false);
    expect(camera.position.toArray()).toEqual([10, 20, 30]);
    expect(controls.target.toArray()).toEqual([1, 2, 3]);
    expect(camera.fov).toBe(50);
  });
});
