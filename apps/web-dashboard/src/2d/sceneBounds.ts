import type {Point2, SceneBounds, StaticSceneDocument} from "../3d/scene/types";

function collectPoints(scene: StaticSceneDocument): Point2[] {
  return [
    ...scene.junctions.flatMap((item) => item.shape.length ? item.shape : [item.position]),
    ...scene.edges.flatMap((item) => item.shape ?? []),
    ...scene.lanes.flatMap((item) => item.shape),
    ...scene.crossings.flatMap((item) => item.shape),
  ].filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y));
}

export function sceneGeometryBounds(scene: StaticSceneDocument): SceneBounds {
  const points = collectPoints(scene);
  if (!points.length) return scene.coordinateSystem.sceneBounds;
  const minX = Math.min(...points.map((point) => point.x));
  const minY = Math.min(...points.map((point) => point.y));
  const maxX = Math.max(...points.map((point) => point.x));
  const maxY = Math.max(...points.map((point) => point.y));
  const span = Math.max(maxX - minX, maxY - minY, 1);
  const padding = Math.min(80, Math.max(12, span * .08));
  return {minX: minX - padding, minY: minY - padding, maxX: maxX + padding, maxY: maxY + padding};
}
