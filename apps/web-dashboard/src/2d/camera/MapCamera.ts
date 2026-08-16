import type {Point2, SceneBounds} from "../../3d/scene/types";

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

function easeInOutCubic(value: number): number {
  return value < 0.5 ? 4 * value ** 3 : 1 - ((-2 * value + 2) ** 3) / 2;
}

type CameraPose = {centerX: number; centerY: number; scale: number};
type Flight = {from: CameraPose; to: CameraPose; startedAt: number; durationMs: number};

export class MapCamera {
  width = 1;
  height = 1;
  dpr = 1;
  centerX = 0;
  centerY = 0;
  scale = 1;
  revision = 0;
  private sceneBounds: SceneBounds | null = null;
  private fittedScale = 0.1;
  private flight: Flight | null = null;

  resize(width: number, height: number, dpr: number): void {
    const changed = width !== this.width || height !== this.height || dpr !== this.dpr;
    this.width = Math.max(1, width);
    this.height = Math.max(1, height);
    this.dpr = dpr;
    if (changed && this.sceneBounds) this.fitBounds(this.sceneBounds, 76, false);
  }

  setSceneBounds(bounds: SceneBounds): void {
    this.sceneBounds = bounds;
    this.fitBounds(bounds, 158, false);
  }

  fitBounds(bounds: SceneBounds, padding = 76, animate = true): void {
    const width = Math.max(1, bounds.maxX - bounds.minX);
    const height = Math.max(1, bounds.maxY - bounds.minY);
    const pose = {
      centerX: (bounds.minX + bounds.maxX) / 2,
      centerY: (bounds.minY + bounds.maxY) / 2,
      scale: Math.min((this.width - padding * 2) / width, (this.height - padding * 2) / height),
    };
    if (bounds === this.sceneBounds || !this.sceneBounds) this.fittedScale = pose.scale;
    this.moveTo(pose, animate);
  }

  fitPoints(points: readonly Point2[], padding = 160, animate = true): void {
    if (!points.length) return;
    this.fitBounds({
      minX: Math.min(...points.map((point) => point.x)),
      minY: Math.min(...points.map((point) => point.y)),
      maxX: Math.max(...points.map((point) => point.x)),
      maxY: Math.max(...points.map((point) => point.y)),
    }, padding, animate);
  }

  focusPoint(point: Point2, targetScale = 1.25): void {
    this.moveTo({centerX: point.x, centerY: point.y, scale: clamp(targetScale, this.fittedScale, 5)}, true);
  }

  pan(deltaX: number, deltaY: number): void {
    this.flight = null;
    this.centerX -= deltaX / this.scale;
    this.centerY += deltaY / this.scale;
    this.revision += 1;
  }

  zoomAt(screenX: number, screenY: number, factor: number): void {
    this.flight = null;
    const before = this.screenToWorld(screenX, screenY);
    this.scale = clamp(this.scale * factor, this.fittedScale * 0.72, 5);
    const after = this.screenToWorld(screenX, screenY);
    this.centerX += before.x - after.x;
    this.centerY += before.y - after.y;
    this.revision += 1;
  }

  update(now: number): boolean {
    if (!this.flight) return false;
    const ratio = clamp((now - this.flight.startedAt) / this.flight.durationMs, 0, 1);
    const eased = easeInOutCubic(ratio);
    this.centerX = this.flight.from.centerX + (this.flight.to.centerX - this.flight.from.centerX) * eased;
    this.centerY = this.flight.from.centerY + (this.flight.to.centerY - this.flight.from.centerY) * eased;
    this.scale = this.flight.from.scale + (this.flight.to.scale - this.flight.from.scale) * eased;
    this.revision += 1;
    if (ratio >= 1) this.flight = null;
    return true;
  }

  worldToScreen(point: Point2): Point2 {
    return {
      x: (point.x - this.centerX) * this.scale + this.width / 2,
      y: (this.centerY - point.y) * this.scale + this.height / 2,
    };
  }

  screenToWorld(x: number, y: number): Point2 {
    return {
      x: (x - this.width / 2) / this.scale + this.centerX,
      y: this.centerY - (y - this.height / 2) / this.scale,
    };
  }

  visibleBounds(marginPx = 60): SceneBounds {
    const topLeft = this.screenToWorld(-marginPx, -marginPx);
    const bottomRight = this.screenToWorld(this.width + marginPx, this.height + marginPx);
    return {minX: topLeft.x, maxX: bottomRight.x, minY: bottomRight.y, maxY: topLeft.y};
  }

  private moveTo(pose: CameraPose, animate: boolean): void {
    if (!animate || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      this.centerX = pose.centerX;
      this.centerY = pose.centerY;
      this.scale = pose.scale;
      this.flight = null;
      this.revision += 1;
      return;
    }
    this.flight = {
      from: {centerX: this.centerX, centerY: this.centerY, scale: this.scale},
      to: pose,
      startedAt: performance.now(),
      durationMs: 620,
    };
  }
}
