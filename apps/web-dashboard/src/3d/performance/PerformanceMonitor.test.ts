import {describe, expect, it} from "vitest";
import type * as THREE from "three";
import {PerformanceMonitor} from "./PerformanceMonitor";

function rendererInfo(): THREE.WebGLInfo {
  return {
    autoReset: true,
    memory: {geometries: 14, textures: 6},
    programs: null,
    render: {calls: 21, frame: 4, lines: 0, points: 0, triangles: 12345},
    reset: () => undefined,
    update: () => undefined,
  } as unknown as THREE.WebGLInfo;
}

describe("PerformanceMonitor", () => {
  it("reports submitted render cadence and renderer budgets", () => {
    const monitor = new PerformanceMonitor(120, 50);
    const info = rendererInfo();

    expect(monitor.record(0, info)).toBeNull();
    expect(monitor.record(33.333, info)).toBeNull();
    const snapshot = monitor.record(66.666, info);

    expect(snapshot).not.toBeNull();
    expect(snapshot?.averageFps).toBeCloseTo(30, 1);
    expect(snapshot?.p1Fps).toBeCloseTo(30, 1);
    expect(snapshot?.drawCalls).toBe(21);
    expect(snapshot?.triangles).toBe(12345);
    expect(snapshot?.geometries).toBe(14);
    expect(snapshot?.textures).toBe(6);
  });

  it("keeps a bounded window and includes slow frames in P1", () => {
    const monitor = new PerformanceMonitor(3, 1);
    const info = rendererInfo();
    monitor.record(0, info);
    monitor.record(33, info);
    monitor.record(66, info);
    monitor.record(166, info);
    const snapshot = monitor.record(199, info);

    expect(snapshot?.sampleCount).toBe(3);
    expect(snapshot?.p1Fps).toBe(10);
    expect(snapshot?.maxFrameTimeMs).toBe(100);
  });
});
