import * as THREE from "three";
import type {CoordinateService} from "../core/CoordinateService";
import type {SceneJunction, SceneRoadsideDevice} from "../scene/types";

export type RoadsideDeviceStats = {
  devices: number;
  rsus: number;
  cameras: number;
  runtimeBound: number;
  drawObjects: number;
  triangles: number;
};

export class RoadsideDeviceManager {
  readonly root = new THREE.Group();
  readonly analysisRoot = new THREE.Group();
  readonly stats: RoadsideDeviceStats;
  private readonly geometries: THREE.BufferGeometry[] = [];
  private readonly materials: THREE.Material[] = [];
  private readonly rsus: SceneRoadsideDevice[];
  private readonly cameras: SceneRoadsideDevice[];
  private readonly rsuBodies: THREE.InstancedMesh;
  private readonly cameraBodies: THREE.InstancedMesh;

  constructor(
    coordinates: CoordinateService,
    devices: SceneRoadsideDevice[],
    junctions: SceneJunction[],
  ) {
    this.root.name = "RoadsideDeviceManager";
    this.analysisRoot.name = "RoadsideDeviceAnalysis";
    this.analysisRoot.visible = false;
    const junctionById = new Map(junctions.map((item) => [item.sumoJunctionId, item]));
    const rsus = devices.filter((item) => item.deviceType === "rsu");
    const cameras = devices.filter((item) => item.deviceType === "camera");
    this.rsus = rsus;
    this.cameras = cameras;
    const poleGeometry = new THREE.CylinderGeometry(0.09, 0.13, 5, 8);
    const rsuGeometry = new THREE.BoxGeometry(0.58, 0.84, 0.34);
    const cameraGeometry = new THREE.BoxGeometry(0.72, 0.3, 0.32);
    const poleMaterial = new THREE.MeshStandardMaterial({
      color: 0x354247,
      roughness: 0.55,
    });
    const rsuMaterial = new THREE.MeshStandardMaterial({
      color: 0xdce8e4,
      emissive: 0x103f38,
      emissiveIntensity: 0.42,
      roughness: 0.38,
    });
    const cameraMaterial = new THREE.MeshStandardMaterial({
      color: 0x63747a,
      roughness: 0.42,
    });
    this.geometries.push(poleGeometry, rsuGeometry, cameraGeometry);
    this.materials.push(poleMaterial, rsuMaterial, cameraMaterial);
    const poles = new THREE.InstancedMesh(poleGeometry, poleMaterial, devices.length);
    const rsuBodies = new THREE.InstancedMesh(rsuGeometry, rsuMaterial, rsus.length);
    const cameraBodies = new THREE.InstancedMesh(
      cameraGeometry,
      cameraMaterial,
      cameras.length,
    );
    this.rsuBodies = rsuBodies;
    this.cameraBodies = cameraBodies;
    poles.name = "RoadsideDevicePoles";
    rsuBodies.name = "RSUBodies";
    cameraBodies.name = "CameraBodies";
    poles.userData.instanceEntities = devices.map((device) => ({
      kind: "roadsideDevice",
      id: device.deviceId,
      deviceType: device.deviceType,
    }));
    rsuBodies.userData.instanceEntities = rsus.map((device) => ({
      kind: "roadsideDevice",
      id: device.deviceId,
      deviceType: device.deviceType,
    }));
    cameraBodies.userData.instanceEntities = cameras.map((device) => ({
      kind: "roadsideDevice",
      id: device.deviceId,
      deviceType: device.deviceType,
    }));
    const matrix = new THREE.Matrix4();
    devices.forEach((device, index) => {
      const world = coordinates.sumoToWorld(device.position.x, device.position.y, 2.5);
      matrix.makeTranslation(world.x, world.y, world.z);
      poles.setMatrixAt(index, matrix);
    });
    rsus.forEach((device, index) => {
      const world = coordinates.sumoToWorld(device.position.x, device.position.y, 4.45);
      matrix.makeTranslation(world.x, world.y, world.z);
      rsuBodies.setMatrixAt(index, matrix);
    });
    cameras.forEach((device, index) => {
      const world = coordinates.sumoToWorld(device.position.x, device.position.y, 5.08);
      matrix.makeTranslation(world.x, world.y, world.z);
      cameraBodies.setMatrixAt(index, matrix);
    });
    for (const mesh of [poles, rsuBodies, cameraBodies]) {
      mesh.instanceMatrix.needsUpdate = true;
    }

    const coverageGeometry = new THREE.RingGeometry(40, 41.2, 48);
    const coverageMaterial = new THREE.MeshBasicMaterial({
      color: 0x35d5b3,
      transparent: true,
      opacity: 0.25,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    this.geometries.push(coverageGeometry);
    this.materials.push(coverageMaterial);
    const coverage = new THREE.InstancedMesh(
      coverageGeometry,
      coverageMaterial,
      rsus.length,
    );
    coverage.name = "ModeledRSUCoverage";
    const flat = new THREE.Quaternion().setFromAxisAngle(
      new THREE.Vector3(1, 0, 0),
      -Math.PI / 2,
    );
    rsus.forEach((device, index) => {
      const world = coordinates.sumoToWorld(device.position.x, device.position.y, 0.16);
      matrix.compose(
        new THREE.Vector3(world.x, world.y, world.z),
        flat,
        new THREE.Vector3(1, 1, 1),
      );
      coverage.setMatrixAt(index, matrix);
    });
    coverage.instanceMatrix.needsUpdate = true;

    const relationPositions: number[] = [];
    for (const device of rsus) {
      const managed = device.managedJunctions[0];
      const junction = managed ? junctionById.get(managed) : undefined;
      if (!junction) continue;
      const from = coordinates.sumoToWorld(device.position.x, device.position.y, 4.5);
      const to = coordinates.sumoToWorld(junction.position.x, junction.position.y, 0.5);
      relationPositions.push(from.x, from.y, from.z, to.x, to.y, to.z);
    }
    const relationGeometry = new THREE.BufferGeometry();
    relationGeometry.setAttribute(
      "position",
      new THREE.Float32BufferAttribute(relationPositions, 3),
    );
    const relationMaterial = new THREE.LineBasicMaterial({
      color: 0x72ffe1,
      transparent: true,
      opacity: 0.22,
      depthWrite: false,
    });
    this.geometries.push(relationGeometry);
    this.materials.push(relationMaterial);
    const relations = new THREE.LineSegments(relationGeometry, relationMaterial);
    relations.name = "ModeledRSUManagementRelations";
    this.analysisRoot.add(coverage, relations);
    this.root.add(poles, rsuBodies, cameraBodies, this.analysisRoot);
    this.stats = {
      devices: devices.length,
      rsus: rsus.length,
      cameras: cameras.length,
      runtimeBound: devices.filter((item) => item.communicationStatus !== "runtime_unbound").length,
      drawObjects: 5,
      triangles:
        devices.length * 32 +
        rsus.length * 12 +
        cameras.length * 12 +
        rsus.length * 96,
    };
  }

  setAnalysisVisible(visible: boolean): void {
    this.analysisRoot.visible = visible;
  }

  applyRuntimeState(
    trafficLights: ReadonlyMap<string, unknown>,
    metrics: Readonly<Record<string, number | string | boolean | null>>,
  ): void {
    const transportOnline = metrics.cloud_online !== false && metrics.mqtt_online !== false;
    let runtimeBound = 0;
    const apply = (
      mesh: THREE.InstancedMesh,
      devices: SceneRoadsideDevice[],
      onlineColor: THREE.Color,
    ) => {
      devices.forEach((device, index) => {
        const sumoBound = device.managedJunctions.some((id) => trafficLights.has(id));
        if (sumoBound) runtimeBound += 1;
        mesh.setColorAt(
          index,
          sumoBound && transportOnline
            ? onlineColor
            : sumoBound
              ? new THREE.Color(0xffb347)
              : new THREE.Color(0x66767b),
        );
      });
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    };
    apply(this.rsuBodies, this.rsus, new THREE.Color(0x9fffe7));
    apply(this.cameraBodies, this.cameras, new THREE.Color(0x9fd7ff));
    this.stats.runtimeBound = runtimeBound;
  }

  dispose(): void {
    this.root.removeFromParent();
    this.geometries.forEach((geometry) => geometry.dispose());
    this.materials.forEach((material) => material.dispose());
    this.root.clear();
  }
}
