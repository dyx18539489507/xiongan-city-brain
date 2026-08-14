import type * as THREE from "three";

export type PerformanceSnapshot = {
  averageFps: number;
  p1Fps: number;
  averageFrameTimeMs: number;
  maxFrameTimeMs: number;
  drawCalls: number;
  triangles: number;
  geometries: number;
  textures: number;
  sampleCount: number;
};

const EMPTY_SNAPSHOT: PerformanceSnapshot = {
  averageFps: 0,
  p1Fps: 0,
  averageFrameTimeMs: 0,
  maxFrameTimeMs: 0,
  drawCalls: 0,
  triangles: 0,
  geometries: 0,
  textures: 0,
  sampleCount: 0,
};

function round(value: number, digits = 1): number {
  const scale = 10 ** digits;
  return Math.round(value * scale) / scale;
}

/**
 * Measures frames that were actually submitted to WebGL rather than raw rAF
 * callbacks. The bounded window avoids unbounded history growth during long
 * simulations and deliberately includes slow frames in the P1 result.
 */
export class PerformanceMonitor {
  private readonly intervalsMs: number[] = [];
  private lastRenderTimeMs: number | null = null;
  private lastSnapshotTimeMs = 0;

  constructor(
    private readonly maximumSamples = 240,
    private readonly publishIntervalMs = 1000,
  ) {}

  record(
    renderTimeMs: number,
    rendererInfo: THREE.WebGLInfo,
  ): PerformanceSnapshot | null {
    if (this.lastRenderTimeMs !== null) {
      const interval = renderTimeMs - this.lastRenderTimeMs;
      if (interval > 0 && interval < 1000) {
        this.intervalsMs.push(interval);
        if (this.intervalsMs.length > this.maximumSamples) {
          this.intervalsMs.splice(0, this.intervalsMs.length - this.maximumSamples);
        }
      }
    }
    this.lastRenderTimeMs = renderTimeMs;

    if (
      this.intervalsMs.length < 2 ||
      renderTimeMs - this.lastSnapshotTimeMs < this.publishIntervalMs
    ) {
      return null;
    }
    this.lastSnapshotTimeMs = renderTimeMs;

    const sorted = [...this.intervalsMs].sort((a, b) => a - b);
    const total = this.intervalsMs.reduce((sum, value) => sum + value, 0);
    const averageFrameTimeMs = total / this.intervalsMs.length;
    const p99Index = Math.min(
      sorted.length - 1,
      Math.max(0, Math.ceil(sorted.length * 0.99) - 1),
    );
    const p99FrameTimeMs = sorted[p99Index] ?? averageFrameTimeMs;

    return {
      averageFps: round(1000 / averageFrameTimeMs),
      p1Fps: round(1000 / p99FrameTimeMs),
      averageFrameTimeMs: round(averageFrameTimeMs),
      maxFrameTimeMs: round(sorted[sorted.length - 1] ?? 0),
      drawCalls: rendererInfo.render.calls,
      triangles: rendererInfo.render.triangles,
      geometries: rendererInfo.memory.geometries,
      textures: rendererInfo.memory.textures,
      sampleCount: this.intervalsMs.length,
    };
  }

  reset(): void {
    this.intervalsMs.length = 0;
    this.lastRenderTimeMs = null;
    this.lastSnapshotTimeMs = 0;
  }
}

export function emptyPerformanceSnapshot(): PerformanceSnapshot {
  return {...EMPTY_SNAPSHOT};
}
