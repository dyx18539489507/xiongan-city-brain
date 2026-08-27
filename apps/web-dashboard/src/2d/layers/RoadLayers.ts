import type {Point2, SceneLane} from "../../3d/scene/types";
import {mapTheme} from "../theme";
import type {LayerRenderContext, TrafficMapLayer} from "./LayerTypes";
import {appendPolygon, appendPolyline, geometryIntersectsBounds} from "./LayerTypes";

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
    const edgeBatches = new Map<number, Array<readonly Point2[]>>();
    const surfaceBatches = new Map<string, {color: string; width: number; shapes: Array<readonly Point2[]>}>();
    for (const indexed of world.indexedLanes) {
      const lane = indexed.lane;
      if (lane.shape.length < 2 || (lane.edgeFunction === "internal" && camera.scale < .22)) continue;
      if (!geometryIntersectsBounds(indexed, visibleBounds)) continue;
      const width = Math.max(.8, Math.min(14, lane.widthM * camera.scale));
      const edgeWidth = width + Math.max(1.4, camera.scale * 1.8);
      const edgeShapes = edgeBatches.get(edgeWidth);
      if (edgeShapes) edgeShapes.push(lane.shape);
      else edgeBatches.set(edgeWidth, [lane.shape]);

      const color = laneSurface(lane);
      const key = `${color}|${width}`;
      const surfaceBatch = surfaceBatches.get(key);
      if (surfaceBatch) surfaceBatch.shapes.push(lane.shape);
      else surfaceBatches.set(key, {color, width, shapes: [lane.shape]});
    }

    ctx.strokeStyle = mapTheme.roadEdge;
    for (const [width, shapes] of edgeBatches) {
      ctx.lineWidth = width;
      ctx.beginPath();
      for (const shape of shapes) appendPolyline(ctx, camera, shape);
      ctx.stroke();
    }
    for (const batch of surfaceBatches.values()) {
      ctx.strokeStyle = batch.color;
      ctx.lineWidth = batch.width;
      ctx.beginPath();
      for (const shape of batch.shapes) appendPolyline(ctx, camera, shape);
      ctx.stroke();
    }

    const junctionShapes: Array<readonly Point2[]> = [];
    for (const indexed of world.indexedJunctions) {
      if (!geometryIntersectsBounds(indexed, visibleBounds)) continue;
      const junction = indexed.junction;
      if (junction.shape.length < 3 || (!junction.controlled && camera.scale < .34)) continue;
      junctionShapes.push(junction.shape);
    }
    if (junctionShapes.length) {
      ctx.beginPath();
      for (const shape of junctionShapes) appendPolygon(ctx, camera, shape);
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
    ctx.strokeStyle = "rgba(7, 154, 146, .24)";
    ctx.lineWidth = Math.max(5, camera.scale * 13);
    ctx.beginPath();
    for (const edgeId of world.corridorEdgeIds) {
      const edge = world.edgeById.get(edgeId);
      if (edge?.shape) appendPolyline(ctx, camera, edge.shape);
    }
    ctx.stroke();
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
    ctx.beginPath();
    for (const indexed of world.indexedLanes) {
      const lane = indexed.lane;
      if (!geometryIntersectsBounds(indexed, visibleBounds)) continue;
      if (lane.edgeFunction === "internal" || lane.laneKind === "bicycle" || lane.laneKind === "pedestrian" || lane.shape.length < 2) continue;
      appendPolyline(ctx, camera, lane.shape);
    }
    ctx.stroke();
    ctx.setLineDash([]);

    // SUMO lane endpoints provide truthful stop-line placement; no turn movement is inferred.
    if (camera.scale > .48) {
      ctx.strokeStyle = mapTheme.crossing;
      ctx.lineWidth = 2;
      ctx.beginPath();
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
        ctx.moveTo(end.x + Math.cos(angle) * half, end.y + Math.sin(angle) * half);
        ctx.lineTo(end.x - Math.cos(angle) * half, end.y - Math.sin(angle) * half);
      }
      ctx.stroke();

      ctx.strokeStyle = mapTheme.crossing;
      ctx.lineWidth = camera.scale > .9 ? 4 : 2;
      ctx.setLineDash(camera.scale > .9 ? [3, 3] : [2, 3]);
      ctx.beginPath();
      for (const crossing of world.scene.crossings) appendPolyline(ctx, camera, crossing.shape);
      ctx.stroke();
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
