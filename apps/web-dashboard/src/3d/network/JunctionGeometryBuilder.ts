import * as THREE from "three";
import type {CoordinateService} from "../core/CoordinateService";
import type {SceneJunction} from "../scene/types";
import {MaterialManager} from "../scene/MaterialManager";
import {appendPolygon, emptyBuffers, toBufferGeometry, worldPolyline} from "./geometry";

export class JunctionGeometryBuilder {
  constructor(
    private readonly coordinates: CoordinateService,
    private readonly materials: MaterialManager,
  ) {}

  build(junctions: SceneJunction[]): {mesh: THREE.Mesh; triangles: number} {
    const buffers = emptyBuffers();
    for (const junction of junctions) {
      appendPolygon(buffers, worldPolyline(junction.shape, this.coordinates), 0.012);
    }
    const mesh = new THREE.Mesh(toBufferGeometry(buffers), this.materials.junction());
    mesh.name = "SUMO_JunctionBatch";
    mesh.receiveShadow = true;
    return {mesh, triangles: buffers.indices.length / 3};
  }
}
