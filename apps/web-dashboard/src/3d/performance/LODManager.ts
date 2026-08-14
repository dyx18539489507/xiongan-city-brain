import * as THREE from "three";

export type LODConfig = {
  schemaVersion: string;
  nearHeightM: number;
  farHeightM: number;
  updateIntervalFrames: number;
  nearOnlyNames: string[];
  farHiddenNames: string[];
};

export type StaticLODSnapshot = {
  tier: "near" | "mid" | "far";
  managedObjects: number;
  hiddenObjects: number;
};

export class LODManager {
  private readonly nearOnly: THREE.Object3D[] = [];
  private readonly farHidden: THREE.Object3D[] = [];
  private frame = 0;
  private tier: StaticLODSnapshot["tier"] = "near";

  constructor(private readonly config: LODConfig) {
    if (config.nearHeightM <= 0 || config.farHeightM <= config.nearHeightM) {
      throw new Error("static LOD thresholds are invalid");
    }
  }

  capture(root: THREE.Object3D): void {
    this.nearOnly.length = 0;
    this.farHidden.length = 0;
    const nearNames = new Set(this.config.nearOnlyNames);
    const farNames = new Set(this.config.farHiddenNames);
    root.traverse((object) => {
      if (nearNames.has(object.name)) this.nearOnly.push(object);
      if (farNames.has(object.name)) this.farHidden.push(object);
    });
  }

  update(camera: THREE.Camera): boolean {
    this.frame += 1;
    if (this.frame % Math.max(1, this.config.updateIntervalFrames) !== 0) return false;
    const height = Math.abs(camera.position.y);
    const nextTier = height >= this.config.farHeightM
      ? "far"
      : height >= this.config.nearHeightM
        ? "mid"
        : "near";
    if (nextTier === this.tier) return false;
    this.tier = nextTier;
    const showNear = nextTier === "near";
    const showFarDetails = nextTier !== "far";
    for (const object of this.nearOnly) object.visible = showNear;
    for (const object of this.farHidden) object.visible = showFarDetails;
    return true;
  }

  snapshot(): StaticLODSnapshot {
    const managed = new Set([...this.nearOnly, ...this.farHidden]);
    return {
      tier: this.tier,
      managedObjects: managed.size,
      hiddenObjects: [...managed].filter((object) => !object.visible).length,
    };
  }
}
