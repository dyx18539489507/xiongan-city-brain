import * as THREE from "three";
import {describe, expect, it} from "vitest";
import {LODManager} from "./LODManager";

describe("LODManager", () => {
  it("removes small details at configured camera heights", () => {
    const root = new THREE.Group();
    const near = new THREE.Group();
    near.name = "near-detail";
    const far = new THREE.Group();
    far.name = "far-detail";
    root.add(near, far);
    const manager = new LODManager({
      schemaVersion: "test",
      nearHeightM: 100,
      farHeightM: 300,
      updateIntervalFrames: 1,
      nearOnlyNames: ["near-detail"],
      farHiddenNames: ["far-detail"],
    });
    manager.capture(root);
    const camera = new THREE.PerspectiveCamera();
    camera.position.y = 150;
    manager.update(camera);
    expect(near.visible).toBe(false);
    expect(far.visible).toBe(true);
    camera.position.y = 400;
    manager.update(camera);
    expect(far.visible).toBe(false);
    expect(manager.snapshot().tier).toBe("far");
  });
});
