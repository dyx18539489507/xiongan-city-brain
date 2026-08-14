import * as THREE from "three";
import type {CoordinateService} from "../core/CoordinateService";
import type {Point2, SceneLane} from "../scene/types";

export type StreetFurnitureStats = {
  streetLights: number;
  drawObjects: number;
  triangles: number;
};

function polylineLength(shape: Point2[]): number {
  let total = 0;
  for (let index = 1; index < shape.length; index += 1) {
    const a = shape[index - 1];
    const b = shape[index];
    if (a && b) total += Math.hypot(b.x - a.x, b.y - a.y);
  }
  return total;
}

function midpoint(shape: Point2[]): {point: Point2; tangent: Point2} | null {
  const total = polylineLength(shape);
  if (total < 15) return null;
  const target = total / 2;
  let traversed = 0;
  for (let index = 1; index < shape.length; index += 1) {
    const a = shape[index - 1];
    const b = shape[index];
    if (!a || !b) continue;
    const length = Math.hypot(b.x - a.x, b.y - a.y);
    if (traversed + length >= target && length > 0) {
      const ratio = (target - traversed) / length;
      return {
        point: {x: a.x + (b.x - a.x) * ratio, y: a.y + (b.y - a.y) * ratio},
        tangent: {x: (b.x - a.x) / length, y: (b.y - a.y) / length},
      };
    }
    traversed += length;
  }
  return null;
}

export class StreetFurnitureManager {
  readonly root = new THREE.Group();
  readonly stats: StreetFurnitureStats;

  private readonly geometries: THREE.BufferGeometry[] = [];
  private readonly materials: THREE.Material[] = [];

  constructor(coordinateService: CoordinateService, lanes: SceneLane[]) {
    this.root.name = "StreetFurnitureManager";
    const outerLaneByEdge = new Map<string, SceneLane>();
    for (const lane of lanes) {
      if (lane.edgeFunction !== "ordinary" || lane.laneKind !== "motor") continue;
      const current = outerLaneByEdge.get(lane.sumoEdgeId);
      if (!current || lane.index > current.index) outerLaneByEdge.set(lane.sumoEdgeId, lane);
    }
    const placements: Array<{position: THREE.Vector3; yaw: number}> = [];
    for (const lane of outerLaneByEdge.values()) {
      if (placements.length >= 900) break;
      const center = midpoint(lane.shape);
      if (!center) continue;
      const sideOffset = lane.widthM / 2 + 1.25;
      const sumoX = center.point.x + center.tangent.y * sideOffset;
      const sumoY = center.point.y - center.tangent.x * sideOffset;
      const world = coordinateService.sumoToWorld(sumoX, sumoY);
      placements.push({
        position: new THREE.Vector3(world.x, 0, world.z),
        yaw: Math.atan2(center.tangent.x, -center.tangent.y),
      });
    }

    if (placements.length) {
      const poleGeometry = new THREE.CylinderGeometry(0.07, 0.1, 6.2, 8);
      const headGeometry = new THREE.BoxGeometry(0.82, 0.14, 0.28);
      const poleMaterial = new THREE.MeshStandardMaterial({color: 0x384143, roughness: 0.58});
      const headMaterial = new THREE.MeshStandardMaterial({
        name: "street-light-head",
        color: 0xc5d5c8,
        emissive: 0x273f36,
        emissiveIntensity: 0.22,
        roughness: 0.42,
      });
      const poles = new THREE.InstancedMesh(poleGeometry, poleMaterial, placements.length);
      const heads = new THREE.InstancedMesh(headGeometry, headMaterial, placements.length);
      poles.name = "StreetLightPoles";
      heads.name = "StreetLightHeads";
      const matrix = new THREE.Matrix4();
      const quaternion = new THREE.Quaternion();
      placements.forEach((placement, index) => {
        matrix.makeTranslation(placement.position.x, 3.1, placement.position.z);
        poles.setMatrixAt(index, matrix);
        quaternion.setFromAxisAngle(new THREE.Vector3(0, 1, 0), placement.yaw);
        matrix.compose(
          new THREE.Vector3(
            placement.position.x + Math.sin(placement.yaw) * 0.34,
            6.18,
            placement.position.z + Math.cos(placement.yaw) * 0.34,
          ),
          quaternion,
          new THREE.Vector3(1, 1, 1),
        );
        heads.setMatrixAt(index, matrix);
      });
      poles.instanceMatrix.needsUpdate = true;
      heads.instanceMatrix.needsUpdate = true;
      this.geometries.push(poleGeometry, headGeometry);
      this.materials.push(poleMaterial, headMaterial);
      this.root.add(poles, heads);
    }
    const perPoleTriangles = 32;
    const perHeadTriangles = 12;
    this.stats = {
      streetLights: placements.length,
      drawObjects: this.root.children.length,
      triangles: placements.length * (perPoleTriangles + perHeadTriangles),
    };
  }

  dispose(): void {
    this.root.removeFromParent();
    this.geometries.forEach((geometry) => geometry.dispose());
    this.materials.forEach((material) => material.dispose());
    this.root.clear();
  }
}
