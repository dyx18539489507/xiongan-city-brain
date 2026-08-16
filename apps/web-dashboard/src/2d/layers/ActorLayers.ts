import type {PedestrianEntity, VehicleEntity} from "../../3d/network/digitalTwinTypes";
import type {Point2} from "../../3d/scene/types";
import type {RenderEntity} from "../motion/EntityInterpolator";
import {sumoAngleToCanvasRadians} from "../motion/heading";
import {mapTheme} from "../theme";
import type {LayerRenderContext, TrafficMapLayer} from "./LayerTypes";
import {strokePolyline} from "./LayerTypes";

function visibleCoordinate(x: number, y: number, bounds: LayerRenderContext["visibleBounds"], margin: number): boolean {
  return x >= bounds.minX - margin && x <= bounds.maxX + margin
    && y >= bounds.minY - margin && y <= bounds.maxY + margin;
}

type StrokeBatch = {path: Path2D; color: string; alpha: number; width: number};

function strokeBatches(ctx: CanvasRenderingContext2D, batches: ReadonlyMap<string, StrokeBatch>): void {
  ctx.save();
  ctx.lineCap = "round";
  for (const batch of batches.values()) {
    ctx.strokeStyle = batch.color;
    ctx.globalAlpha = batch.alpha;
    ctx.lineWidth = batch.width;
    ctx.stroke(batch.path);
  }
  ctx.restore();
}

function strokeBatch(
  batches: Map<string, StrokeBatch>,
  color: string,
  alpha: number,
  width: number,
): Path2D {
  const key = `${color}|${alpha}|${width}`;
  let batch = batches.get(key);
  if (!batch) {
    batch = {path: new Path2D(), color, alpha, width};
    batches.set(key, batch);
  }
  return batch.path;
}

function vehicleKind(entity: VehicleEntity): "bus" | "truck" | "emergency" | "car" {
  const value = `${entity.vehicleClass} ${entity.type}`.toLowerCase();
  if (/emergency|ambulance|police|fire/.test(value)) return "emergency";
  if (/bus|coach/.test(value)) return "bus";
  if (/truck|delivery|lorry|trailer/.test(value)) return "truck";
  return "car";
}

function colorForVehicle(entity: VehicleEntity, kind: ReturnType<typeof vehicleKind>): string {
  if (kind === "bus") return mapTheme.bus;
  if (kind === "truck") return mapTheme.truck;
  if (kind === "emergency") return mapTheme.selection;
  if (entity.status === "waiting") return mapTheme.trafficCongested;
  return mapTheme.car;
}

export class VehicleLayer implements TrafficMapLayer {
  readonly id = "vehicles" as const;
  readonly isStatic = false;

  render({ctx, camera, world, entities, visibleBounds, selection, hover, layers}: LayerRenderContext): void {
    if (camera.scale < .16) {
      const batches = new Map<string, StrokeBatch>();
      for (const entity of entities.vehicles) {
        const kind = vehicleKind(entity);
        if ((kind === "bus" && !layers.buses) || (kind === "truck" && !layers.trucks)) continue;
        if (!visibleCoordinate(entity.renderX, entity.renderY, visibleBounds, 20)) continue;
        const screenX = (entity.renderX - camera.centerX) * camera.scale + camera.width / 2;
        const screenY = (camera.centerY - entity.renderY) * camera.scale + camera.height / 2;
        const yaw = sumoAngleToCanvasRadians(entity.renderAngle);
        const selected = selection?.id === entity.id || hover?.id === entity.id;
        const halfLength = selected ? 3 : 2.2;
        const dx = Math.cos(yaw) * halfLength;
        const dy = Math.sin(yaw) * halfLength;
        const path = strokeBatch(
          batches,
          selected ? mapTheme.selection : colorForVehicle(entity, kind),
          entity.status === "waiting" || selected ? 1 : .78,
          selected ? 3 : 1.8,
        );
        path.moveTo(screenX - dx, screenY - dy);
        path.lineTo(screenX + dx, screenY + dy);
      }
      strokeBatches(ctx, batches);
      return;
    }
    for (const entity of entities.vehicles) {
      const kind = vehicleKind(entity);
      if ((kind === "bus" && !layers.buses) || (kind === "truck" && !layers.trucks)) continue;
      if (!visibleCoordinate(entity.renderX, entity.renderY, visibleBounds, 20)) continue;
      const screenX = (entity.renderX - camera.centerX) * camera.scale + camera.width / 2;
      const screenY = (camera.centerY - entity.renderY) * camera.scale + camera.height / 2;
      const selected = selection?.id === entity.id || hover?.id === entity.id;
      const yaw = sumoAngleToCanvasRadians(entity.renderAngle);
      ctx.save();
      ctx.translate(screenX, screenY);
      ctx.rotate(yaw);
      const color = colorForVehicle(entity, kind);
      const baseLength = kind === "bus" ? 13 : kind === "truck" ? 11 : 8;
      const length = Math.max(5, Math.min(17, baseLength * Math.max(.72, camera.scale * .82)));
      const laneWidthPx = (world.laneById.get(entity.laneId)?.widthM ?? 3.2) * camera.scale;
      const nominalWidth = (kind === "car" ? 3.5 : 4.2) * Math.max(.8, camera.scale * .8);
      const width = Math.max(2.6, Math.min(6.2, nominalWidth, Math.max(2.6, laneWidthPx * .74)));
      ctx.shadowColor = selected ? mapTheme.selection : mapTheme.shadow;
      ctx.shadowBlur = selected ? 9 : 2;
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.roundRect(-length / 2, -width / 2, length, width, Math.min(2, width / 2));
      ctx.fill();
      ctx.shadowBlur = 0;
      if (camera.scale > .45) {
        ctx.fillStyle = "rgba(10, 25, 29, .74)";
        ctx.fillRect(length * .08, -width * .36, length * .22, width * .72);
        ctx.fillStyle = entity.brake ? mapTheme.signalRed : "rgba(238, 245, 242, .65)";
        ctx.fillRect(-length / 2, -width * .31, 1.1, width * .62);
        ctx.fillStyle = "rgba(238, 245, 242, .82)";
        ctx.beginPath();
        ctx.moveTo(length / 2 + 1.6, 0); ctx.lineTo(length / 2 - 1.2, -1.8); ctx.lineTo(length / 2 - 1.2, 1.8); ctx.closePath(); ctx.fill();
      }
      if (selected) {
        ctx.strokeStyle = mapTheme.selection;
        ctx.lineWidth = 1.2;
        ctx.strokeRect(-length / 2 - 2, -width / 2 - 2, length + 4, width + 4);
      }
      ctx.restore();
    }
  }

  destroy(): void {}
}

export class BicycleLayer implements TrafficMapLayer {
  readonly id = "bicycles" as const;
  readonly isStatic = false;

  render({ctx, camera, entities, visibleBounds, selection, hover}: LayerRenderContext): void {
    if (camera.scale < .4) {
      const batches = new Map<string, StrokeBatch>();
      for (const entity of entities.bicycles) {
        if (!visibleCoordinate(entity.renderX, entity.renderY, visibleBounds, 16)) continue;
        const screenX = (entity.renderX - camera.centerX) * camera.scale + camera.width / 2;
        const screenY = (camera.centerY - entity.renderY) * camera.scale + camera.height / 2;
        const yaw = sumoAngleToCanvasRadians(entity.renderAngle);
        const selected = selection?.id === entity.id || hover?.id === entity.id;
        const halfLength = selected ? 3.4 : 2.5;
        const dx = Math.cos(yaw) * halfLength;
        const dy = Math.sin(yaw) * halfLength;
        const path = strokeBatch(batches, selected ? mapTheme.selection : mapTheme.bicycle, 1, selected ? 2.2 : 2);
        path.moveTo(screenX - dx, screenY - dy);
        path.lineTo(screenX + dx, screenY + dy);
      }
      strokeBatches(ctx, batches);
      return;
    }
    for (const entity of entities.bicycles) {
      if (!visibleCoordinate(entity.renderX, entity.renderY, visibleBounds, 16)) continue;
      const screenX = (entity.renderX - camera.centerX) * camera.scale + camera.width / 2;
      const screenY = (camera.centerY - entity.renderY) * camera.scale + camera.height / 2;
      const selected = selection?.id === entity.id || hover?.id === entity.id;
      const yaw = sumoAngleToCanvasRadians(entity.renderAngle);
      ctx.save(); ctx.translate(screenX, screenY); ctx.rotate(yaw);
      const size = selected ? 5 : 3.8;
      ctx.strokeStyle = selected ? mapTheme.selection : mapTheme.bicycle;
      ctx.lineWidth = 1.1;
      ctx.beginPath();
      ctx.arc(-size * .65, 0, size * .5, 0, Math.PI * 2);
      ctx.moveTo(size * 1.15, 0); ctx.arc(size * .65, 0, size * .5, 0, Math.PI * 2);
      ctx.moveTo(-size * .65, 0); ctx.lineTo(0, -size * .48); ctx.lineTo(size * .65, 0); ctx.stroke();
      ctx.restore();
    }
  }

  destroy(): void {}
}

export class PedestrianLayer implements TrafficMapLayer {
  readonly id = "pedestrians" as const;
  readonly isStatic = false;

  render({ctx, camera, entities, visibleBounds, selection, hover}: LayerRenderContext): void {
    if (camera.scale < .55) {
      const moving = new Path2D();
      const waiting = new Path2D();
      const selectedPath = new Path2D();
      for (const entity of entities.pedestrians) {
        if (!visibleCoordinate(entity.renderX, entity.renderY, visibleBounds, 12)) continue;
        const screenX = (entity.renderX - camera.centerX) * camera.scale + camera.width / 2;
        const screenY = (camera.centerY - entity.renderY) * camera.scale + camera.height / 2;
        const selected = selection?.id === entity.id || hover?.id === entity.id;
        const path = selected ? selectedPath : entity.status === "waiting" ? waiting : moving;
        path.moveTo(screenX + (selected ? 2.8 : 1.6), screenY);
        path.arc(screenX, screenY, selected ? 2.8 : 1.6, 0, Math.PI * 2);
      }
      ctx.fillStyle = mapTheme.pedestrian; ctx.fill(moving);
      ctx.fillStyle = mapTheme.warning; ctx.fill(waiting);
      ctx.fillStyle = mapTheme.selection; ctx.fill(selectedPath);
      return;
    }
    for (const entity of entities.pedestrians) {
      if (!visibleCoordinate(entity.renderX, entity.renderY, visibleBounds, 12)) continue;
      const screenX = (entity.renderX - camera.centerX) * camera.scale + camera.width / 2;
      const screenY = (camera.centerY - entity.renderY) * camera.scale + camera.height / 2;
      const selected = selection?.id === entity.id || hover?.id === entity.id;
      ctx.save(); ctx.translate(screenX, screenY);
      ctx.fillStyle = entity.status === "waiting" ? mapTheme.warning : mapTheme.pedestrian;
      ctx.beginPath(); ctx.arc(0, -2.6, selected ? 2.2 : 1.7, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = ctx.fillStyle;
      ctx.lineWidth = 1.1;
      ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(0, 4.4); ctx.moveTo(0, 1.2); ctx.lineTo(-2.2, 3.5); ctx.moveTo(0, 1.2); ctx.lineTo(2.2, 3.5); ctx.stroke();
      ctx.restore();
    }
  }

  destroy(): void {}
}

export class TrailLayer implements TrafficMapLayer {
  readonly id = "trails" as const;
  readonly isStatic = false;

  constructor(private readonly vehicleTrail: (id: string) => readonly Point2[], private readonly bicycleTrail: (id: string) => readonly Point2[]) {}

  render({ctx, camera, entities}: LayerRenderContext): void {
    ctx.save();
    ctx.lineWidth = 1;
    ctx.globalAlpha = .24;
    for (const entity of entities.vehicles) {
      ctx.strokeStyle = mapTheme.car;
      strokePolyline(ctx, camera, this.vehicleTrail(entity.id));
    }
    for (const entity of entities.bicycles) {
      ctx.strokeStyle = mapTheme.bicycle;
      strokePolyline(ctx, camera, this.bicycleTrail(entity.id));
    }
    ctx.restore();
  }

  destroy(): void {}
}

export type AnyRenderEntity = RenderEntity<VehicleEntity> | RenderEntity<PedestrianEntity>;
