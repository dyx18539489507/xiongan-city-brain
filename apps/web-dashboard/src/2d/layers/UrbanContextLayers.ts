import type {Point2} from "../../3d/scene/types";
import {mapTheme} from "../theme";
import type {TrafficMapLayer, LayerRenderContext} from "./LayerTypes";
import {appendPolygon, geometryIntersectsBounds} from "./LayerTypes";

export class BackgroundLayer implements TrafficMapLayer {
  readonly id = "baseMap" as const;
  readonly isStatic = true;

  render({ctx, camera, world}: LayerRenderContext): void {
    const gradient = ctx.createRadialGradient(camera.width * .52, camera.height * .46, 40, camera.width * .52, camera.height * .46, Math.max(camera.width, camera.height));
    gradient.addColorStop(0, mapTheme.land);
    gradient.addColorStop(1, mapTheme.backgroundDeep);
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, camera.width, camera.height);

    const waterShapes: Array<readonly Point2[]> = [];
    const blockShapes: Array<readonly Point2[]> = [];
    for (const zone of world.scene.zones) {
      if (zone.shape.length < 3) continue;
      const isWater = /water|river|basin|reservoir/i.test(`${zone.areaType} ${zone.tags.natural ?? ""} ${zone.tags.landuse ?? ""}`);
      (isWater ? waterShapes : blockShapes).push(zone.shape);
    }
    for (const [shapes, color] of [[blockShapes, mapTheme.block], [waterShapes, mapTheme.water]] as const) {
      if (!shapes.length) continue;
      ctx.beginPath();
      for (const shape of shapes) appendPolygon(ctx, camera, shape);
      ctx.fillStyle = color;
      ctx.fill();
      ctx.strokeStyle = mapTheme.blockEdge;
      ctx.lineWidth = .8;
      ctx.stroke();
    }
    ctx.beginPath();
    for (const vegetation of world.scene.vegetation) {
      appendPolygon(ctx, camera, vegetation.shape);
    }
    ctx.fillStyle = mapTheme.vegetation;
    ctx.fill();
  }

  destroy(): void {}
}

export class BuildingLayer implements TrafficMapLayer {
  readonly id = "buildings" as const;
  readonly isStatic = true;

  render({ctx, camera, world, visibleBounds}: LayerRenderContext): void {
    if (camera.scale < .08) return;
    ctx.beginPath();
    let visible = 0;
    for (const indexed of world.buildingSpatialIndex.query(visibleBounds)) {
      if (!geometryIntersectsBounds(indexed, visibleBounds)) continue;
      const building = indexed.building;
      appendPolygon(ctx, camera, building.footprint);
      visible += 1;
    }
    if (!visible) return;
    ctx.fillStyle = mapTheme.building;
    ctx.fill();
    ctx.strokeStyle = mapTheme.buildingEdge;
    ctx.lineWidth = camera.scale > .4 ? 1 : .6;
    ctx.stroke();
  }

  destroy(): void {}
}
