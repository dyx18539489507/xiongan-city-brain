import * as THREE from "three";

export type ShadowBudgetSnapshot = {
  enabled: boolean;
  casters: number;
  maxCasters: number;
};

export class ShadowBudgetManager {
  private readonly candidates: THREE.Object3D[] = [];
  private readonly previous = new Set<THREE.Object3D>();
  private frame = 0;
  private casters = 0;
  private enabled = true;

  constructor(
    private readonly maxCasters = 8,
    private readonly maxDistanceM = 80,
    private readonly updateIntervalFrames = 15,
  ) {}

  capture(root: THREE.Object3D): void {
    this.candidates.length = 0;
    root.traverse((object) => {
      if (object.userData.entityKind === "vehicle" && object.userData.entityId) {
        this.candidates.push(object);
      }
    });
  }

  setEnabled(enabled: boolean): void {
    this.enabled = enabled;
    if (!enabled) this.clear();
  }

  update(camera: THREE.Camera): void {
    this.frame += 1;
    if (!this.enabled || this.frame % Math.max(1, this.updateIntervalFrames) !== 0) return;
    this.clear();
    const selected = this.candidates
      .filter((object) => object.visible)
      .map((object) => ({object, distance: object.position.distanceTo(camera.position)}))
      .filter((item) => item.distance <= this.maxDistanceM)
      .sort((left, right) => left.distance - right.distance)
      .slice(0, this.maxCasters);
    for (const {object} of selected) {
      object.traverse((child) => {
        if (child instanceof THREE.Mesh) child.castShadow = true;
      });
      this.previous.add(object);
    }
    this.casters = selected.length;
  }

  snapshot(): ShadowBudgetSnapshot {
    return {enabled: this.enabled, casters: this.casters, maxCasters: this.maxCasters};
  }

  dispose(): void {
    this.clear();
    this.candidates.length = 0;
  }

  private clear(): void {
    for (const object of this.previous) {
      object.traverse((child) => {
        if (child instanceof THREE.Mesh) child.castShadow = false;
      });
    }
    this.previous.clear();
    this.casters = 0;
  }
}
