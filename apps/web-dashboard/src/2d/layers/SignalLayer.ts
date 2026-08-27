import type {TrafficLightEntity} from "../../3d/network/digitalTwinTypes";
import {mapTheme} from "../theme";
import type {LayerRenderContext, TrafficMapLayer} from "./LayerTypes";

function dominantSignal(light: TrafficLightEntity | undefined): "red" | "yellow" | "green" | "off" {
  if (!light) return "off";
  if (/[Gg]/.test(light.state)) return "green";
  if (/[Yy]/.test(light.state)) return "yellow";
  if (/[Rr]/.test(light.state)) return "red";
  return "off";
}

const signalColor = {
  red: mapTheme.signalRed,
  yellow: mapTheme.signalYellow,
  green: mapTheme.signalGreen,
  off: mapTheme.textMuted,
} as const;

export class SignalLayer implements TrafficMapLayer {
  readonly id = "signals" as const;
  readonly isStatic = false;

  render({ctx, camera, world}: LayerRenderContext): void {
    const zoomRatio = camera.getZoomRatio();
    for (const junction of world.controlledJunctions) {
      const definition = world.trafficLightByJunctionId.get(junction.sumoJunctionId);
      const light = world.digitalTwin.trafficLights.get(definition?.sumoTlsId ?? junction.sumoJunctionId)
        ?? world.digitalTwin.trafficLights.get(junction.sumoJunctionId);
      const state = dominantSignal(light);
      const point = camera.worldToScreen(junction.position);
      if (zoomRatio < 1.2) {
        ctx.fillStyle = signalColor[state];
        ctx.beginPath(); ctx.arc(point.x - 5, point.y + 5, 2.8, 0, Math.PI * 2); ctx.fill();
        continue;
      }
      ctx.save();
      ctx.translate(point.x - 13, point.y + 7);
      ctx.fillStyle = "rgba(255, 255, 255, .94)";
      ctx.beginPath(); ctx.roundRect(-3, -5, 25, 11, 4); ctx.fill();
      const states = ["red", "yellow", "green"] as const;
      states.forEach((lamp, index) => {
        ctx.fillStyle = lamp === state ? signalColor[lamp] : "rgba(116, 135, 141, .28)";
        if (lamp === state) { ctx.shadowColor = signalColor[lamp]; ctx.shadowBlur = 5; }
        ctx.beginPath(); ctx.arc(2 + index * 8, .5, 2.4, 0, Math.PI * 2); ctx.fill();
        ctx.shadowBlur = 0;
      });
      ctx.restore();
      if (light && zoomRatio > 2) {
        ctx.fillStyle = mapTheme.textSecondary;
        ctx.font = '500 11px "Microsoft YaHei", sans-serif';
        ctx.fillText(`${light.remainingS.toFixed(0)}s`, point.x + 14, point.y + 12);
      }
    }
  }

  destroy(): void {}
}
