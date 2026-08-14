import * as THREE from "three";
import type {CoordinateService} from "../core/CoordinateService";
import type {Point2, SceneBounds} from "../scene/types";

export type GeometryBuffers = {
  positions: number[];
  normals: number[];
  uvs: number[];
  indices: number[];
};

export function emptyBuffers(): GeometryBuffers {
  return {positions: [], normals: [], uvs: [], indices: []};
}

function appendVertex(buffers: GeometryBuffers, x: number, y: number, z: number): number {
  const index = buffers.positions.length / 3;
  buffers.positions.push(x, y, z);
  buffers.normals.push(0, 1, 0);
  buffers.uvs.push(x / 8, z / 8);
  return index;
}

export function worldPolyline(points: Point2[], coordinates: CoordinateService): THREE.Vector2[] {
  return points.map((point) => {
    const world = coordinates.sumoToWorld(point.x, point.y);
    return new THREE.Vector2(world.x, world.z);
  });
}

function clipSegment(
  start: Point2,
  end: Point2,
  bounds: SceneBounds,
): [Point2, Point2] | null {
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  let minimum = 0;
  let maximum = 1;
  const tests: Array<[number, number]> = [
    [-dx, start.x - bounds.minX],
    [dx, bounds.maxX - start.x],
    [-dy, start.y - bounds.minY],
    [dy, bounds.maxY - start.y],
  ];
  for (const [direction, distance] of tests) {
    if (Math.abs(direction) < 1e-9) {
      if (distance < 0) return null;
      continue;
    }
    const ratio = distance / direction;
    if (direction < 0) minimum = Math.max(minimum, ratio);
    else maximum = Math.min(maximum, ratio);
    if (minimum > maximum) return null;
  }
  return [
    {x: start.x + minimum * dx, y: start.y + minimum * dy},
    {x: start.x + maximum * dx, y: start.y + maximum * dy},
  ];
}

export function clippedWorldPolylines(
  points: Point2[],
  bounds: SceneBounds,
  coordinates: CoordinateService,
): THREE.Vector2[][] {
  const result: Point2[][] = [];
  let current: Point2[] = [];
  for (let index = 0; index < points.length - 1; index += 1) {
    const clipped = clipSegment(points[index], points[index + 1], bounds);
    if (!clipped) {
      if (current.length > 1) result.push(current);
      current = [];
      continue;
    }
    const [start, end] = clipped;
    const previous = current[current.length - 1];
    if (!previous || Math.hypot(previous.x - start.x, previous.y - start.y) > 1e-6) {
      if (current.length > 1) result.push(current);
      current = [start];
    }
    current.push(end);
  }
  if (current.length > 1) result.push(current);
  return result.map((polyline) => worldPolyline(polyline, coordinates));
}

function sideNormal(left: THREE.Vector2, right: THREE.Vector2): THREE.Vector2 {
  const direction = right.clone().sub(left);
  if (direction.lengthSq() < 1e-8) return new THREE.Vector2(1, 0);
  direction.normalize();
  return new THREE.Vector2(-direction.y, direction.x);
}

export function offsetPolyline(points: THREE.Vector2[], offset: number): THREE.Vector2[] {
  if (points.length < 2) return [];
  return points.map((point, index) => {
    const previous = sideNormal(points[Math.max(0, index - 1)], points[index]);
    const next = sideNormal(points[index], points[Math.min(points.length - 1, index + 1)]);
    let normal = index === 0 ? next : index === points.length - 1 ? previous : previous.add(next);
    if (normal.lengthSq() < 1e-8) normal = next;
    normal.normalize();
    const reference = index === 0 ? next : previous;
    const denominator = Math.max(Math.abs(normal.dot(reference)), 0.5);
    return point.clone().addScaledVector(normal, offset / denominator);
  });
}

export function appendRibbon(
  buffers: GeometryBuffers,
  points: THREE.Vector2[],
  width: number,
  height: number,
): void {
  if (points.length < 2 || width <= 0) return;
  const left = offsetPolyline(points, width / 2);
  const right = offsetPolyline(points, -width / 2);
  const base = buffers.positions.length / 3;
  for (let index = 0; index < points.length; index += 1) {
    appendVertex(buffers, left[index].x, height, left[index].y);
    appendVertex(buffers, right[index].x, height, right[index].y);
  }
  for (let index = 0; index < points.length - 1; index += 1) {
    const start = base + index * 2;
    buffers.indices.push(start, start + 2, start + 1, start + 1, start + 2, start + 3);
  }
}

export function appendPolygon(
  buffers: GeometryBuffers,
  points: THREE.Vector2[],
  height: number,
): void {
  if (points.length < 3) return;
  const ring = points[0].equals(points[points.length - 1]) ? points.slice(0, -1) : points;
  if (ring.length < 3) return;
  const base = buffers.positions.length / 3;
  for (const point of ring) appendVertex(buffers, point.x, height, point.y);
  const faces = THREE.ShapeUtils.triangulateShape(ring, []);
  for (const face of faces) buffers.indices.push(base + face[0], base + face[1], base + face[2]);
}

export function appendQuad(
  buffers: GeometryBuffers,
  center: THREE.Vector2,
  along: THREE.Vector2,
  length: number,
  width: number,
  height: number,
): void {
  if (along.lengthSq() < 1e-8 || length <= 0 || width <= 0) return;
  const tangent = along.clone().normalize();
  const side = new THREE.Vector2(-tangent.y, tangent.x);
  const halfLength = tangent.multiplyScalar(length / 2);
  const halfWidth = side.multiplyScalar(width / 2);
  const points = [
    center.clone().sub(halfLength).sub(halfWidth),
    center.clone().add(halfLength).sub(halfWidth),
    center.clone().add(halfLength).add(halfWidth),
    center.clone().sub(halfLength).add(halfWidth),
  ];
  appendPolygon(buffers, points, height);
}

export function toBufferGeometry(buffers: GeometryBuffers): THREE.BufferGeometry {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(buffers.positions, 3));
  geometry.setAttribute("normal", new THREE.Float32BufferAttribute(buffers.normals, 3));
  const uv = new THREE.Float32BufferAttribute(buffers.uvs, 2);
  geometry.setAttribute("uv", uv);
  geometry.setAttribute("uv1", uv.clone());
  geometry.setIndex(buffers.indices);
  geometry.computeBoundingSphere();
  return geometry;
}

export function disposeObject(root: THREE.Object3D): void {
  root.traverse((object) => {
    const mesh = object as THREE.Mesh;
    mesh.geometry?.dispose();
    const materials = Array.isArray(mesh.material) ? mesh.material : mesh.material ? [mesh.material] : [];
    for (const material of materials) material.dispose();
  });
}
