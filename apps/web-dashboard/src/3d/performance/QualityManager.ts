import type * as THREE from "three";

export type QualitySnapshot = {
  level: "native" | "balanced" | "performance";
  renderScale: number;
  pixelRatio: number;
};

export function targetFrameRate(level: QualitySnapshot["level"]): number {
  if (level === "performance") return 20;
  if (level === "balanced") return 24;
  return 30;
}

const SCALES = [1, 0.88, 0.75] as const;

export class QualityManager {
  private levelIndex = 0;
  private slowWindows = 0;
  private fastWindows = 0;

  constructor(
    private readonly renderer: Pick<THREE.WebGLRenderer, "setPixelRatio" | "setSize">,
    private readonly devicePixelRatio: number,
    private readonly maximumPixelRatio = 1.25,
  ) {
    this.applyPixelRatio();
  }

  observe(
    averageFps: number,
    p1Fps = averageFps,
    maxFrameTimeMs = averageFps > 0 ? 1_000 / averageFps : 1_000,
    dynamicEntityCount = 0,
  ): boolean {
    // Average FPS alone concealed long main-thread stalls during rising traffic
    // loads (for example 22.5 average / 7.5 P1 / 999 ms maximum). Treat tail
    // latency as a first-class signal so MX250 degrades before the page becomes
    // unresponsive.
    const highLoad = dynamicEntityCount >= 180;
    const slow = highLoad && (averageFps < 24.5 || p1Fps < 8 || maxFrameTimeMs > 300);
    const targetFps = targetFrameRate(this.snapshot().level);
    const fast = !highLoad && averageFps > targetFps * 0.9 && p1Fps > 5 && maxFrameTimeMs < 250;
    if (slow) {
      this.slowWindows += 1;
      this.fastWindows = 0;
    } else if (fast) {
      this.fastWindows += 1;
      this.slowWindows = 0;
    } else {
      this.slowWindows = 0;
      this.fastWindows = 0;
    }
    if (this.slowWindows >= 4 && this.levelIndex < SCALES.length - 1) {
      this.levelIndex += 1;
      this.slowWindows = 0;
      this.applyPixelRatio();
      return true;
    }
    if (this.fastWindows >= 12 && this.levelIndex > 0) {
      this.levelIndex -= 1;
      this.fastWindows = 0;
      this.applyPixelRatio();
      return true;
    }
    return false;
  }

  applyViewport(width: number, height: number): void {
    this.applyPixelRatio();
    this.renderer.setSize(width, height, false);
  }

  snapshot(): QualitySnapshot {
    const renderScale = SCALES[this.levelIndex] ?? 1;
    return {
      level: this.levelIndex === 0
        ? "native"
        : this.levelIndex === 1
          ? "balanced"
          : "performance",
      renderScale,
      pixelRatio: Math.min(
        this.devicePixelRatio * renderScale,
        this.maximumPixelRatio,
      ),
    };
  }

  private applyPixelRatio(): void {
    this.renderer.setPixelRatio(this.snapshot().pixelRatio);
  }
}
