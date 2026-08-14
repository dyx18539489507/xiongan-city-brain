import * as THREE from "three";
import type {CoordinateService} from "../core/CoordinateService";
import type {VehicleEntity} from "../network/digitalTwinTypes";
import type {SceneBounds} from "../scene/types";
import {VehicleInterpolator} from "../vehicles/VehicleInterpolator";

type BicycleVisual = {
  root: THREE.Group;
  lean: THREE.Group;
  wheels: THREE.Group[];
  leftLeg: THREE.Group;
  rightLeg: THREE.Group;
};

type ActiveBicycle = {
  entity: VehicleEntity;
  previousAngle: number;
  targetLean: number;
  wheelAngle: number;
  visual: BicycleVisual;
  interpolator: VehicleInterpolator;
  transform: {position: THREE.Vector3; quaternion: THREE.Quaternion};
};

export class BicycleManager {
  readonly root = new THREE.Group();
  private readonly active = new Map<string, ActiveBicycle>();
  private readonly available: BicycleVisual[] = [];
  private readonly geometries: THREE.BufferGeometry[] = [];
  private readonly materials: THREE.Material[] = [];
  private readonly up = new THREE.Vector3(0, 1, 0);
  private readonly targetPosition = new THREE.Vector3();
  private readonly targetQuaternion = new THREE.Quaternion();
  private readonly farInstances: THREE.InstancedMesh;
  private readonly farInstanceEntities: Array<{kind: "bicycle"; id: string}> = [];
  private readonly farMatrix = new THREE.Matrix4();
  private readonly farPosition = new THREE.Vector3();
  private readonly farScale = new THREE.Vector3(1, 1, 1);
  private lastFrameTimeMs: number | null = null;

  constructor(
    private readonly coordinates: CoordinateService,
    private readonly bounds: SceneBounds,
    private readonly softLimit = 128,
  ) {
    this.root.name = "SUMOBicycles";
    this.geometries.push(
      new THREE.TorusGeometry(0.34, 0.038, 6, 14),
      new THREE.BoxGeometry(0.12, 0.58, 1.42),
      new THREE.BoxGeometry(0.52, 0.08, 0.09),
      new THREE.CapsuleGeometry(0.16, 0.48, 4, 8),
      new THREE.SphereGeometry(0.15, 9, 7),
      new THREE.CylinderGeometry(0.045, 0.055, 0.58, 6),
      new THREE.BoxGeometry(0.45, 1.25, 1.85),
    );
    this.materials.push(
      new THREE.MeshStandardMaterial({color: 0x29a5a0, metalness: 0.2, roughness: 0.42}),
      new THREE.MeshStandardMaterial({color: 0x111719, roughness: 0.9}),
      new THREE.MeshStandardMaterial({color: 0x586a72, metalness: 0.5, roughness: 0.35}),
      new THREE.MeshStandardMaterial({color: 0x6d4d7c, roughness: 0.82}),
      new THREE.MeshStandardMaterial({color: 0xc99772, roughness: 0.88}),
    );
    this.farInstances = new THREE.InstancedMesh(
      this.geometries[6],
      this.materials[0],
      1_024,
    );
    this.farInstances.name = "BicycleFarInstances";
    this.farInstances.count = 0;
    this.farInstances.frustumCulled = false;
    this.farInstances.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    this.farInstances.userData.instanceEntities = this.farInstanceEntities;
    this.root.add(this.farInstances);
  }

  applySnapshot(
    entities: ReadonlyMap<string, VehicleEntity>,
    tickHz: number,
    receivedAtMs: number,
  ): void {
    const visible = new Set<string>();
    const interpolationMs = THREE.MathUtils.clamp(1_000 / Math.max(tickHz, 0.1), 80, 1_500);
    for (const entity of entities.values()) {
      if (!this.withinBounds(entity.x, entity.y)) continue;
      visible.add(entity.id);
      const world = this.coordinates.sumoToWorld(entity.x, entity.y, 0.02);
      this.targetPosition.set(world.x, world.y, world.z);
      this.targetQuaternion.setFromAxisAngle(
        this.up,
        this.coordinates.sumoAngleToThree(entity.angle) + Math.PI,
      );
      let active = this.active.get(entity.id);
      if (!active) {
        const visual = this.acquire(entity.id);
        active = {
          entity,
          previousAngle: entity.angle,
          targetLean: 0,
          wheelAngle: 0,
          visual,
          interpolator: new VehicleInterpolator(),
          transform: {position: new THREE.Vector3(), quaternion: new THREE.Quaternion()},
        };
        active.interpolator.snap(this.targetPosition, this.targetQuaternion, receivedAtMs);
        this.active.set(entity.id, active);
      } else {
        const angleDelta = ((entity.angle - active.previousAngle + 540) % 360) - 180;
        active.targetLean = THREE.MathUtils.clamp(
          THREE.MathUtils.degToRad(-angleDelta * 0.32),
          -0.18,
          0.18,
        );
        active.previousAngle = entity.angle;
        active.entity = entity;
        active.interpolator.retarget(
          this.targetPosition,
          this.targetQuaternion,
          receivedAtMs,
          interpolationMs,
        );
      }
    }
    for (const [identifier, active] of this.active) {
      if (visible.has(identifier)) continue;
      this.release(active.visual);
      this.active.delete(identifier);
    }
  }

  update(frameTimeMs: number, camera?: THREE.Camera): void {
    const deltaSeconds = this.lastFrameTimeMs === null
      ? 0
      : Math.min(0.1, Math.max(0, (frameTimeMs - this.lastFrameTimeMs) / 1000));
    this.lastFrameTimeMs = frameTimeMs;
    let farCount = 0;
    for (const active of this.active.values()) {
      const transform = active.interpolator.sample(frameTimeMs, active.transform);
      active.visual.root.position.copy(transform.position);
      active.visual.root.quaternion.copy(transform.quaternion);
      if (camera && camera.position.distanceToSquared(transform.position) >= 82 ** 2) {
        active.visual.root.visible = false;
        if (farCount < this.farInstances.instanceMatrix.count) {
          this.farPosition.copy(transform.position);
          this.farPosition.y += 0.8;
          this.farMatrix.compose(this.farPosition, transform.quaternion, this.farScale);
          this.farInstances.setMatrixAt(farCount, this.farMatrix);
          const metadata = this.farInstanceEntities[farCount];
          if (metadata) metadata.id = active.entity.id;
          else this.farInstanceEntities[farCount] = {kind: "bicycle", id: active.entity.id};
          farCount += 1;
        }
        continue;
      }
      active.visual.root.visible = true;
      active.visual.lean.rotation.z = THREE.MathUtils.lerp(
        active.visual.lean.rotation.z,
        active.targetLean,
        0.14,
      );
      active.wheelAngle -= (active.entity.speed / 0.34) * deltaSeconds;
      active.visual.wheels.forEach((wheel) => { wheel.rotation.x = active.wheelAngle; });
      const pedal = Math.sin(active.wheelAngle) * 0.72;
      active.visual.leftLeg.rotation.x = pedal;
      active.visual.rightLeg.rotation.x = -pedal;
    }
    this.farInstances.count = farCount;
    this.farInstanceEntities.length = farCount;
    if (farCount > 0) this.farInstances.instanceMatrix.needsUpdate = true;
  }

  count(): number {
    return this.active.size;
  }

  dispose(): void {
    this.active.clear();
    this.available.length = 0;
    this.geometries.forEach((geometry) => geometry.dispose());
    this.materials.forEach((material) => material.dispose());
    this.root.clear();
    this.lastFrameTimeMs = null;
  }

  private acquire(identifier: string): BicycleVisual {
    const visual = this.available.pop() ?? this.createVisual();
    visual.root.visible = true;
    visual.root.userData.entityId = identifier;
    visual.root.userData.entityKind = "bicycle";
    return visual;
  }

  private release(visual: BicycleVisual): void {
    visual.root.visible = false;
    visual.root.userData.entityId = undefined;
    visual.root.userData.entityKind = undefined;
    if (this.available.length < this.softLimit) this.available.push(visual);
    else visual.root.removeFromParent();
  }

  private createVisual(): BicycleVisual {
    const root = new THREE.Group();
    const lean = new THREE.Group();
    const lod = new THREE.LOD();
    const near = new THREE.Group();
    const wheels: THREE.Group[] = [];
    for (const z of [-0.82, 0.82]) {
      const wheelGroup = new THREE.Group();
      wheelGroup.position.set(0, 0.36, z);
      const wheel = new THREE.Mesh(this.geometries[0], this.materials[1]);
      wheel.rotation.y = Math.PI / 2;
      wheelGroup.add(wheel);
      near.add(wheelGroup);
      wheels.push(wheelGroup);
    }
    const frame = new THREE.Mesh(this.geometries[1], this.materials[0]);
    frame.position.y = 0.58;
    const handlebar = new THREE.Mesh(this.geometries[2], this.materials[2]);
    handlebar.position.set(0, 1.05, -0.62);
    const torso = new THREE.Mesh(this.geometries[3], this.materials[3]);
    torso.position.set(0, 1.52, 0.05);
    torso.rotation.x = -0.22;
    const head = new THREE.Mesh(this.geometries[4], this.materials[4]);
    head.position.set(0, 2.03, -0.08);
    const leg = (x: number) => {
      const pivot = new THREE.Group();
      pivot.position.set(x, 1.17, 0.08);
      const mesh = new THREE.Mesh(this.geometries[5], this.materials[3]);
      mesh.position.y = -0.28;
      pivot.add(mesh);
      return pivot;
    };
    const leftLeg = leg(-0.1);
    const rightLeg = leg(0.1);
    near.add(frame, handlebar, torso, head, leftLeg, rightLeg);
    const far = new THREE.Mesh(this.geometries[6], this.materials[0]);
    far.position.y = 0.8;
    lod.addLevel(near, 0);
    lod.addLevel(far, 82);
    lean.add(lod);
    root.add(lean);
    this.root.add(root);
    return {root, lean, wheels, leftLeg, rightLeg};
  }

  private withinBounds(x: number, y: number): boolean {
    const margin = 80;
    return (
      x >= this.bounds.minX - margin && x <= this.bounds.maxX + margin &&
      y >= this.bounds.minY - margin && y <= this.bounds.maxY + margin
    );
  }
}
