import type {RealtimeEvent} from "../../3d/network/digitalTwinTypes";
import {mapTheme, trafficColor} from "../theme";
import type {LayerRenderContext, TrafficMapLayer} from "./LayerTypes";
import {strokePolyline} from "./LayerTypes";

export type MapEventMarker = {id: string; x: number; y: number; event: RealtimeEvent};

function payloadString(event: RealtimeEvent, ...keys: string[]): string | null {
  for (const key of keys) {
    const value = event.payload[key];
    if (typeof value === "string" && value) return value;
  }
  return null;
}

export function resolveEventMarkers(context: LayerRenderContext): MapEventMarker[] {
  const {world, entities} = context;
  if (!world.digitalTwin.events.length) return [];
  const markers: MapEventMarker[] = [];
  const events = world.digitalTwin.events;
  for (let index = Math.max(0, events.length - 32); index < events.length; index += 1) {
    const event = events[index];
    const laneId = payloadString(event, "lane_id", "actual_lane_id", "target_lane_id");
    const lane = laneId ? world.laneById.get(laneId) : null;
    if (lane?.shape.length) {
      const point = lane.shape[Math.floor(lane.shape.length / 2)];
      markers.push({id: event.eventId, x: point.x, y: point.y, event});
      continue;
    }
    const junctionId = payloadString(event, "intersection_id", "junction_id", "target_intersection_id");
    const junction = junctionId ? world.junctionById.get(junctionId) : null;
    if (junction) {
      markers.push({id: event.eventId, ...junction.position, event});
      continue;
    }
    // SUMO incident events use the affected vehicle as ``detail``; using that
    // identifier keeps the marker attached to the real TraCI entity.
    const vehicleId = payloadString(event, "vehicle_id", "target_vehicle_id")
      ?? (/INCIDENT/i.test(event.event) ? event.detail : null);
    if (!vehicleId) continue;
    const vehicle = entities.vehicles.find((item) => item.id === vehicleId)
      ?? entities.bicycles.find((item) => item.id === vehicleId);
    if (vehicle) markers.push({id: event.eventId, x: vehicle.renderX, y: vehicle.renderY, event});
  }
  return markers;
}

export class AlgorithmLayer implements TrafficMapLayer {
  readonly id = "algorithm" as const;
  readonly isStatic = false;

  render({ctx, camera, world, now}: LayerRenderContext): void {
    const coordinated = world.snapshot.fallback_mode === "CLOUD_COORDINATED";
    let hasControlled = false;
    for (const item of world.intersectionRealtime.values()) {
      const mode = item.control_mode?.toLowerCase() ?? "";
      if (mode && !/fixed|none|idle|unknown/.test(mode)) { hasControlled = true; break; }
    }
    if (!coordinated && !hasControlled) return;
    ctx.save();
    const pulse = .5 + .5 * Math.sin(now / 700);
    ctx.strokeStyle = mapTheme.algorithm;
    ctx.fillStyle = mapTheme.algorithm;
    ctx.globalAlpha = .28 + pulse * .18;
    ctx.setLineDash([9, 12]);
    ctx.lineDashOffset = -(now / 48) % 21;
    ctx.lineWidth = 2.2;
    if (coordinated) {
      for (const edgeId of world.corridorEdgeIds) {
        const edge = world.edgeById.get(edgeId);
        if (edge?.shape) strokePolyline(ctx, camera, edge.shape);
      }
    }
    ctx.setLineDash([]);
    for (const metric of world.intersectionRealtime.values()) {
      const mode = metric.control_mode?.toLowerCase() ?? "";
      if (!mode || /fixed|none|idle|unknown/.test(mode)) continue;
      const junction = world.junctionById.get(metric.intersection_id);
      if (!junction) continue;
      const point = camera.worldToScreen(junction.position);
      ctx.beginPath(); ctx.arc(point.x, point.y, 8 + pulse * 3, 0, Math.PI * 2); ctx.stroke();
      if (camera.scale > .56) {
        ctx.globalAlpha = .9;
        ctx.font = '600 10px "Microsoft YaHei", sans-serif';
        ctx.fillText("协同控制", point.x + 12, point.y - 10);
      }
    }
    ctx.restore();
  }

  destroy(): void {}
}

export class EventLayer implements TrafficMapLayer {
  readonly id = "events" as const;
  readonly isStatic = false;

  render(context: LayerRenderContext): void {
    const {ctx, camera, now} = context;
    for (const marker of resolveEventMarkers(context)) {
      const point = camera.worldToScreen(marker);
      const danger = /INCIDENT|FAULT|OFFLINE|LOSS|COLLISION/i.test(marker.event.event);
      const color = danger ? mapTheme.danger : mapTheme.warning;
      const pulse = 1 + Math.sin(now / 260) * .08;
      ctx.save(); ctx.translate(point.x, point.y); ctx.scale(pulse, pulse);
      ctx.fillStyle = "rgba(6, 11, 13, .92)";
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(0, -11); ctx.lineTo(10, 8); ctx.lineTo(-10, 8); ctx.closePath(); ctx.fill(); ctx.stroke();
      ctx.fillStyle = color;
      ctx.font = '700 12px "Microsoft YaHei", sans-serif'; ctx.textAlign = "center"; ctx.fillText("!", 0, 5);
      ctx.restore();
    }
  }

  destroy(): void {}
}

export class RoadsideDeviceLayer implements TrafficMapLayer {
  readonly id = "rsu" as const;
  readonly isStatic = false;

  render({ctx, camera, world}: LayerRenderContext): void {
    if (camera.scale < .55) return;
    for (const device of world.scene.roadsideDevices) {
      const point = camera.worldToScreen(device.position);
      const online = /online|active|normal/i.test(`${device.status} ${device.communicationStatus}`);
      ctx.save(); ctx.translate(point.x, point.y);
      ctx.strokeStyle = online ? mapTheme.edge : mapTheme.danger;
      ctx.lineWidth = 1.4;
      ctx.beginPath(); ctx.moveTo(0, 7); ctx.lineTo(0, -5); ctx.moveTo(-4, 7); ctx.lineTo(4, 7); ctx.stroke();
      ctx.beginPath(); ctx.arc(0, -6, 2, 0, Math.PI * 2); ctx.fillStyle = ctx.strokeStyle; ctx.fill();
      ctx.font = '600 10px "Microsoft YaHei", sans-serif'; ctx.fillText("RSU", 7, 1);
      ctx.restore();
    }
  }

  destroy(): void {}
}

export class LabelLayer implements TrafficMapLayer {
  readonly id = "labels" as const;
  readonly isStatic = false;

  render({ctx, camera, world, selection, hover}: LayerRenderContext): void {
    ctx.save();
    ctx.textBaseline = "middle";
    for (const junction of world.controlledJunctions) {
      const point = camera.worldToScreen(junction.position);
      const selected = selection?.kind === "junction" && selection.id === junction.sumoJunctionId;
      const hovered = hover?.kind === "junction" && hover.id === junction.sumoJunctionId;
      const metric = world.intersectionRealtime.get(junction.sumoJunctionId);
      const severity = Math.max(metric?.congestion_level ?? 0, metric?.spillback_risk ?? 0);
      ctx.fillStyle = selected || hovered ? mapTheme.selection : severity > .6 ? trafficColor(severity) : mapTheme.textSecondary;
      ctx.font = `${selected ? 700 : 600} ${camera.scale > .5 ? 13 : 11}px "Microsoft YaHei", sans-serif`;
      ctx.fillText(junction.displayId ?? junction.sumoJunctionId, point.x + 7, point.y - 8);
    }
    ctx.restore();
  }

  destroy(): void {}
}

export class SelectionLayer implements TrafficMapLayer {
  readonly id = "selection" as const;
  readonly isStatic = false;

  render({ctx, camera, world, entities, selection, hover, now}: LayerRenderContext): void {
    const target = hover ?? selection;
    if (!target) return;
    ctx.save();
    ctx.strokeStyle = mapTheme.selection;
    ctx.lineWidth = 1.5;
    ctx.setLineDash([5, 5]);
    ctx.lineDashOffset = -(now / 80) % 10;
    if (target.kind === "junction") {
      const junction = world.junctionById.get(target.id);
      if (junction) {
        const point = camera.worldToScreen(junction.position);
        ctx.beginPath(); ctx.arc(point.x, point.y, 15, 0, Math.PI * 2); ctx.stroke();
      }
    } else if (target.kind === "edge") {
      const edge = world.edgeById.get(target.id);
      if (edge?.shape) { ctx.setLineDash([]); ctx.lineWidth = 3; strokePolyline(ctx, camera, edge.shape); }
    } else {
      const entity = [...entities.vehicles, ...entities.bicycles, ...entities.pedestrians].find((item) => item.id === target.id);
      if (entity) {
        const point = camera.worldToScreen({x: entity.renderX, y: entity.renderY});
        ctx.beginPath(); ctx.arc(point.x, point.y, 12, 0, Math.PI * 2); ctx.stroke();
      }
    }
    ctx.restore();
  }

  destroy(): void {}
}
