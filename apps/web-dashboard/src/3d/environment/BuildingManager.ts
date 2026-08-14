import * as THREE from "three";
import {mergeGeometries} from "three/addons/utils/BufferGeometryUtils.js";
import type {CoordinateService} from "../core/CoordinateService";
import type {SceneBuilding} from "../scene/types";

type BuildingClass = "residential" | "commercial" | "public" | "generic";

export type BuildingStats = {
  sourceBuildings: number;
  renderedBuildings: number;
  modeledHeightBuildings: number;
  drawObjects: number;
  triangles: number;
  windows: number;
};

function stableHash(value: string): number {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

export function visualBuildingHeight(building: SceneBuilding): {
  heightM: number;
  modeled: boolean;
} {
  if (building.heightM !== null && building.heightM > 1) {
    return {heightM: building.heightM, modeled: false};
  }
  if (building.levels !== null && building.levels > 0) {
    return {heightM: building.levels * 3.15, modeled: false};
  }
  // Deterministic engineering default for OSM footprints without height tags.
  // It is visual context only and is not described as surveyed geometry.
  return {heightM: 10 + (stableHash(building.sceneId) % 7) * 3.1, modeled: true};
}

function buildingClass(building: SceneBuilding): BuildingClass {
  const value = `${building.buildingType} ${building.tags.amenity ?? ""} ${building.tags.landuse ?? ""}`.toLowerCase();
  if (/school|hospital|civic|public|government/.test(value)) return "public";
  if (/commercial|retail|office|shop/.test(value)) return "commercial";
  if (/residential|apartments|house|dormitory/.test(value)) return "residential";
  return "generic";
}

function footprintShape(
  coordinateService: CoordinateService,
  building: SceneBuilding,
): THREE.Shape | null {
  const points = building.footprint;
  if (points.length < 3) return null;
  const shape = new THREE.Shape();
  points.forEach((point, index) => {
    const world = coordinateService.sumoToWorld(point.x, point.y);
    if (index === 0) shape.moveTo(world.x, -world.z);
    else shape.lineTo(world.x, -world.z);
  });
  shape.closePath();
  return shape;
}

function appendFacadeWindows(
  coordinateService: CoordinateService,
  building: SceneBuilding,
  heightM: number,
  output: THREE.Matrix4[],
): void {
  if (output.length >= 4800 || building.footprint.length < 3) return;
  const points = building.footprint.map((point) => coordinateService.sumoToWorld(point.x, point.y));
  const floors = Math.min(9, Math.max(1, Math.floor(heightM / 3.15) - 1));
  let signedArea = 0;
  for (let index = 0; index < points.length; index += 1) {
    const current = points[index];
    const next = points[(index + 1) % points.length];
    if (current && next) signedArea += current.x * next.z - next.x * current.z;
  }
  const quaternion = new THREE.Quaternion();
  for (let edgeIndex = 0; edgeIndex < points.length; edgeIndex += 1) {
    const start = points[edgeIndex];
    const end = points[(edgeIndex + 1) % points.length];
    if (!start || !end) continue;
    const dx = end.x - start.x;
    const dz = end.z - start.z;
    const length = Math.hypot(dx, dz);
    const columns = Math.min(14, Math.max(0, Math.floor(length / 3.4)));
    if (columns < 1) continue;
    const tangentX = dx / length;
    const tangentZ = dz / length;
    const outwardSign = signedArea >= 0 ? 1 : -1;
    const normalX = tangentZ * outwardSign;
    const normalZ = -tangentX * outwardSign;
    quaternion.setFromAxisAngle(
      new THREE.Vector3(0, 1, 0),
      Math.atan2(-tangentZ, tangentX),
    );
    for (let floor = 0; floor < floors; floor += 1) {
      const y = 2.05 + floor * 3.15;
      for (let column = 0; column < columns; column += 1) {
        if (output.length >= 4800) return;
        const along = (column + 1) / (columns + 1);
        const position = new THREE.Vector3(
          start.x + dx * along + normalX * 0.09,
          y,
          start.z + dz * along + normalZ * 0.09,
        );
        output.push(
          new THREE.Matrix4().compose(position, quaternion, new THREE.Vector3(1, 1, 1)),
        );
      }
    }
  }
}

export class BuildingManager {
  readonly root = new THREE.Group();
  readonly stats: BuildingStats;

  private readonly geometries: THREE.BufferGeometry[] = [];
  private readonly materials: THREE.Material[] = [];

  constructor(
    coordinateService: CoordinateService,
    buildings: SceneBuilding[],
  ) {
    this.root.name = "BuildingManager";
    const byClass = new Map<BuildingClass, THREE.BufferGeometry[]>();
    let modeledHeightBuildings = 0;
    let renderedBuildings = 0;
    const windowMatrices: THREE.Matrix4[] = [];

    for (const building of buildings) {
      const shape = footprintShape(coordinateService, building);
      if (!shape) continue;
      const height = visualBuildingHeight(building);
      if (height.modeled) modeledHeightBuildings += 1;
      appendFacadeWindows(coordinateService, building, height.heightM, windowMatrices);
      const geometry = new THREE.ExtrudeGeometry(shape, {
        depth: height.heightM,
        bevelEnabled: true,
        bevelSegments: 1,
        bevelSize: 0.12,
        bevelThickness: 0.12,
        curveSegments: 1,
        steps: 1,
      });
      geometry.rotateX(-Math.PI / 2);
      geometry.computeVertexNormals();
      const key = buildingClass(building);
      const collection = byClass.get(key) ?? [];
      collection.push(geometry);
      byClass.set(key, collection);
      renderedBuildings += 1;
    }

    const colors: Record<BuildingClass, number> = {
      residential: 0xb7aa92,
      commercial: 0x7f9296,
      public: 0xc1b184,
      generic: 0x9e9b91,
    };
    let triangles = 0;
    for (const [key, pieces] of byClass) {
      const merged = mergeGeometries(pieces, false);
      pieces.forEach((piece) => piece.dispose());
      if (!merged) continue;
      const material = new THREE.MeshStandardMaterial({
        name: `building-${key}`,
        color: colors[key],
        roughness: 0.72,
        metalness: key === "commercial" ? 0.08 : 0.02,
      });
      const mesh = new THREE.Mesh(merged, material);
      mesh.name = `Buildings-${key}`;
      mesh.matrixAutoUpdate = false;
      this.geometries.push(merged);
      this.materials.push(material);
      this.root.add(mesh);
      triangles += merged.index
        ? merged.index.count / 3
        : merged.getAttribute("position").count / 3;
    }
    if (windowMatrices.length) {
      const windowGeometry = new THREE.BoxGeometry(1.55, 1.25, 0.12);
      const windowMaterial = new THREE.MeshStandardMaterial({
        name: "building-windows",
        color: 0x29444b,
        emissive: 0x071316,
        emissiveIntensity: 0.32,
        metalness: 0.18,
        roughness: 0.28,
        side: THREE.DoubleSide,
      });
      const windows = new THREE.InstancedMesh(
        windowGeometry,
        windowMaterial,
        windowMatrices.length,
      );
      windows.name = "BuildingWindows";
      windowMatrices.forEach((matrix, index) => windows.setMatrixAt(index, matrix));
      windows.instanceMatrix.needsUpdate = true;
      this.geometries.push(windowGeometry);
      this.materials.push(windowMaterial);
      this.root.add(windows);
      triangles += windowMatrices.length * 12;
    }
    this.stats = {
      sourceBuildings: buildings.length,
      renderedBuildings,
      modeledHeightBuildings,
      drawObjects: this.root.children.length,
      triangles: Math.round(triangles),
      windows: windowMatrices.length,
    };
  }

  dispose(): void {
    this.root.removeFromParent();
    this.geometries.forEach((geometry) => geometry.dispose());
    this.materials.forEach((material) => material.dispose());
    this.root.clear();
  }
}
