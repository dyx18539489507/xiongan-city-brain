import * as THREE from "three";
import type {CoordinateService} from "../core/CoordinateService";
import type {SceneBounds, SceneEdge, SceneLane} from "../scene/types";
import type {LaneMaterialKey} from "../scene/MaterialManager";
import {MaterialManager} from "../scene/MaterialManager";
import {appendRibbon, clippedWorldPolylines, emptyBuffers, toBufferGeometry} from "./geometry";

function motorClass(edge: SceneEdge | undefined): LaneMaterialKey {
  const value = edge?.roadType?.toLowerCase() ?? "";
  if (value.includes("primary") || value.includes("trunk")) return "motor-primary";
  if (value.includes("secondary") || value.includes("tertiary")) return "motor-secondary";
  return "motor-local";
}

function materialKey(lane: SceneLane, edge: SceneEdge | undefined): LaneMaterialKey | null {
  if (lane.edgeFunction === "crossing") return null;
  if (lane.laneKind === "bicycle") return "bicycle";
  if (lane.laneKind === "pedestrian" || lane.laneKind === "pedestrian_area") return "pedestrian";
  if (lane.laneKind === "shared_active") return "shared";
  if (lane.laneKind === "mixed") return motorClass(edge);
  return motorClass(edge);
}

export class LaneGeometryBuilder {
  constructor(
    private readonly coordinates: CoordinateService,
    private readonly materials: MaterialManager,
  ) {}

  build(
    lanes: SceneLane[],
    edges: SceneEdge[],
    bounds: SceneBounds,
  ): {group: THREE.Group; triangles: number} {
    const edgeById = new Map(edges.map((edge) => [edge.sumoEdgeId, edge]));
    const buffersByKey = new Map<LaneMaterialKey, ReturnType<typeof emptyBuffers>>();
    for (const lane of lanes) {
      const key = materialKey(lane, edgeById.get(lane.sumoEdgeId));
      if (!key || lane.shape.length < 2) continue;
      const buffers = buffersByKey.get(key) ?? emptyBuffers();
      buffersByKey.set(key, buffers);
      for (const polyline of clippedWorldPolylines(lane.shape, bounds, this.coordinates)) {
        appendRibbon(
          buffers,
          polyline,
          Math.max(0.8, Math.min(lane.widthM, 8)),
          lane.laneKind === "pedestrian" ? 0.035 : 0.02,
        );
      }
    }

    const group = new THREE.Group();
    group.name = "SUMO_Lanes";
    let triangles = 0;
    for (const [key, buffers] of buffersByKey) {
      if (!buffers.indices.length) continue;
      const geometry = toBufferGeometry(buffers);
      triangles += buffers.indices.length / 3;
      const mesh = new THREE.Mesh(geometry, this.materials.lane(key));
      mesh.name = `LaneBatch_${key}`;
      mesh.receiveShadow = true;
      group.add(mesh);
    }
    return {group, triangles};
  }
}
