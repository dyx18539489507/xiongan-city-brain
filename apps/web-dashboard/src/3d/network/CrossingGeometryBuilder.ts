import * as THREE from "three";
import type {CoordinateService} from "../core/CoordinateService";
import type {SceneCrossing} from "../scene/types";
import {MaterialManager} from "../scene/MaterialManager";
import {
  appendQuad,
  appendRibbon,
  emptyBuffers,
  toBufferGeometry,
  worldPolyline,
} from "./geometry";

export class CrossingGeometryBuilder {
  constructor(
    private readonly coordinates: CoordinateService,
    private readonly materials: MaterialManager,
  ) {}

  build(crossings: SceneCrossing[]): {group: THREE.Group; triangles: number} {
    const base = emptyBuffers();
    const stripes = emptyBuffers();
    for (const crossing of crossings) {
      const points = worldPolyline(crossing.shape, this.coordinates);
      if (points.length < 2) continue;
      const width = Math.max(1.5, Math.min(crossing.widthM, 8));
      appendRibbon(base, points, width, 0.027);
      for (let index = 0; index < points.length - 1; index += 1) {
        const start = points[index];
        const end = points[index + 1];
        const direction = end.clone().sub(start);
        const length = direction.length();
        if (length < 0.2) continue;
        const tangent = direction.clone().normalize();
        for (let distance = 0.55; distance < length; distance += 1.1) {
          const center = start.clone().addScaledVector(tangent, distance);
          appendQuad(stripes, center, tangent, 0.52, width * 0.82, 0.045);
        }
      }
    }
    const group = new THREE.Group();
    group.name = "SUMO_Crossings";
    const baseMesh = new THREE.Mesh(toBufferGeometry(base), this.materials.crossingBase());
    baseMesh.name = "CrossingBaseBatch";
    const stripeMesh = new THREE.Mesh(toBufferGeometry(stripes), this.materials.marking());
    stripeMesh.name = "ZebraStripeBatch";
    group.add(baseMesh, stripeMesh);
    return {group, triangles: (base.indices.length + stripes.indices.length) / 3};
  }
}
