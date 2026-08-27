import type {Point2, SceneLane} from "../../3d/scene/types";
import {mapTheme} from "../theme";
import type {LayerRenderContext, TrafficMapLayer} from "./LayerTypes";
import {appendPolygon, appendPolyline, geometryIntersectsBounds} from "./LayerTypes";

export type RoadLevelOfDetail = "overview" | "district" | "street";

export function roadLevelOfDetail(zoomRatio: number): RoadLevelOfDetail {
  if (zoomRatio < 2.5) return "overview";
  if (zoomRatio < 9) return "district";
  return "street";
}

function isSpecialLane(lane: SceneLane): boolean {
  return lane.laneKind === "bicycle" || lane.laneKind === "pedestrian";
}

function roundedWidth(width: number): number {
  return Math.round(width * 2) / 2;
}

export function offsetPolyline(points: readonly Point2[], offsetM: number): Point2[] {
  if (points.length < 2 || offsetM === 0) return [...points];
  return points.map((point, index) => {
    const previous = points[Math.max(0, index - 1)];
    const next = points[Math.min(points.length - 1, index + 1)];
    const dx = next.x - previous.x;
    const dy = next.y - previous.y;
    const length = Math.hypot(dx, dy) || 1;
    return {x: point.x - dy / length * offsetM, y: point.y + dx / length * offsetM};
  });
}

function laneSurface(lane: SceneLane): string {
  if (lane.laneKind === "bicycle") return mapTheme.bicycleLane;
  if (lane.laneKind === "pedestrian") return mapTheme.pedestrianLane;
  return lane.edgeFunction === "internal" ? mapTheme.roadSurfaceMuted : mapTheme.roadSurface;
}

export class RoadSurfaceLayer implements TrafficMapLayer {
  readonly id = "baseMap" as const;
  readonly isStatic = true;

  render({ctx, camera, world, visibleBounds}: LayerRenderContext): void {
    const detail = roadLevelOfDetail(camera.getZoomRatio());
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    const edgeBatches = new Map<number, Array<readonly Point2[]>>();
    const surfaceBatches = new Map<string, {color: string; width: number; shapes: Array<readonly Point2[]>}>();
    for (const indexed of world.indexedEdges) {
      const edge = indexed.edge;
      if (edge.function === "internal") continue;
      if (!geometryIntersectsBounds(indexed, visibleBounds)) continue;
      const lanes = edge.laneIds.map((id) => world.laneById.get(id)).filter((lane): lane is SceneLane => Boolean(lane));
      const motorLanes = lanes.filter((lane) => !isSpecialLane(lane));
      const surfaceLanes = motorLanes.length ? motorLanes : lanes;
      const widthM = Math.max(3.2, Math.min(28, surfaceLanes.reduce((sum, lane) => sum + lane.widthM, 0)));
      const maximumWidth = detail === "overview" ? 12 : detail === "district" ? 32 : 48;
      const width = roundedWidth(Math.max(detail === "overview" ? 1.5 : 2.2, Math.min(maximumWidth, widthM * camera.scale)));
      const edgeWidth = roundedWidth(width + (detail === "overview" ? 1.2 : 2));
      const edgeShapes = edgeBatches.get(edgeWidth);
      if (edgeShapes) edgeShapes.push(indexed.shape);
      else edgeBatches.set(edgeWidth, [indexed.shape]);

      const color = mapTheme.roadSurface;
      const key = `${color}|${width}`;
      const surfaceBatch = surfaceBatches.get(key);
      if (surfaceBatch) surfaceBatch.shapes.push(indexed.shape);
      else surfaceBatches.set(key, {color, width, shapes: [indexed.shape]});
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

    if (detail !== "overview") {
      const specialBatches = new Map<string, {color: string; width: number; shapes: Array<readonly Point2[]>}>();
      for (const indexed of world.indexedLanes) {
        const lane = indexed.lane;
        if (!isSpecialLane(lane) || lane.edgeFunction === "internal" || !geometryIntersectsBounds(indexed, visibleBounds)) continue;
        const color = laneSurface(lane);
        const width = roundedWidth(Math.max(1.2, Math.min(12, lane.widthM * camera.scale)));
        const key = `${color}|${width}`;
        const batch = specialBatches.get(key);
        if (batch) batch.shapes.push(lane.shape);
        else specialBatches.set(key, {color, width, shapes: [lane.shape]});
      }
      for (const batch of specialBatches.values()) {
        ctx.strokeStyle = batch.color;
        ctx.lineWidth = batch.width;
        ctx.beginPath();
        for (const shape of batch.shapes) appendPolyline(ctx, camera, shape);
        ctx.stroke();
      }
    }

    const junctionShapes: Array<readonly Point2[]> = [];
    for (const indexed of world.indexedJunctions) {
      if (!geometryIntersectsBounds(indexed, visibleBounds)) continue;
      const junction = indexed.junction;
      if (junction.shape.length < 3 || !junction.controlled) continue;
      junctionShapes.push(junction.shape);
    }
    if (junctionShapes.length) {
      ctx.beginPath();
      for (const shape of junctionShapes) appendPolygon(ctx, camera, shape);
      ctx.fillStyle = mapTheme.junction;
      ctx.fill();
      if (detail === "street") {
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
    const detail = roadLevelOfDetail(camera.getZoomRatio());
    if (detail === "overview") return;
    ctx.save();
    ctx.lineCap = "butt";
    ctx.strokeStyle = mapTheme.laneMarking;
    ctx.lineWidth = detail === "street" ? 1.1 : .75;
    ctx.setLineDash(detail === "street" ? [9, 9] : [6, 8]);
    ctx.beginPath();
    for (const indexed of world.indexedEdges) {
      if (!geometryIntersectsBounds(indexed, visibleBounds) || indexed.edge.function === "internal") continue;
      const lanes = indexed.edge.laneIds
        .map((id) => world.laneById.get(id))
        .filter((lane): lane is SceneLane => lane !== undefined && !isSpecialLane(lane))
        .sort((left, right) => left.index - right.index);
      for (let index = 1; index < lanes.length; index += 1) {
        const lane = lanes[index];
        appendPolyline(ctx, camera, offsetPolyline(lane.shape, -lane.widthM / 2));
      }
    }
    ctx.stroke();
    ctx.setLineDash([]);

    // SUMO lane endpoints provide truthful stop-line placement; no turn movement is inferred.
    if (detail === "street") {
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

    if (detail === "street") {
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
