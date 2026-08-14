import * as THREE from "three";
import type {CoordinateService} from "../core/CoordinateService";
import type {PedestrianEntity} from "../network/digitalTwinTypes";
import type {SceneBounds} from "../scene/types";
import {VehicleInterpolator} from "../vehicles/VehicleInterpolator";

type PedestrianVisual = {
  root: THREE.Group;
  leftArm: THREE.Bone;
  rightArm: THREE.Bone;
  leftLeg: THREE.Bone;
  rightLeg: THREE.Bone;
  leftForearm: THREE.Bone;
  rightForearm: THREE.Bone;
  leftShin: THREE.Bone;
  rightShin: THREE.Bone;
};

type LimbRig = {
  root: THREE.Group;
  upperBone: THREE.Bone;
  lowerBone: THREE.Bone;
};

type ActivePedestrian = {
  entity: PedestrianEntity;
  visual: PedestrianVisual;
  interpolator: VehicleInterpolator;
  transform: {position: THREE.Vector3; quaternion: THREE.Quaternion};
  clothingColor: THREE.Color;
};

function identifierHash(value: string): number {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = (Math.imul(hash, 33) ^ value.charCodeAt(index)) >>> 0;
  }
  return hash;
}

export class PedestrianManager {
  readonly root = new THREE.Group();
  private readonly active = new Map<string, ActivePedestrian>();
  private readonly available: PedestrianVisual[] = [];
  private readonly geometries: THREE.BufferGeometry[] = [];
  private readonly materials: THREE.Material[] = [];
  private readonly up = new THREE.Vector3(0, 1, 0);
  private readonly targetPosition = new THREE.Vector3();
  private readonly targetQuaternion = new THREE.Quaternion();
  private readonly farInstances: THREE.InstancedMesh;
  private readonly farInstanceEntities: Array<{kind: "pedestrian"; id: string}> = [];
  private readonly farMatrix = new THREE.Matrix4();
  private readonly farPosition = new THREE.Vector3();
  private readonly farScale = new THREE.Vector3(1, 1, 1);

  constructor(
    private readonly coordinates: CoordinateService,
    private readonly bounds: SceneBounds,
    private readonly softLimit = 96,
  ) {
    this.root.name = "SUMOPedestrians";
    const limbGeometry = new THREE.CylinderGeometry(0.045, 0.055, 0.58, 6, 4);
    const limbPositions = limbGeometry.getAttribute("position");
    const skinIndices: number[] = [];
    const skinWeights: number[] = [];
    for (let index = 0; index < limbPositions.count; index += 1) {
      const y = limbPositions.getY(index);
      const lowerWeight = THREE.MathUtils.clamp((0.12 - y) / 0.42, 0, 1);
      skinIndices.push(0, 1, 0, 0);
      skinWeights.push(1 - lowerWeight, lowerWeight, 0, 0);
    }
    limbGeometry.setAttribute("skinIndex", new THREE.Uint16BufferAttribute(skinIndices, 4));
    limbGeometry.setAttribute("skinWeight", new THREE.Float32BufferAttribute(skinWeights, 4));
    this.geometries.push(
      new THREE.SphereGeometry(0.16, 10, 8),
      new THREE.CapsuleGeometry(0.17, 0.48, 4, 8),
      limbGeometry,
      new THREE.CapsuleGeometry(0.13, 0.7, 3, 6),
    );
    const colors = [0x3a6f8c, 0x9b5a4f, 0x4e775a, 0x79648f];
    colors.forEach((color) => this.materials.push(new THREE.MeshStandardMaterial({
      color,
      roughness: 0.82,
    })));
    this.materials.push(
      new THREE.MeshStandardMaterial({color: 0xc99772, roughness: 0.88}),
      new THREE.MeshStandardMaterial({color: 0x252d33, roughness: 0.9}),
    );
    const farMaterial = new THREE.MeshStandardMaterial({color: 0xffffff, roughness: 0.82});
    this.materials.push(farMaterial);
    this.farInstances = new THREE.InstancedMesh(this.geometries[3], farMaterial, 1_024);
    this.farInstances.name = "PedestrianFarInstances";
    this.farInstances.count = 0;
    this.farInstances.frustumCulled = false;
    this.farInstances.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    this.farInstances.userData.instanceEntities = this.farInstanceEntities;
    this.root.add(this.farInstances);
  }

  applySnapshot(
    entities: ReadonlyMap<string, PedestrianEntity>,
    tickHz: number,
    receivedAtMs: number,
  ): void {
    const visible = new Set<string>();
    const interpolationMs = THREE.MathUtils.clamp(1_000 / Math.max(tickHz, 0.1), 80, 1_500);
    for (const entity of entities.values()) {
      if (!this.withinBounds(entity.x, entity.y)) continue;
      visible.add(entity.id);
      const world = this.coordinates.sumoToWorld(entity.x, entity.y, 0.03);
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
          visual,
          interpolator: new VehicleInterpolator(),
          transform: {position: new THREE.Vector3(), quaternion: new THREE.Quaternion()},
          clothingColor: (
            this.materials[identifierHash(entity.id) % 4] as THREE.MeshStandardMaterial
          ).color.clone(),
        };
        active.interpolator.snap(this.targetPosition, this.targetQuaternion, receivedAtMs);
        this.active.set(entity.id, active);
      } else {
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
    let farCount = 0;
    for (const active of this.active.values()) {
      const transform = active.interpolator.sample(frameTimeMs, active.transform);
      active.visual.root.position.copy(transform.position);
      active.visual.root.quaternion.copy(transform.quaternion);
      if (camera && camera.position.distanceToSquared(transform.position) >= 65 ** 2) {
        active.visual.root.visible = false;
        if (farCount < this.farInstances.instanceMatrix.count) {
          this.farPosition.copy(transform.position);
          this.farPosition.y += 0.92;
          this.farMatrix.compose(this.farPosition, transform.quaternion, this.farScale);
          this.farInstances.setMatrixAt(farCount, this.farMatrix);
          this.farInstances.setColorAt(farCount, active.clothingColor);
          const metadata = this.farInstanceEntities[farCount];
          if (metadata) metadata.id = active.entity.id;
          else this.farInstanceEntities[farCount] = {kind: "pedestrian", id: active.entity.id};
          farCount += 1;
        }
        continue;
      }
      active.visual.root.visible = true;
      const moving = active.entity.status === "walking" && active.entity.speed > 0.05;
      const phase = moving ? Math.sin(frameTimeMs * 0.0065 * Math.max(active.entity.speed, 0.5)) : 0;
      active.visual.leftArm.rotation.x = phase * 0.58;
      active.visual.rightArm.rotation.x = -phase * 0.58;
      active.visual.leftLeg.rotation.x = -phase * 0.62;
      active.visual.rightLeg.rotation.x = phase * 0.62;
      active.visual.leftForearm.rotation.x = Math.max(0, phase) * 0.34;
      active.visual.rightForearm.rotation.x = Math.max(0, -phase) * 0.34;
      active.visual.leftShin.rotation.x = Math.max(0, phase) * 0.46;
      active.visual.rightShin.rotation.x = Math.max(0, -phase) * 0.46;
      active.visual.root.position.y += moving ? Math.abs(phase) * 0.015 : 0;
    }
    this.farInstances.count = farCount;
    this.farInstanceEntities.length = farCount;
    if (farCount > 0) {
      this.farInstances.instanceMatrix.needsUpdate = true;
      if (this.farInstances.instanceColor) this.farInstances.instanceColor.needsUpdate = true;
    }
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
  }

  private acquire(identifier: string): PedestrianVisual {
    const visual = this.available.pop() ?? this.createVisual(identifier);
    visual.root.visible = true;
    visual.root.userData.entityId = identifier;
    visual.root.userData.entityKind = "pedestrian";
    return visual;
  }

  private release(visual: PedestrianVisual): void {
    visual.root.visible = false;
    visual.root.userData.entityId = undefined;
    visual.root.userData.entityKind = undefined;
    if (this.available.length < this.softLimit) this.available.push(visual);
    else visual.root.removeFromParent();
  }

  private createVisual(identifier: string): PedestrianVisual {
    const root = new THREE.Group();
    const lod = new THREE.LOD();
    const near = new THREE.Group();
    const clothing = this.materials[identifierHash(identifier) % 4];
    const skin = this.materials[4];
    const dark = this.materials[5];
    const body = new THREE.Mesh(this.geometries[1], clothing);
    body.position.y = 1.05;
    const head = new THREE.Mesh(this.geometries[0], skin);
    head.position.y = 1.62;
    const limb = (x: number, y: number, material: THREE.Material): LimbRig => {
      const pivot = new THREE.Group();
      pivot.position.set(x, y, 0);
      const mesh = new THREE.SkinnedMesh(this.geometries[2], material);
      mesh.position.y = -0.28;
      mesh.normalizeSkinWeights();
      const upperBone = new THREE.Bone();
      upperBone.name = "upper-limb";
      upperBone.position.y = 0.29;
      const lowerBone = new THREE.Bone();
      lowerBone.name = "lower-limb";
      lowerBone.position.y = -0.29;
      upperBone.add(lowerBone);
      mesh.add(upperBone);
      mesh.bind(new THREE.Skeleton([upperBone, lowerBone]));
      pivot.add(mesh);
      return {root: pivot, upperBone, lowerBone};
    };
    const leftArm = limb(-0.22, 1.35, clothing);
    const rightArm = limb(0.22, 1.35, clothing);
    const leftLeg = limb(-0.105, 0.72, dark);
    const rightLeg = limb(0.105, 0.72, dark);
    near.add(body, head, leftArm.root, rightArm.root, leftLeg.root, rightLeg.root);
    const mid = new THREE.Mesh(this.geometries[3], clothing);
    mid.name = "PedestrianMidLOD";
    mid.position.y = 0.92;
    lod.addLevel(near, 0);
    lod.addLevel(mid, 25);
    root.add(lod);
    this.root.add(root);
    return {
      root,
      leftArm: leftArm.upperBone,
      rightArm: rightArm.upperBone,
      leftLeg: leftLeg.upperBone,
      rightLeg: rightLeg.upperBone,
      leftForearm: leftArm.lowerBone,
      rightForearm: rightArm.lowerBone,
      leftShin: leftLeg.lowerBone,
      rightShin: rightLeg.lowerBone,
    };
  }

  private withinBounds(x: number, y: number): boolean {
    const margin = 80;
    return (
      x >= this.bounds.minX - margin && x <= this.bounds.maxX + margin &&
      y >= this.bounds.minY - margin && y <= this.bounds.maxY + margin
    );
  }
}
