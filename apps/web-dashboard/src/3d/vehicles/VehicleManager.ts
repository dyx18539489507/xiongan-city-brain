import * as THREE from "three";
import {CoordinateService} from "../core/CoordinateService";
import type {SceneBounds} from "../scene/types";
import type {VehicleEntity} from "../network/digitalTwinTypes";
import {VehicleInterpolator} from "./VehicleInterpolator";
import {AssetManager} from "../assets/AssetManager";
import {
  VehiclePool,
  type PooledVehicle,
  type VehicleModelMapping,
  type VehicleVisualMapping,
} from "./VehiclePool";

type ActiveVehicle = {
  entity: VehicleEntity;
  instance: PooledVehicle;
  modelKey: string;
  pool: VehiclePool;
  interpolator: VehicleInterpolator;
  transform: {position: THREE.Vector3; quaternion: THREE.Quaternion};
  wheelAngleRad: number;
  steerAngleRad: number;
  targetSteerAngleRad: number;
};

const DEFAULT_MAPPING: VehicleModelMapping = {
  schemaVersion: "fallback",
  poolSoftLimit: 192,
  lodDistancesM: [90, 260],
  models: {
    "urban-car": {
      asset: "/assets/k06/k06-vehicle.glb",
      baseYawRad: Math.PI / 2,
      groundOffsetM: 0.02,
    },
  },
  typeMappings: {},
  classMappings: {},
  fallback: {model: "urban-car", scale: [1, 1, 1], temporaryFallback: true},
};

async function loadMapping(): Promise<VehicleModelMapping> {
  try {
    const response = await fetch("/assets/3d/vehicle_model_mapping.json");
    if (!response.ok) throw new Error(`vehicle mapping HTTP ${response.status}`);
    return (await response.json()) as VehicleModelMapping;
  } catch (error: unknown) {
    console.warn("vehicle mapping failed; using built-in safe mapping", error);
    return DEFAULT_MAPPING;
  }
}

export class VehicleManager {
  readonly root = new THREE.Group();
  private mapping: VehicleModelMapping = DEFAULT_MAPPING;
  private readonly pools = new Map<string, VehiclePool>();
  private readonly active = new Map<string, ActiveVehicle>();
  private readonly targetPosition = new THREE.Vector3();
  private readonly targetQuaternion = new THREE.Quaternion();
  private readonly up = new THREE.Vector3(0, 1, 0);
  private initialized = false;
  private lastFrameTimeMs: number | null = null;
  private readonly assets: AssetManager;

  constructor(
    private readonly coordinates: CoordinateService,
    private readonly bounds: SceneBounds,
    private readonly renderer?: THREE.WebGLRenderer,
  ) {
    this.root.name = "SUMOVehicles";
    this.assets = new AssetManager(renderer);
  }

  async initialize(): Promise<void> {
    this.mapping = await loadMapping();
    if (!this.mapping.models[this.mapping.fallback.model]) {
      throw new Error("vehicle mapping fallback model is missing");
    }
    await Promise.all(
      Object.entries(this.mapping.models).map(async ([modelKey, definition]) => {
        const pool = new VehiclePool(
          this.mapping.poolSoftLimit,
          this.mapping.lodDistancesM,
          definition,
          this.assets,
        );
        pool.root.name = `VehiclePool:${modelKey}`;
        await pool.initialize(definition.asset);
        this.pools.set(modelKey, pool);
        this.root.add(pool.root);
      }),
    );
    this.initialized = true;
  }

  applySnapshot(
    entities: ReadonlyMap<string, VehicleEntity>,
    tickHz: number,
    receivedAtMs: number,
  ): void {
    if (!this.initialized) return;
    const visible = new Set<string>();
    const interpolationMs = THREE.MathUtils.clamp(1_000 / Math.max(tickHz, 0.1), 80, 1_500);
    for (const entity of entities.values()) {
      if (!this.withinRenderBounds(entity)) continue;
      visible.add(entity.id);
      const mapping = this.visualMapping(entity);
      const modelKey = this.mapping.models[mapping.model]
        ? mapping.model
        : this.mapping.fallback.model;
      const model = this.mapping.models[modelKey];
      const pool = this.pools.get(modelKey);
      if (!model || !pool) continue;
      let active = this.active.get(entity.id);
      const world = this.coordinates.sumoToWorld(entity.x, entity.y, model.groundOffsetM);
      this.targetPosition.set(world.x, world.y, world.z);
      this.targetQuaternion.setFromAxisAngle(
        this.up,
        this.coordinates.sumoAngleToThree(entity.angle) + model.baseYawRad,
      );
      if (active && active.modelKey !== modelKey) {
        active.pool.release(active.instance);
        this.active.delete(entity.id);
        active = undefined;
      }
      if (!active) {
        const instance = pool.acquire(entity.id);
        instance.root.scale.set(...mapping.scale);
        active = {
          entity,
          instance,
          modelKey,
          pool,
          interpolator: new VehicleInterpolator(),
          transform: {
            position: new THREE.Vector3(),
            quaternion: new THREE.Quaternion(),
          },
          wheelAngleRad: 0,
          steerAngleRad: 0,
          targetSteerAngleRad: 0,
        };
        active.interpolator.snap(this.targetPosition, this.targetQuaternion, receivedAtMs);
        this.active.set(entity.id, active);
      } else {
        const headingDelta = ((entity.angle - active.entity.angle + 540) % 360) - 180;
        active.targetSteerAngleRad = THREE.MathUtils.clamp(
          THREE.MathUtils.degToRad(headingDelta * 0.72),
          -0.46,
          0.46,
        );
        active.interpolator.retarget(
          this.targetPosition,
          this.targetQuaternion,
          receivedAtMs,
          interpolationMs,
        );
        active.entity = entity;
      }
      this.updateMaterials(active.instance, entity);
    }
    for (const [identifier, active] of this.active) {
      if (visible.has(identifier)) continue;
      active.pool.release(active.instance);
      this.active.delete(identifier);
    }
  }

  update(frameTimeMs: number, camera?: THREE.Camera): void {
    const deltaSeconds =
      this.lastFrameTimeMs === null
        ? 0
        : Math.min(0.1, Math.max(0, (frameTimeMs - this.lastFrameTimeMs) / 1_000));
    this.lastFrameTimeMs = frameTimeMs;
    const blinkOn = Math.floor(frameTimeMs / 360) % 2 === 0;
    for (const pool of this.pools.values()) pool.beginFarFrame();
    for (const active of this.active.values()) {
      const transform = active.interpolator.sample(frameTimeMs, active.transform);
      active.instance.root.position.copy(transform.position);
      active.instance.root.quaternion.copy(transform.quaternion);
      const farDistanceM = active.pool.farDistanceM();
      const isFar = Boolean(
        camera && camera.position.distanceToSquared(transform.position) >= farDistanceM ** 2,
      );
      if (isFar) {
        active.instance.root.visible = false;
        active.pool.appendFarInstance(
          active.entity.id,
          transform.position,
          transform.quaternion,
          active.instance.root.scale,
          active.entity.color,
        );
        continue;
      }
      active.instance.root.visible = true;
      active.wheelAngleRad -= (active.entity.speed / 0.39) * deltaSeconds;
      active.steerAngleRad = THREE.MathUtils.lerp(
        active.steerAngleRad,
        active.targetSteerAngleRad,
        0.18,
      );
      for (const wheel of active.instance.wheelSpinGroups) {
        wheel.rotation.z = active.wheelAngleRad;
      }
      for (const wheel of active.instance.frontSteerGroups) {
        wheel.rotation.y = active.steerAngleRad;
      }
      const leftOn = Boolean(active.entity.signals & 2) && blinkOn;
      const rightOn = Boolean(active.entity.signals & 1) && blinkOn;
      for (const material of active.instance.leftIndicatorMaterials) {
        material.emissiveIntensity = leftOn ? 4.2 : 0;
      }
      for (const material of active.instance.rightIndicatorMaterials) {
        material.emissiveIntensity = rightOn ? 4.2 : 0;
      }
      const emergencyOn =
        active.entity.vehicleClass === "emergency" ||
        Boolean(active.entity.signals & (2_048 | 4_096 | 8_192));
      for (const mesh of active.instance.emergencyMeshes) mesh.visible = emergencyOn;
      active.instance.emergencyMaterials.forEach((material, index) => {
        material.emissiveIntensity = emergencyOn && (index + Number(blinkOn)) % 2 === 0 ? 5 : 0;
      });
    }
    for (const pool of this.pools.values()) pool.endFarFrame();
  }

  count(): number {
    return this.active.size;
  }

  dispose(): void {
    this.active.clear();
    for (const pool of this.pools.values()) pool.dispose();
    this.pools.clear();
    this.assets.dispose();
    this.root.clear();
    this.initialized = false;
    this.lastFrameTimeMs = null;
  }

  private withinRenderBounds(entity: VehicleEntity): boolean {
    const margin = 80;
    return (
      entity.x >= this.bounds.minX - margin &&
      entity.x <= this.bounds.maxX + margin &&
      entity.y >= this.bounds.minY - margin &&
      entity.y <= this.bounds.maxY + margin
    );
  }

  private visualMapping(entity: VehicleEntity): VehicleVisualMapping {
    return (
      this.mapping.typeMappings[entity.type] ??
      this.mapping.classMappings[entity.vehicleClass] ??
      this.mapping.fallback
    );
  }

  private updateMaterials(instance: PooledVehicle, entity: VehicleEntity): void {
    const color = new THREE.Color(entity.color);
    for (const material of instance.paintMaterials) material.color.copy(color);
    for (const material of instance.taillightMaterials) {
      material.emissive.set(0xff1808);
      material.emissiveIntensity = entity.brake ? 3.2 : 0.65;
    }
    const headlightsOn = Boolean(entity.signals & 16);
    for (const material of instance.headlightMaterials) {
      material.emissive.set(0xfff2cf);
      material.emissiveIntensity = headlightsOn ? 2.4 : 0.25;
    }
  }
}
