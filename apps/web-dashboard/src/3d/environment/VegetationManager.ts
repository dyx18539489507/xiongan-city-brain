import * as THREE from "three";
import {mergeGeometries} from "three/addons/utils/BufferGeometryUtils.js";
import type {CoordinateService} from "../core/CoordinateService";
import type {Point2, SceneLane, SceneVegetationArea} from "../scene/types";

export type VegetationStats = {
  areas: number;
  trees: number;
  drawObjects: number;
  triangles: number;
};

type Segment = {a: Point2; b: Point2};

function stableUnit(value: string): number {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = (Math.imul(hash, 31) + value.charCodeAt(index)) | 0;
  }
  return (hash >>> 0) / 0xffffffff;
}

function pointInPolygon(point: Point2, polygon: Point2[]): boolean {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i, i += 1) {
    const a = polygon[i];
    const b = polygon[j];
    if (!a || !b) continue;
    const intersects =
      (a.y > point.y) !== (b.y > point.y) &&
      point.x < ((b.x - a.x) * (point.y - a.y)) / (b.y - a.y || Number.EPSILON) + a.x;
    if (intersects) inside = !inside;
  }
  return inside;
}

function distanceToSegment(point: Point2, segment: Segment): number {
  const dx = segment.b.x - segment.a.x;
  const dy = segment.b.y - segment.a.y;
  const lengthSquared = dx * dx + dy * dy;
  if (lengthSquared === 0) return Math.hypot(point.x - segment.a.x, point.y - segment.a.y);
  const ratio = Math.max(
    0,
    Math.min(1, ((point.x - segment.a.x) * dx + (point.y - segment.a.y) * dy) / lengthSquared),
  );
  return Math.hypot(
    point.x - (segment.a.x + ratio * dx),
    point.y - (segment.a.y + ratio * dy),
  );
}

function roadSegments(lanes: SceneLane[]): Segment[] {
  const result: Segment[] = [];
  for (const lane of lanes) {
    if (lane.edgeFunction !== "ordinary") continue;
    for (let index = 1; index < lane.shape.length; index += 1) {
      const a = lane.shape[index - 1];
      const b = lane.shape[index];
      if (a && b) result.push({a, b});
    }
  }
  return result;
}

function grassShape(
  coordinateService: CoordinateService,
  area: SceneVegetationArea,
): THREE.Shape | null {
  if (area.shape.length < 3) return null;
  const shape = new THREE.Shape();
  area.shape.forEach((point, index) => {
    const world = coordinateService.sumoToWorld(point.x, point.y);
    if (index === 0) shape.moveTo(world.x, -world.z);
    else shape.lineTo(world.x, -world.z);
  });
  shape.closePath();
  return shape;
}

export class VegetationManager {
  readonly root = new THREE.Group();
  readonly stats: VegetationStats;

  private readonly geometries: THREE.BufferGeometry[] = [];
  private readonly materials: THREE.Material[] = [];

  constructor(
    coordinateService: CoordinateService,
    areas: SceneVegetationArea[],
    lanes: SceneLane[],
  ) {
    this.root.name = "VegetationManager";
    const grassPieces: THREE.BufferGeometry[] = [];
    const treePoints: Array<{position: Point2; scale: number; rotation: number}> = [];
    const segments = roadSegments(lanes);

    for (const area of areas) {
      const shape = grassShape(coordinateService, area);
      if (shape) {
        const geometry = new THREE.ShapeGeometry(shape, 1);
        geometry.rotateX(-Math.PI / 2);
        geometry.translate(0, 0.035, 0);
        grassPieces.push(geometry);
      }
      const xs = area.shape.map((point) => point.x);
      const ys = area.shape.map((point) => point.y);
      if (!xs.length || !ys.length) continue;
      const minimumX = Math.min(...xs);
      const maximumX = Math.max(...xs);
      const minimumY = Math.min(...ys);
      const maximumY = Math.max(...ys);
      const spacing = 46;
      for (let x = minimumX + spacing / 2; x < maximumX; x += spacing) {
        for (let y = minimumY + spacing / 2; y < maximumY; y += spacing) {
          if (treePoints.length >= 720) break;
          const key = `${area.sceneId}:${Math.round(x)}:${Math.round(y)}`;
          const point = {
            x: x + (stableUnit(`${key}:x`) - 0.5) * 15,
            y: y + (stableUnit(`${key}:y`) - 0.5) * 15,
          };
          if (!pointInPolygon(point, area.shape)) continue;
          if (segments.some((segment) => distanceToSegment(point, segment) < 7.5)) continue;
          treePoints.push({
            position: point,
            scale: 0.78 + stableUnit(`${key}:scale`) * 0.48,
            rotation: stableUnit(`${key}:rotation`) * Math.PI * 2,
          });
        }
      }
    }

    if (grassPieces.length) {
      const grassGeometry = mergeGeometries(grassPieces, false);
      grassPieces.forEach((piece) => piece.dispose());
      if (grassGeometry) {
        const grassMaterial = new THREE.MeshStandardMaterial({
          name: "vegetation-ground",
          color: 0x405d3c,
          roughness: 1,
        });
        const grass = new THREE.Mesh(grassGeometry, grassMaterial);
        grass.name = "OSMVegetationAreas";
        grass.matrixAutoUpdate = false;
        this.geometries.push(grassGeometry);
        this.materials.push(grassMaterial);
        this.root.add(grass);
      }
    }

    if (treePoints.length) {
      const trunkGeometry = new THREE.CylinderGeometry(0.18, 0.24, 2.8, 6);
      const crownGeometry = new THREE.IcosahedronGeometry(1.65, 1);
      const trunkMaterial = new THREE.MeshStandardMaterial({color: 0x66513d, roughness: 1});
      const crownMaterial = new THREE.MeshStandardMaterial({color: 0x315d37, roughness: 0.94});
      const trunks = new THREE.InstancedMesh(trunkGeometry, trunkMaterial, treePoints.length);
      const crowns = new THREE.InstancedMesh(crownGeometry, crownMaterial, treePoints.length);
      trunks.name = "TreeTrunks";
      crowns.name = "TreeCrowns";
      const matrix = new THREE.Matrix4();
      const quaternion = new THREE.Quaternion();
      treePoints.forEach((tree, index) => {
        const world = coordinateService.sumoToWorld(tree.position.x, tree.position.y);
        quaternion.setFromAxisAngle(new THREE.Vector3(0, 1, 0), tree.rotation);
        matrix.compose(
          new THREE.Vector3(world.x, 1.4 * tree.scale, world.z),
          quaternion,
          new THREE.Vector3(tree.scale, tree.scale, tree.scale),
        );
        trunks.setMatrixAt(index, matrix);
        matrix.compose(
          new THREE.Vector3(world.x, 3.55 * tree.scale, world.z),
          quaternion,
          new THREE.Vector3(tree.scale, tree.scale * 1.08, tree.scale),
        );
        crowns.setMatrixAt(index, matrix);
      });
      trunks.instanceMatrix.needsUpdate = true;
      crowns.instanceMatrix.needsUpdate = true;
      this.geometries.push(trunkGeometry, crownGeometry);
      this.materials.push(trunkMaterial, crownMaterial);
      this.root.add(trunks, crowns);
    }

    const triangles = this.root.children.reduce((total, child) => {
      const mesh = child as THREE.Mesh;
      const geometry = mesh.geometry;
      if (!geometry) return total;
      const perInstance = geometry.index
        ? geometry.index.count / 3
        : geometry.getAttribute("position").count / 3;
      const instances = child instanceof THREE.InstancedMesh ? child.count : 1;
      return total + perInstance * instances;
    }, 0);
    this.stats = {
      areas: areas.length,
      trees: treePoints.length,
      drawObjects: this.root.children.length,
      triangles: Math.round(triangles),
    };
  }

  dispose(): void {
    this.root.removeFromParent();
    this.geometries.forEach((geometry) => geometry.dispose());
    this.materials.forEach((material) => material.dispose());
    this.root.clear();
  }
}
