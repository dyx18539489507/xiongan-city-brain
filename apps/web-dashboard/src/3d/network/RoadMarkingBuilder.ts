import * as THREE from "three";
import type {CoordinateService} from "../core/CoordinateService";
import type {SceneBounds, SceneEdge, SceneLane} from "../scene/types";
import {MaterialManager} from "../scene/MaterialManager";
import {
  appendQuad,
  appendRibbon,
  clippedWorldPolylines,
  emptyBuffers,
  offsetPolyline,
  toBufferGeometry,
} from "./geometry";

export class RoadMarkingBuilder {
  constructor(
    private readonly coordinates: CoordinateService,
    private readonly materials: MaterialManager,
  ) {}

  build(
    lanes: SceneLane[],
    edges: SceneEdge[],
    controlledJunctionIds: Set<string>,
    bounds: SceneBounds,
  ): {mesh: THREE.Mesh; triangles: number; stopLines: number} {
    const buffers = emptyBuffers();
    const edgeById = new Map(edges.map((edge) => [edge.sumoEdgeId, edge]));
    let stopLines = 0;
    for (const lane of lanes) {
      if (
        lane.edgeFunction !== "ordinary" ||
        !["motor", "mixed"].includes(lane.laneKind) ||
        lane.shape.length < 2
      ) {
        continue;
      }
      const width = Math.max(0.8, Math.min(lane.widthM, 8));
      const polylines = clippedWorldPolylines(lane.shape, bounds, this.coordinates);
      for (const points of polylines) {
        appendRibbon(buffers, offsetPolyline(points, width / 2), 0.075, 0.048);
        appendRibbon(buffers, offsetPolyline(points, -width / 2), 0.075, 0.048);
      }

      const edge = edgeById.get(lane.sumoEdgeId);
      if (!edge?.toJunctionId || !controlledJunctionIds.has(edge.toJunctionId)) continue;
      const points = polylines[polylines.length - 1];
      if (!points || points.length < 2) continue;
      const end = points[points.length - 1];
      const direction = end.clone().sub(points[points.length - 2]);
      appendQuad(buffers, end.clone().addScaledVector(direction.clone().normalize(), -0.35), direction, 0.42, width * 0.94, 0.052);
      stopLines += 1;
    }
    const mesh = new THREE.Mesh(toBufferGeometry(buffers), this.materials.marking());
    mesh.name = "RoadMarkingBatch";
    return {mesh, triangles: buffers.indices.length / 3, stopLines};
  }
}
