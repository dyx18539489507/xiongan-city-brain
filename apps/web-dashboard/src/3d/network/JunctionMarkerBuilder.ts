import * as THREE from "three";
import type {CoordinateService} from "../core/CoordinateService";
import type {SceneJunction} from "../scene/types";
import {MaterialManager} from "../scene/MaterialManager";

export class JunctionMarkerBuilder {
  constructor(
    private readonly coordinates: CoordinateService,
    private readonly materials: MaterialManager,
  ) {}

  build(junctions: SceneJunction[]): THREE.InstancedMesh {
    const controlled = junctions.filter((item) => item.controlled);
    const geometry = new THREE.RingGeometry(4.2, 6, 24);
    geometry.rotateX(-Math.PI / 2);
    const mesh = new THREE.InstancedMesh(geometry, this.materials.marker(), controlled.length);
    mesh.name = "ControlledJunctionMarkers";
    const matrix = new THREE.Matrix4();
    const color = new THREE.Color();
    controlled.forEach((junction, index) => {
      const world = this.coordinates.sumoToWorld(junction.position.x, junction.position.y, 0.07);
      matrix.makeTranslation(world.x, world.y, world.z);
      mesh.setMatrixAt(index, matrix);
      mesh.setColorAt(index, color.setHex(junction.role === "core_corridor" ? 0x35d5b3 : 0x65a9c2));
    });
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    return mesh;
  }
}
