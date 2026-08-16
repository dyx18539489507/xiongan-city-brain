import {mapTheme} from "../theme";
import type {TrafficMapLayer, LayerRenderContext} from "./LayerTypes";
import {geometryIntersectsBounds, tracePolygon} from "./LayerTypes";

export class BackgroundLayer implements TrafficMapLayer {
  readonly id = "baseMap" as const;
  readonly isStatic = true;

  render({ctx, camera, world}: LayerRenderContext): void {
    const gradient = ctx.createRadialGradient(camera.width * .52, camera.height * .46, 40, camera.width * .52, camera.height * .46, Math.max(camera.width, camera.height));
    gradient.addColorStop(0, mapTheme.land);
    gradient.addColorStop(1, mapTheme.backgroundDeep);
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, camera.width, camera.height);

    for (const zone of world.scene.zones) {
      if (zone.shape.length < 3) continue;
      tracePolygon(ctx, camera, zone.shape);
      const isWater = /water|river|basin|reservoir/i.test(`${zone.areaType} ${zone.tags.natural ?? ""} ${zone.tags.landuse ?? ""}`);
      ctx.fillStyle = isWater ? mapTheme.water : mapTheme.block;
      ctx.fill();
      ctx.strokeStyle = mapTheme.blockEdge;
      ctx.lineWidth = .8;
      ctx.stroke();
    }
    for (const vegetation of world.scene.vegetation) {
      tracePolygon(ctx, camera, vegetation.shape);
      ctx.fillStyle = mapTheme.vegetation;
      ctx.fill();
    }
  }

  destroy(): void {}
}

export class BuildingLayer implements TrafficMapLayer {
  readonly id = "buildings" as const;
  readonly isStatic = true;

  render({ctx, camera, world, visibleBounds}: LayerRenderContext): void {
    if (camera.scale < .08) return;
    for (const indexed of world.indexedBuildings) {
      if (!geometryIntersectsBounds(indexed, visibleBounds)) continue;
      const building = indexed.building;
      tracePolygon(ctx, camera, building.footprint);
      ctx.fillStyle = mapTheme.building;
      ctx.fill();
      ctx.strokeStyle = mapTheme.buildingEdge;
      ctx.lineWidth = camera.scale > .4 ? 1 : .6;
      ctx.stroke();
    }
  }

  destroy(): void {}
}
