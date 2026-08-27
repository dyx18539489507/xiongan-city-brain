import type {Point2, SceneBounds} from "../../3d/scene/types";

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

function easeInOutCubic(value: number): number {
  return value < 0.5 ? 4 * value ** 3 : 1 - ((-2 * value + 2) ** 3) / 2;
}

export type CameraPose = {centerX: number; centerY: number; scale: number};
type Flight = {from: CameraPose; to: CameraPose; startedAt: number; durationMs: number};
export type MapViewportInsets = {top: number; right: number; bottom: number; left: number};

const DEFAULT_SCENE_PADDING = 36;
const MAX_ZOOM_RATIO = 48;

export class MapCamera {
  width = 1;
  height = 1;
  dpr = 1;
  centerX = 0;
  centerY = 0;
  scale = 1;
  revision = 0;
  private insets: MapViewportInsets = {top: 0, right: 0, bottom: 0, left: 0};
  private sceneBounds: SceneBounds | null = null;
  private fittedScale = 0.1;
  private flight: Flight | null = null;

  resize(width: number, height: number, dpr: number): void {
    const nextWidth = Math.max(1, width);
    const nextHeight = Math.max(1, height);
    const changed = nextWidth !== this.width || nextHeight !== this.height || dpr !== this.dpr;
    if (!changed) return;
    const wasOverview = this.scale <= this.fittedScale * 1.02;
    this.width = nextWidth;
    this.height = nextHeight;
    this.dpr = dpr;
    this.refreshSceneFit(wasOverview);
    this.revision += 1;
  }

  setViewportInsets(insets: MapViewportInsets): void {
    const next = {
      top: Math.max(0, insets.top),
      right: Math.max(0, insets.right),
      bottom: Math.max(0, insets.bottom),
      left: Math.max(0, insets.left),
    };
    if (Object.keys(next).every((key) => next[key as keyof MapViewportInsets] === this.insets[key as keyof MapViewportInsets])) return;
    const wasOverview = this.scale <= this.fittedScale * 1.02;
    this.insets = next;
    this.refreshSceneFit(wasOverview);
    this.revision += 1;
  }

  setSceneBounds(bounds: SceneBounds): void {
    this.sceneBounds = bounds;
    this.fitBounds(bounds, DEFAULT_SCENE_PADDING, false);
  }

  fitBounds(bounds: SceneBounds, padding = 76, animate = true): void {
    const pose = this.fitPose(bounds, padding);
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
    this.moveTo({centerX: point.x, centerY: point.y, scale: clamp(targetScale, this.fittedScale, this.maximumScale)}, true);
  }

  pan(deltaX: number, deltaY: number): void {
    this.flight = null;
    const previousX = this.centerX;
    const previousY = this.centerY;
    this.centerX -= deltaX / this.scale;
    this.centerY += deltaY / this.scale;
    this.constrainCenter();
    if (
      Math.abs(this.centerX - previousX) < .0001
      && Math.abs(this.centerY - previousY) < .0001
    ) return;
    this.revision += 1;
  }

  zoomAt(screenX: number, screenY: number, factor: number): void {
    this.flight = null;
    const previous = this.getPose();
    const before = this.screenToWorld(screenX, screenY);
    this.scale = clamp(this.scale * factor, this.fittedScale * 0.72, this.maximumScale);
    const after = this.screenToWorld(screenX, screenY);
    this.centerX += before.x - after.x;
    this.centerY += before.y - after.y;
    this.constrainCenter();
    if (
      Math.abs(this.centerX - previous.centerX) < .0001
      && Math.abs(this.centerY - previous.centerY) < .0001
      && Math.abs(this.scale - previous.scale) < .000001
    ) return;
    this.revision += 1;
  }

  update(now: number): boolean {
    if (!this.flight) return false;
    const ratio = clamp((now - this.flight.startedAt) / this.flight.durationMs, 0, 1);
    const eased = easeInOutCubic(ratio);
    this.centerX = this.flight.from.centerX + (this.flight.to.centerX - this.flight.from.centerX) * eased;
    this.centerY = this.flight.from.centerY + (this.flight.to.centerY - this.flight.from.centerY) * eased;
    this.scale = this.flight.from.scale + (this.flight.to.scale - this.flight.from.scale) * eased;
    this.constrainCenter();
    this.revision += 1;
    if (ratio >= 1) this.flight = null;
    return true;
  }

  worldToScreen(point: Point2): Point2 {
    return {
      x: (point.x - this.centerX) * this.scale + this.viewportCenterX,
      y: (this.centerY - point.y) * this.scale + this.viewportCenterY,
    };
  }

  screenToWorld(x: number, y: number): Point2 {
    return {
      x: (x - this.viewportCenterX) / this.scale + this.centerX,
      y: this.centerY - (y - this.viewportCenterY) / this.scale,
    };
  }

  viewportBounds(padding = 0): {left: number; top: number; right: number; bottom: number} {
    return {
      left: this.insets.left + padding,
      top: this.insets.top + padding,
      right: this.width - this.insets.right - padding,
      bottom: this.height - this.insets.bottom - padding,
    };
  }

  getZoomRatio(): number {
    return this.scale / Math.max(.0001, this.fittedScale);
  }

  getPose(): CameraPose {
    return {centerX: this.centerX, centerY: this.centerY, scale: this.scale};
  }

  setPose(pose: CameraPose, animate = false): void {
    const next = {
      centerX: pose.centerX,
      centerY: pose.centerY,
      scale: clamp(pose.scale, this.fittedScale * 0.72, this.maximumScale),
    };
    this.constrainPose(next);
    if (!animate
      && Math.abs(next.centerX - this.centerX) < .0001
      && Math.abs(next.centerY - this.centerY) < .0001
      && Math.abs(next.scale - this.scale) < .000001) return;
    this.moveTo(next, animate);
  }

  visibleBounds(marginPx = 60): SceneBounds {
    const topLeft = this.screenToWorld(-marginPx, -marginPx);
    const bottomRight = this.screenToWorld(this.width + marginPx, this.height + marginPx);
    return {minX: topLeft.x, maxX: bottomRight.x, minY: bottomRight.y, maxY: topLeft.y};
  }

  private moveTo(pose: CameraPose, animate: boolean): void {
    const target = {...pose};
    this.constrainPose(target);
    if (!animate || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      this.centerX = target.centerX;
      this.centerY = target.centerY;
      this.scale = target.scale;
      this.flight = null;
      this.revision += 1;
      return;
    }
    this.flight = {
      from: {centerX: this.centerX, centerY: this.centerY, scale: this.scale},
      to: target,
      startedAt: performance.now(),
      durationMs: 620,
    };
  }

  private fitPose(bounds: SceneBounds, padding: number): CameraPose {
    const width = Math.max(1, bounds.maxX - bounds.minX);
    const height = Math.max(1, bounds.maxY - bounds.minY);
    return {
      centerX: (bounds.minX + bounds.maxX) / 2,
      centerY: (bounds.minY + bounds.maxY) / 2,
      scale: Math.max(.0001, Math.min(
        (this.viewportWidth - padding * 2) / width,
        (this.viewportHeight - padding * 2) / height,
      )),
    };
  }

  private refreshSceneFit(useOverview: boolean): void {
    if (!this.sceneBounds) return;
    const overview = this.fitPose(this.sceneBounds, DEFAULT_SCENE_PADDING);
    this.fittedScale = overview.scale;
    if (useOverview) {
      this.centerX = overview.centerX;
      this.centerY = overview.centerY;
      this.scale = overview.scale;
      this.flight = null;
      return;
    }
    this.scale = clamp(this.scale, this.fittedScale * .72, this.maximumScale);
    this.constrainCenter();
  }

  private constrainPose(pose: CameraPose): void {
    if (!this.sceneBounds) return;
    pose.centerX = clamp(pose.centerX, this.sceneBounds.minX, this.sceneBounds.maxX);
    pose.centerY = clamp(pose.centerY, this.sceneBounds.minY, this.sceneBounds.maxY);
  }

  private constrainCenter(): void {
    const pose = {centerX: this.centerX, centerY: this.centerY, scale: this.scale};
    this.constrainPose(pose);
    this.centerX = pose.centerX;
    this.centerY = pose.centerY;
  }

  private get viewportWidth(): number { return Math.max(1, this.width - this.insets.left - this.insets.right); }
  private get viewportHeight(): number { return Math.max(1, this.height - this.insets.top - this.insets.bottom); }
  private get viewportCenterX(): number { return this.insets.left + this.viewportWidth / 2; }
  private get viewportCenterY(): number { return this.insets.top + this.viewportHeight / 2; }
  private get maximumScale(): number { return Math.max(this.fittedScale, Math.min(5, this.fittedScale * MAX_ZOOM_RATIO)); }
}
