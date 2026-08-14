import * as THREE from "three";
import type {AssetManager} from "../assets/AssetManager";

export type VehicleModelDefinition = {
  asset: string;
  baseYawRad: number;
  groundOffsetM: number;
  dimensionsM?: [number, number, number];
  wheelAxlesM?: number[];
  wheelRadiusM?: number;
};

export type VehicleVisualMapping = {
  model: string;
  scale: [number, number, number];
  temporaryFallback?: boolean;
};

export type VehicleModelMapping = {
  schemaVersion: string;
  poolSoftLimit: number;
  lodDistancesM: [number, number];
  models: Record<string, VehicleModelDefinition>;
  typeMappings: Record<string, VehicleVisualMapping>;
  classMappings: Record<string, VehicleVisualMapping>;
  fallback: VehicleVisualMapping;
};

export type PooledVehicle = {
  root: THREE.Group;
  ownedMaterials: THREE.Material[];
  paintMaterials: THREE.MeshStandardMaterial[];
  taillightMaterials: THREE.MeshStandardMaterial[];
  headlightMaterials: THREE.MeshStandardMaterial[];
  leftIndicatorMaterials: THREE.MeshStandardMaterial[];
  rightIndicatorMaterials: THREE.MeshStandardMaterial[];
  emergencyMaterials: THREE.MeshStandardMaterial[];
  emergencyMeshes: THREE.Mesh[];
  wheelSpinGroups: THREE.Group[];
  frontSteerGroups: THREE.Group[];
};

function cloneMaterialForInstance(
  mesh: THREE.Mesh,
  instance: PooledVehicle,
): void {
  const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
  const next = materials.map((material) => {
    const needsInstanceMaterial =
      mesh.name.includes("VehiclePaint") ||
      mesh.name.includes("VehicleTaillight") ||
      mesh.name.includes("VehicleHeadlight") ||
      mesh.name.includes("Indicator") ||
      mesh.name.includes("EmergencyBeacon");
    if (!needsInstanceMaterial || !(material instanceof THREE.MeshStandardMaterial)) {
      return material;
    }
    const cloned = material.clone();
    instance.ownedMaterials.push(cloned);
    if (mesh.name.includes("VehiclePaint")) instance.paintMaterials.push(cloned);
    if (mesh.name.includes("VehicleTaillight")) instance.taillightMaterials.push(cloned);
    if (mesh.name.includes("VehicleHeadlight")) instance.headlightMaterials.push(cloned);
    if (mesh.name.includes("IndicatorLeft")) instance.leftIndicatorMaterials.push(cloned);
    if (mesh.name.includes("IndicatorRight")) instance.rightIndicatorMaterials.push(cloned);
    if (mesh.name.includes("EmergencyBeacon")) instance.emergencyMaterials.push(cloned);
    return cloned;
  });
  mesh.material = Array.isArray(mesh.material) ? next : next[0];
}

function fallbackTemplate(): THREE.Group {
  const root = new THREE.Group();
  root.name = "VehicleFallbackTemplate";
  const body = new THREE.Mesh(
    new THREE.BoxGeometry(4.6, 1.25, 2.0),
    new THREE.MeshStandardMaterial({color: 0xb8c5ca, roughness: 0.3, metalness: 0.35}),
  );
  body.name = "Vehicle_VehiclePaint_Fallback";
  body.position.y = 0.72;
  const cabin = new THREE.Mesh(
    new THREE.BoxGeometry(2.3, 0.75, 1.72),
    new THREE.MeshStandardMaterial({color: 0x25333b, roughness: 0.16, metalness: 0.2}),
  );
  cabin.name = "Vehicle_Cabin_Fallback";
  cabin.position.set(-0.25, 1.62, 0);
  root.add(body, cabin);
  return root;
}

function enhanceVehicleTemplate(
  root: THREE.Group,
  definition: VehicleModelDefinition,
): void {
  root.traverse((object) => {
    if (
      object instanceof THREE.Mesh &&
      (object.name.includes("VehicleTire") || object.name.includes("VehicleRim"))
    ) {
      object.visible = false;
    }
  });
  const [length, height, width] = definition.dimensionsM ?? [4.65, 1.95, 2.1];
  const wheelRadius = definition.wheelRadiusM ?? 0.39;
  const wheelDepth = Math.min(0.42, Math.max(0.26, width * 0.13));
  const wheelAxles = definition.wheelAxlesM ?? [1.45, -1.45];
  const tireGeometry = new THREE.CylinderGeometry(
    wheelRadius,
    wheelRadius,
    wheelDepth,
    14,
  );
  const rimGeometry = new THREE.CylinderGeometry(
    wheelRadius * 0.52,
    wheelRadius * 0.52,
    wheelDepth + 0.012,
    12,
  );
  const tireMaterial = new THREE.MeshStandardMaterial({
    color: 0x111416,
    roughness: 0.86,
    metalness: 0.02,
  });
  const rimMaterial = new THREE.MeshStandardMaterial({
    color: 0xaeb9bf,
    roughness: 0.28,
    metalness: 0.78,
  });
  for (const [axleIndex, x] of wheelAxles.entries()) {
    const axle = axleIndex === 0 ? "front" : `rear${axleIndex}`;
    for (const [side, z] of [
      ["left", -(width / 2 - wheelRadius * 0.18)],
      ["right", width / 2 - wheelRadius * 0.18],
    ] as const) {
      const steer = new THREE.Group();
      steer.name = `WheelSteer:${axle}-${side}`;
      steer.position.set(x, wheelRadius, z);
      const spin = new THREE.Group();
      spin.name = `WheelSpin:${axle}-${side}`;
      const tire = new THREE.Mesh(tireGeometry, tireMaterial);
      tire.rotation.x = Math.PI / 2;
      tire.name = `WheelTire:${axle}-${side}`;
      const rim = new THREE.Mesh(rimGeometry, rimMaterial);
      rim.rotation.x = Math.PI / 2;
      rim.name = `WheelRim:${axle}-${side}`;
      spin.add(tire, rim);
      steer.add(spin);
      root.add(steer);
    }
  }
  const indicatorGeometry = new THREE.BoxGeometry(0.12, 0.11, 0.16);
  const indicatorMaterial = new THREE.MeshStandardMaterial({
    color: 0xffa000,
    emissive: 0xff7a00,
    emissiveIntensity: 0,
    roughness: 0.3,
  });
  for (const [side, z] of [
    ["Left", -0.86],
    ["Right", 0.86],
  ] as const) {
    for (const x of [-length / 2 - 0.01, length / 2 + 0.01]) {
      const indicator = new THREE.Mesh(indicatorGeometry, indicatorMaterial);
      indicator.name = `Vehicle_Indicator${side}`;
      indicator.position.set(x, Math.min(0.92, height * 0.34), z * (width / 2 - 0.14));
      root.add(indicator);
    }
  }
  const beaconGeometry = new THREE.BoxGeometry(0.48, 0.12, 0.18);
  for (const [side, z, color] of [
    ["Blue", -0.13, 0x147cff],
    ["Red", 0.13, 0xff2438],
  ] as const) {
    const material = new THREE.MeshStandardMaterial({
      color,
      emissive: color,
      emissiveIntensity: 0,
      roughness: 0.2,
    });
    const beacon = new THREE.Mesh(beaconGeometry, material);
    beacon.name = `Vehicle_EmergencyBeacon${side}`;
    beacon.position.set(-0.2, height + 0.07, z);
    beacon.visible = false;
    root.add(beacon);
  }
}

export class VehiclePool {
  readonly root = new THREE.Group();
  readonly farInstances: THREE.InstancedMesh;
  private template: THREE.Group | null = null;
  private readonly available: PooledVehicle[] = [];
  private readonly allocated = new Set<PooledVehicle>();
  private readonly midBodyGeometry: THREE.BoxGeometry;
  private readonly midCabinGeometry: THREE.BoxGeometry;
  private readonly farGeometry: THREE.BoxGeometry;
  private readonly dimensionsM: [number, number, number];
  private readonly farInstanceEntities: Array<{kind: "vehicle"; id: string}> = [];
  private readonly farMatrix = new THREE.Matrix4();
  private readonly farPosition = new THREE.Vector3();
  private readonly farColor = new THREE.Color();
  private farCount = 0;
  private static readonly FAR_CAPACITY = 2_048;

  constructor(
    private readonly softLimit: number,
    private readonly lodDistancesM: [number, number],
    private readonly definition: VehicleModelDefinition,
    private readonly assets: AssetManager,
  ) {
    this.root.name = "VehiclePool";
    this.dimensionsM = definition.dimensionsM ?? [4.65, 1.95, 2.1];
    const [length, height, width] = this.dimensionsM;
    this.midBodyGeometry = new THREE.BoxGeometry(length * 0.98, height * 0.56, width * 0.96);
    this.midCabinGeometry = new THREE.BoxGeometry(
      length * 0.72,
      height * 0.30,
      width * 0.84,
    );
    this.farGeometry = new THREE.BoxGeometry(length * 0.96, height * 0.84, width * 0.92);
    const farMaterial = new THREE.MeshStandardMaterial({
      color: 0xffffff,
      roughness: 0.46,
      metalness: 0.18,
    });
    this.farInstances = new THREE.InstancedMesh(
      this.farGeometry,
      farMaterial,
      VehiclePool.FAR_CAPACITY,
    );
    this.farInstances.name = "VehicleFarInstances";
    this.farInstances.count = 0;
    this.farInstances.castShadow = false;
    this.farInstances.receiveShadow = false;
    this.farInstances.frustumCulled = false;
    this.farInstances.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    this.farInstances.userData.instanceEntities = this.farInstanceEntities;
    this.root.add(this.farInstances);
  }

  farDistanceM(): number {
    return this.lodDistancesM[1];
  }

  beginFarFrame(): void {
    this.farCount = 0;
  }

  appendFarInstance(
    identifier: string,
    position: THREE.Vector3,
    quaternion: THREE.Quaternion,
    scale: THREE.Vector3,
    color: string,
  ): void {
    if (this.farCount >= VehiclePool.FAR_CAPACITY) return;
    const index = this.farCount;
    this.farPosition.copy(position);
    this.farPosition.y += this.dimensionsM[1] * 0.45 * scale.y;
    this.farMatrix.compose(this.farPosition, quaternion, scale);
    this.farInstances.setMatrixAt(index, this.farMatrix);
    this.farInstances.setColorAt(index, this.farColor.set(color));
    const metadata = this.farInstanceEntities[index];
    if (metadata) metadata.id = identifier;
    else this.farInstanceEntities[index] = {kind: "vehicle", id: identifier};
    this.farCount += 1;
  }

  endFarFrame(): void {
    this.farInstances.count = this.farCount;
    this.farInstanceEntities.length = this.farCount;
    if (this.farCount > 0) {
      this.farInstances.instanceMatrix.needsUpdate = true;
      if (this.farInstances.instanceColor) this.farInstances.instanceColor.needsUpdate = true;
    }
  }

  async initialize(asset: string): Promise<void> {
    try {
      this.template = await this.assets.loadTemplate(asset);
      this.template.name = "VehicleTemplate";
    } catch (error: unknown) {
      console.warn("vehicle GLB failed; using the explicit fallback model", error);
      this.template = fallbackTemplate();
    }
    enhanceVehicleTemplate(this.template, this.definition);
  }

  acquire(identifier: string): PooledVehicle {
    const instance = this.available.pop() ?? this.createInstance();
    instance.root.visible = true;
    instance.root.name = `Vehicle:${identifier}`;
    instance.root.userData.entityId = identifier;
    instance.root.userData.entityKind = "vehicle";
    return instance;
  }

  release(instance: PooledVehicle): void {
    instance.root.visible = false;
    instance.root.userData.entityId = undefined;
    instance.root.userData.entityKind = undefined;
    if (this.available.length < this.softLimit) {
      this.available.push(instance);
      return;
    }
    for (const material of new Set(instance.ownedMaterials)) {
      material.dispose();
    }
    instance.root.removeFromParent();
    this.allocated.delete(instance);
  }

  dispose(): void {
    const geometries = new Set<THREE.BufferGeometry>();
    const materials = new Set<THREE.Material>();
    this.root.traverse((object) => {
      if (!(object instanceof THREE.Mesh)) return;
      geometries.add(object.geometry);
      const source = Array.isArray(object.material) ? object.material : [object.material];
      for (const material of source) materials.add(material);
    });
    this.template?.traverse((object) => {
      if (!(object instanceof THREE.Mesh)) return;
      geometries.add(object.geometry);
      const source = Array.isArray(object.material) ? object.material : [object.material];
      for (const material of source) materials.add(material);
    });
    for (const geometry of geometries) geometry.dispose();
    for (const material of materials) material.dispose();
    this.root.clear();
    this.available.length = 0;
    this.allocated.clear();
    this.template = null;
  }

  private createInstance(): PooledVehicle {
    if (!this.template) throw new Error("vehicle pool is not initialized");
    const instance: PooledVehicle = {
      root: new THREE.Group(),
      ownedMaterials: [],
      paintMaterials: [],
      taillightMaterials: [],
      headlightMaterials: [],
      leftIndicatorMaterials: [],
      rightIndicatorMaterials: [],
      emergencyMaterials: [],
      emergencyMeshes: [],
      wheelSpinGroups: [],
      frontSteerGroups: [],
    };
    const lod = new THREE.LOD();
    lod.name = "VehicleLOD";
    const near = this.template.clone(true);
    near.name = "VehicleLOD0";
    const mid = new THREE.Group();
    mid.name = "VehicleLOD1";
    const midPaint = new THREE.MeshStandardMaterial({
      color: 0xb8c5ca,
      roughness: 0.34,
      metalness: 0.28,
    });
    const midBody = new THREE.Mesh(this.midBodyGeometry, midPaint);
    midBody.name = "VehicleMidBody";
    midBody.position.y = this.dimensionsM[1] * 0.30;
    const midCabinMaterial = new THREE.MeshStandardMaterial({
      color: 0x26343b,
      roughness: 0.22,
      metalness: 0.18,
    });
    const midCabin = new THREE.Mesh(this.midCabinGeometry, midCabinMaterial);
    midCabin.name = "VehicleMidCabin";
    midCabin.position.set(-this.dimensionsM[0] * 0.05, this.dimensionsM[1] * 0.72, 0);
    mid.add(midBody, midCabin);
    const farPaint = new THREE.MeshStandardMaterial({
      color: 0xb8c5ca,
      roughness: 0.46,
      metalness: 0.18,
    });
    const far = new THREE.Mesh(this.farGeometry, farPaint);
    far.name = "VehicleLOD2";
    far.position.y = this.dimensionsM[1] * 0.45;
    instance.paintMaterials.push(midPaint, farPaint);
    instance.ownedMaterials.push(midPaint, midCabinMaterial, farPaint);
    lod.addLevel(near, 0);
    lod.addLevel(mid, this.lodDistancesM[0]);
    lod.addLevel(far, this.lodDistancesM[1]);
    instance.root.add(lod);
    instance.root.traverse((object) => {
      if (!(object instanceof THREE.Mesh)) return;
      object.castShadow = false;
      object.receiveShadow = false;
      cloneMaterialForInstance(object, instance);
      if (object.name.includes("EmergencyBeacon")) {
        instance.emergencyMeshes.push(object);
      }
    });
    instance.root.traverse((object) => {
      if (!(object instanceof THREE.Group)) return;
      if (object.name.startsWith("WheelSpin:")) instance.wheelSpinGroups.push(object);
      if (object.name.startsWith("WheelSteer:front-")) instance.frontSteerGroups.push(object);
    });
    this.root.add(instance.root);
    this.allocated.add(instance);
    return instance;
  }
}
