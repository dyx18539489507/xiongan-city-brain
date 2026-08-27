import type {PedestrianEntity, VehicleEntity} from "../../3d/network/digitalTwinTypes";
import type {Point2, SceneBounds} from "../../3d/scene/types";
import type {LayerKey, LayerVisibility, MapSelection} from "../model";
import type {RenderEntity} from "../motion/EntityInterpolator";
import type {TrafficWorldState} from "../world/TrafficWorldState";
import type {MapCamera} from "../camera/MapCamera";

export type RenderEntities = {
  vehicles: readonly RenderEntity<VehicleEntity>[];
  bicycles: readonly RenderEntity<VehicleEntity>[];
  pedestrians: readonly RenderEntity<PedestrianEntity>[];
};

export type LayerRenderContext = {
  ctx: CanvasRenderingContext2D;
  camera: MapCamera;
  world: TrafficWorldState;
  entities: RenderEntities;
  selection: MapSelection | null;
  hover: MapSelection | null;
  now: number;
  visibleBounds: SceneBounds;
  layers: LayerVisibility;
};

export interface TrafficMapLayer {
  readonly id: LayerKey | "selection";
  readonly isStatic: boolean;
  render(context: LayerRenderContext): void;
  destroy(): void;
}

export function isPointVisible(point: Point2, bounds: SceneBounds, margin = 0): boolean {
  return point.x >= bounds.minX - margin && point.x <= bounds.maxX + margin && point.y >= bounds.minY - margin && point.y <= bounds.maxY + margin;
}

export function geometryIntersectsBounds(
  geometry: {minX: number; minY: number; maxX: number; maxY: number},
  bounds: SceneBounds,
): boolean {
  return geometry.maxX >= bounds.minX && geometry.minX <= bounds.maxX
    && geometry.maxY >= bounds.minY && geometry.minY <= bounds.maxY;
}

export function strokePolyline(ctx: CanvasRenderingContext2D, camera: MapCamera, points: readonly Point2[]): void {
  if (points.length < 2) return;
  ctx.beginPath();
  appendPolyline(ctx, camera, points);
  ctx.stroke();
}

export function appendPolyline(ctx: CanvasRenderingContext2D, camera: MapCamera, points: readonly Point2[]): void {
  if (points.length < 2) return;
  const first = camera.worldToScreen(points[0]);
  ctx.moveTo(first.x, first.y);
  for (let index = 1; index < points.length; index += 1) {
    const point = camera.worldToScreen(points[index]);
    ctx.lineTo(point.x, point.y);
  }
}

export function tracePolygon(ctx: CanvasRenderingContext2D, camera: MapCamera, points: readonly Point2[]): void {
  if (points.length < 3) return;
  ctx.beginPath();
  appendPolygon(ctx, camera, points);
}

export function appendPolygon(ctx: CanvasRenderingContext2D, camera: MapCamera, points: readonly Point2[]): void {
  if (points.length < 3) return;
  const first = camera.worldToScreen(points[0]);
  ctx.moveTo(first.x, first.y);
  for (let index = 1; index < points.length; index += 1) {
    const point = camera.worldToScreen(points[index]);
    ctx.lineTo(point.x, point.y);
  }
  ctx.closePath();
}
