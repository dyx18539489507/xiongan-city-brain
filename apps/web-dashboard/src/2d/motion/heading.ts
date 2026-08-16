/**
 * SUMO reports headings clockwise with 0° pointing north. Canvas vehicle
 * sprites are authored along +X and Canvas rotation is clockwise because the
 * screen Y axis points down. Moving the north origin to +X therefore requires
 * subtracting 90°, not reversing the SUMO angle.
 */
export function sumoAngleToCanvasRadians(angleDegrees: number): number {
  const finiteAngle = Number.isFinite(angleDegrees) ? angleDegrees : 0;
  const normalized = ((finiteAngle % 360) + 360) % 360;
  return ((normalized - 90) * Math.PI) / 180;
}
