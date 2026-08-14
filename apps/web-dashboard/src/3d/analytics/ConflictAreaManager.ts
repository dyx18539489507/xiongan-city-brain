import * as THREE from "three";
import type {CoordinateService} from "../core/CoordinateService";
import type {SafetyConflictEntity} from "../network/digitalTwinTypes";

const severityColor: Record<string, number> = {
  critical: 0xff3b30,
  warning: 0xffa21a,
  caution: 0xffd166,
};

function conflictRadius(conflict: SafetyConflictEntity): number {
  const proximity = THREE.MathUtils.clamp(3.4 - conflict.minimumDistanceM, 0, 2.4);
  const time = conflict.ttcS ?? conflict.petS ?? 5;
  const urgency = THREE.MathUtils.clamp(4 - time, 0, 3);
  return 2.2 + proximity * 0.55 + urgency * 0.28;
}

/**
 * Displays only conflicts observed by the trajectory-based TTC/PET monitor.
 * No static hotspot is synthesized when the current SUMO tick has no conflict.
 */
export class ConflictAreaManager {
  readonly root = new THREE.Group();

  private readonly geometries: THREE.BufferGeometry[] = [];
  private readonly materials: THREE.Material[] = [];

  constructor(private readonly coordinates: CoordinateService) {
    this.root.name = "ObservedSafetyConflicts";
    this.root.visible = false;
  }

  applySnapshot(conflicts: readonly SafetyConflictEntity[]): void {
    this.clearVisuals();
    for (const conflict of conflicts.slice(0, 24)) {
      const radius = conflictRadius(conflict);
      const color = severityColor[conflict.severity] ?? 0xffa21a;
      const geometry = new THREE.CircleGeometry(radius, 6);
      geometry.rotateX(-Math.PI / 2);
      const material = new THREE.MeshBasicMaterial({
        color,
        transparent: true,
        opacity: conflict.severity === "critical" ? 0.42 : 0.3,
        depthWrite: false,
        side: THREE.DoubleSide,
      });
      const mesh = new THREE.Mesh(geometry, material);
      const world = this.coordinates.sumoToWorld(conflict.x, conflict.y, 0.19);
      mesh.position.set(world.x, world.y, world.z);
      mesh.name = `ObservedConflict:${conflict.id}`;
      mesh.userData.entityKind = "conflict";
      mesh.userData.entityId = conflict.id;
      mesh.renderOrder = 18;
      this.geometries.push(geometry);
      this.materials.push(material);
      this.root.add(mesh);
    }
  }

  setVisible(visible: boolean): void {
    this.root.visible = visible;
  }

  count(): number {
    return this.root.children.length;
  }

  dispose(): void {
    this.clearVisuals();
    this.root.removeFromParent();
  }

  private clearVisuals(): void {
    this.root.clear();
    this.geometries.splice(0).forEach((geometry) => geometry.dispose());
    this.materials.splice(0).forEach((material) => material.dispose());
  }
}
