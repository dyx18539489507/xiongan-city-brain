import * as THREE from "three";

export type LODConfig = {
  schemaVersion: string;
  nearHeightM: number;
  farHeightM: number;
  nearHysteresisM: number;
  farHysteresisM: number;
  settleDelayMs: number;
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
  private initialized = false;
  private lastCameraMotionMs = Number.NEGATIVE_INFINITY;

  constructor(private readonly config: LODConfig) {
    const nearExitHeightM = config.nearHeightM + config.nearHysteresisM;
    const farExitHeightM = config.farHeightM - config.farHysteresisM;
    if (
      config.nearHeightM <= 0 ||
      config.farHeightM <= config.nearHeightM ||
      config.nearHysteresisM < 0 ||
      config.farHysteresisM < 0 ||
      nearExitHeightM >= farExitHeightM ||
      config.settleDelayMs < 0
    ) {
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

  notifyCameraMotion(frameTimeMs = performance.now()): void {
    this.lastCameraMotionMs = frameTimeMs;
  }

  update(
    camera: THREE.Camera,
    frameTimeMs = performance.now(),
    force = false,
  ): boolean {
    this.frame += 1;
    if (!force) {
      if (frameTimeMs - this.lastCameraMotionMs < this.config.settleDelayMs) return false;
      if (this.frame % Math.max(1, this.config.updateIntervalFrames) !== 0) return false;
    }
    const height = Math.abs(camera.position.y);
    const nextTier = this.nextTier(height);
    if (this.initialized && nextTier === this.tier) return false;
    this.initialized = true;
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

  private nextTier(heightM: number): StaticLODSnapshot["tier"] {
    if (!this.initialized) {
      if (heightM >= this.config.farHeightM) return "far";
      if (heightM >= this.config.nearHeightM) return "mid";
      return "near";
    }

    const nearEnterHeightM = this.config.nearHeightM - this.config.nearHysteresisM;
    const nearExitHeightM = this.config.nearHeightM + this.config.nearHysteresisM;
    const farEnterHeightM = this.config.farHeightM + this.config.farHysteresisM;
    const farExitHeightM = this.config.farHeightM - this.config.farHysteresisM;

    if (this.tier === "near") {
      if (heightM >= farEnterHeightM) return "far";
      return heightM >= nearExitHeightM ? "mid" : "near";
    }
    if (this.tier === "far") {
      if (heightM <= nearEnterHeightM) return "near";
      return heightM <= farExitHeightM ? "mid" : "far";
    }
    if (heightM <= nearEnterHeightM) return "near";
    if (heightM >= farEnterHeightM) return "far";
    return "mid";
  }
}
