import {mapTheme, trafficColor} from "../theme";
import {classifyLaneTraffic} from "../traffic/trafficState";
import type {LayerRenderContext, TrafficMapLayer} from "./LayerTypes";
import {strokePolyline} from "./LayerTypes";

function tailOfPolyline(points: readonly {x: number; y: number}[], lengthM: number) {
  if (points.length < 2 || lengthM <= 0) return [];
  const result = [points.at(-1)!];
  let remaining = lengthM;
  for (let index = points.length - 1; index > 0; index -= 1) {
    const end = points[index];
    const start = points[index - 1];
    const length = Math.hypot(end.x - start.x, end.y - start.y);
    if (length <= remaining) {
      result.unshift(start);
      remaining -= length;
    } else {
      const ratio = remaining / Math.max(.001, length);
      result.unshift({x: end.x + (start.x - end.x) * ratio, y: end.y + (start.y - end.y) * ratio});
      break;
    }
  }
  return result;
}

export class TrafficStateLayer implements TrafficMapLayer {
  readonly id = "trafficState" as const;
  readonly isStatic = false;

  render({ctx, camera, world}: LayerRenderContext): void {
    ctx.save();
    ctx.lineCap = "round";
    for (const [laneId, metric] of world.laneRealtime) {
      const lane = world.laneById.get(laneId);
      if (!lane || lane.shape.length < 2) continue;
      const state = classifyLaneTraffic({
        vehicleCount: metric.vehicle_count,
        queueVehicleCount: metric.queue_vehicle_count,
        queueLengthM: metric.queue_length_m,
        occupancy: metric.occupancy,
        meanSpeedMS: metric.mean_speed_m_s,
        speedLimitMS: lane.speedMS ?? 13.9,
        laneLengthM: lane.lengthM,
      });
      // Unknown and empty lanes retain the neutral road surface. This avoids
      // presenting missing samples as free flow or zero-speed empty lanes as jams.
      if (state.kind === "unknown" || state.kind === "empty") continue;
      ctx.globalAlpha = state.kind === "free" ? .48 : state.kind === "slow" ? .62 : .76;
      ctx.strokeStyle = trafficColor(state.pressure);
      ctx.lineWidth = Math.max(2.4, Math.min(10, lane.widthM * camera.scale + 1.4));
      strokePolyline(ctx, camera, lane.shape);
    }
    ctx.restore();
  }

  destroy(): void {}
}

export class QueueLayer implements TrafficMapLayer {
  readonly id = "queues" as const;
  readonly isStatic = false;

  render({ctx, camera, world}: LayerRenderContext): void {
    ctx.save();
    ctx.lineCap = "round";
    for (const [laneId, metric] of world.laneRealtime) {
      if (metric.queue_length_m <= 1 || (metric.vehicle_count <= 0 && metric.queue_vehicle_count <= 0)) continue;
      const lane = world.laneById.get(laneId);
      if (!lane) continue;
      const queueShape = tailOfPolyline(lane.shape, metric.queue_length_m);
      if (queueShape.length < 2) continue;
      const severe = Math.min(1, metric.queue_length_m / 120);
      ctx.strokeStyle = severe > .7 ? mapTheme.trafficSevere : mapTheme.trafficCongested;
      ctx.globalAlpha = .72;
      ctx.lineWidth = Math.max(4, Math.min(12, lane.widthM * camera.scale + 3));
      strokePolyline(ctx, camera, queueShape);
      if (camera.scale > .46) {
        const labelAt = camera.worldToScreen(queueShape[0]);
        ctx.globalAlpha = 1;
        ctx.fillStyle = "rgba(255, 255, 255, .94)";
        ctx.fillRect(labelAt.x - 3, labelAt.y - 20, 74, 18);
        ctx.fillStyle = mapTheme.text;
        ctx.font = '600 11px "Microsoft YaHei", sans-serif';
        ctx.fillText(`排队 ${metric.queue_length_m.toFixed(0)}m`, labelAt.x + 3, labelAt.y - 7);
      }
    }
    ctx.restore();
  }

  destroy(): void {}
}
