import * as THREE from "three";
import {describe, expect, it} from "vitest";
import {LODManager} from "./LODManager";

const config = {
  schemaVersion: "test",
  nearHeightM: 100,
  farHeightM: 300,
  nearHysteresisM: 20,
  farHysteresisM: 40,
  settleDelayMs: 300,
  updateIntervalFrames: 1,
  nearOnlyNames: ["near-detail"],
  farHiddenNames: ["far-detail"],
};

describe("LODManager", () => {
  it("removes small details at configured camera heights", () => {
    const root = new THREE.Group();
    const near = new THREE.Group();
    near.name = "near-detail";
    const far = new THREE.Group();
    far.name = "far-detail";
    root.add(near, far);
    const manager = new LODManager(config);
    manager.capture(root);
    const camera = new THREE.PerspectiveCamera();
    camera.position.y = 150;
    manager.update(camera, 0, true);
    expect(near.visible).toBe(false);
    expect(far.visible).toBe(true);
    camera.position.y = 330;
    manager.update(camera, 1);
    expect(manager.snapshot().tier).toBe("mid");
    camera.position.y = 341;
    manager.update(camera, 2);
    expect(far.visible).toBe(false);
    expect(manager.snapshot().tier).toBe("far");
  });

  it("uses separate enter and exit heights around both boundaries", () => {
    const manager = new LODManager(config);
    const camera = new THREE.PerspectiveCamera();
    camera.position.y = 70;
    manager.update(camera, 0, true);
    expect(manager.snapshot().tier).toBe("near");

    camera.position.y = 115;
    manager.update(camera, 1);
    expect(manager.snapshot().tier).toBe("near");
    camera.position.y = 121;
    manager.update(camera, 2);
    expect(manager.snapshot().tier).toBe("mid");
    camera.position.y = 85;
    manager.update(camera, 3);
    expect(manager.snapshot().tier).toBe("mid");
    camera.position.y = 79;
    manager.update(camera, 4);
    expect(manager.snapshot().tier).toBe("near");

    camera.position.y = 350;
    manager.update(camera, 5);
    expect(manager.snapshot().tier).toBe("far");
    camera.position.y = 270;
    manager.update(camera, 6);
    expect(manager.snapshot().tier).toBe("far");
    camera.position.y = 259;
    manager.update(camera, 7);
    expect(manager.snapshot().tier).toBe("mid");
  });

  it("does not change visibility until camera motion has settled", () => {
    const root = new THREE.Group();
    const near = new THREE.Group();
    near.name = "near-detail";
    root.add(near);
    const manager = new LODManager(config);
    manager.capture(root);
    const camera = new THREE.PerspectiveCamera();
    camera.position.y = 70;
    manager.update(camera, 0, true);

    camera.position.y = 150;
    manager.notifyCameraMotion(100);
    expect(manager.update(camera, 399)).toBe(false);
    expect(near.visible).toBe(true);
    expect(manager.update(camera, 400)).toBe(true);
    expect(near.visible).toBe(false);
  });
});
