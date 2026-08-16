import type {SceneLane} from "../../3d/scene/types";
import {mapTheme} from "../theme";
import type {LayerRenderContext, TrafficMapLayer} from "./LayerTypes";
import {geometryIntersectsBounds, strokePolyline, tracePolygon} from "./LayerTypes";

function laneSurface(lane: SceneLane): string {
  if (lane.laneKind === "bicycle") return mapTheme.bicycleLane;
  if (lane.laneKind === "pedestrian") return mapTheme.pedestrianLane;
  return lane.edgeFunction === "internal" ? mapTheme.roadSurfaceMuted : mapTheme.roadSurface;
}

export class RoadSurfaceLayer implements TrafficMapLayer {
  readonly id = "baseMap" as const;
  readonly isStatic = true;

  render({ctx, camera, world, visibleBounds}: LayerRenderContext): void {
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    for (const indexed of world.indexedLanes) {
      const lane = indexed.lane;
      if (lane.shape.length < 2 || (lane.edgeFunction === "internal" && camera.scale < .22)) continue;
      if (!geometryIntersectsBounds(indexed, visibleBounds)) continue;
      const width = Math.max(.8, Math.min(14, lane.widthM * camera.scale));
      ctx.strokeStyle = mapTheme.roadEdge;
      ctx.lineWidth = width + Math.max(1.4, camera.scale * 1.8);
      strokePolyline(ctx, camera, lane.shape);
      ctx.strokeStyle = laneSurface(lane);
      ctx.lineWidth = width;
      strokePolyline(ctx, camera, lane.shape);
    }

    for (const indexed of world.indexedJunctions) {
      if (!geometryIntersectsBounds(indexed, visibleBounds)) continue;
      const junction = indexed.junction;
      if (junction.shape.length < 3 || (!junction.controlled && camera.scale < .34)) continue;
      tracePolygon(ctx, camera, junction.shape);
      ctx.fillStyle = mapTheme.junction;
      ctx.fill();
      if (camera.scale > .55) {
        ctx.strokeStyle = mapTheme.roadEdgeLine;
        ctx.lineWidth = .8;
        ctx.stroke();
      }
    }
  }

  destroy(): void {}
}

export class CorridorLayer implements TrafficMapLayer {
  readonly id = "corridor" as const;
  readonly isStatic = true;

  render({ctx, camera, world}: LayerRenderContext): void {
    ctx.save();
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.strokeStyle = "rgba(91, 159, 228, .18)";
    ctx.lineWidth = Math.max(5, camera.scale * 13);
    for (const edgeId of world.corridorEdgeIds) {
      const edge = world.edgeById.get(edgeId);
      if (edge?.shape) strokePolyline(ctx, camera, edge.shape);
    }
    ctx.restore();
  }

  destroy(): void {}
}

export class RoadMarkingLayer implements TrafficMapLayer {
  readonly id = "roadMarkings" as const;
  readonly isStatic = true;

  render({ctx, camera, world, visibleBounds}: LayerRenderContext): void {
    if (camera.scale < .28) return;
    ctx.save();
    ctx.lineCap = "butt";
    ctx.strokeStyle = mapTheme.laneMarking;
    ctx.lineWidth = camera.scale > .75 ? 1.15 : .75;
    ctx.setLineDash(camera.scale > .75 ? [9, 9] : [5, 7]);
    for (const indexed of world.indexedLanes) {
      const lane = indexed.lane;
      if (!geometryIntersectsBounds(indexed, visibleBounds)) continue;
      if (lane.edgeFunction === "internal" || lane.laneKind === "bicycle" || lane.laneKind === "pedestrian" || lane.shape.length < 2) continue;
      strokePolyline(ctx, camera, lane.shape);
    }
    ctx.setLineDash([]);

    // SUMO lane endpoints provide truthful stop-line placement; no turn movement is inferred.
    if (camera.scale > .48) {
      ctx.strokeStyle = mapTheme.crossing;
      ctx.lineWidth = 2;
      for (const indexed of world.indexedLanes) {
        const lane = indexed.lane;
        if (!geometryIntersectsBounds(indexed, visibleBounds)) continue;
        if (lane.laneKind === "bicycle" || lane.laneKind === "pedestrian" || lane.edgeFunction === "internal" || lane.shape.length < 2) continue;
        const edge = world.edgeById.get(lane.sumoEdgeId);
        if (!edge?.toJunctionId || !world.junctionById.get(edge.toJunctionId)?.controlled) continue;
        const end = camera.worldToScreen(lane.shape.at(-1)!);
        const previous = camera.worldToScreen(lane.shape.at(-2)!);
        const angle = Math.atan2(end.y - previous.y, end.x - previous.x) + Math.PI / 2;
        const half = Math.max(2, lane.widthM * camera.scale * .55);
        ctx.beginPath();
        ctx.moveTo(end.x + Math.cos(angle) * half, end.y + Math.sin(angle) * half);
        ctx.lineTo(end.x - Math.cos(angle) * half, end.y - Math.sin(angle) * half);
        ctx.stroke();
      }

      ctx.strokeStyle = mapTheme.crossing;
      ctx.lineWidth = camera.scale > .9 ? 4 : 2;
      ctx.setLineDash(camera.scale > .9 ? [3, 3] : [2, 3]);
      for (const crossing of world.scene.crossings) strokePolyline(ctx, camera, crossing.shape);
      ctx.setLineDash([]);
    }

    if (camera.scale > .72) {
      ctx.fillStyle = mapTheme.laneMarking;
      for (const indexed of world.indexedLanes) {
        const lane = indexed.lane;
        if (!geometryIntersectsBounds(indexed, visibleBounds)) continue;
        if (lane.laneKind === "bicycle" || lane.laneKind === "pedestrian" || lane.edgeFunction === "internal" || lane.shape.length < 2) continue;
        const midIndex = Math.floor((lane.shape.length - 1) / 2);
        const start = camera.worldToScreen(lane.shape[midIndex]);
        const end = camera.worldToScreen(lane.shape[midIndex + 1]);
        const angle = Math.atan2(end.y - start.y, end.x - start.x);
        ctx.save();
        ctx.translate((start.x + end.x) / 2, (start.y + end.y) / 2);
        ctx.rotate(angle);
        ctx.beginPath();
        ctx.moveTo(5, 0); ctx.lineTo(-3, -3); ctx.lineTo(-1, 0); ctx.lineTo(-3, 3); ctx.closePath();
        ctx.fill();
        ctx.restore();
      }
    }
    ctx.restore();
  }

  destroy(): void {}
}
