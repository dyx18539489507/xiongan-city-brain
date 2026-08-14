import {describe, expect, it, vi} from "vitest";
import type * as THREE from "three";
import {
  QualityManager,
  targetFrameRate,
} from "./QualityManager";

describe("QualityManager", () => {
  it("uses hysteresis to degrade quickly and recover conservatively", () => {
    const renderer = {
      setPixelRatio: vi.fn(),
      setSize: vi.fn(),
    } as unknown as Pick<THREE.WebGLRenderer, "setPixelRatio" | "setSize">;
    const manager = new QualityManager(renderer, 2, 1.25);
    expect(manager.snapshot()).toEqual({
      level: "native",
      renderScale: 1,
      pixelRatio: 1.25,
    });
    for (let index = 0; index < 3; index += 1) {
      expect(manager.observe(18, 7, 400, 300)).toBe(false);
    }
    expect(manager.observe(18, 7, 400, 300)).toBe(true);
    expect(manager.snapshot().level).toBe("balanced");
    for (let index = 0; index < 11; index += 1) expect(manager.observe(30)).toBe(false);
    expect(manager.observe(30)).toBe(true);
    expect(manager.snapshot().level).toBe("native");
    manager.applyViewport(1280, 720);
    expect(renderer.setSize).toHaveBeenCalledWith(1280, 720, false);
  });

  it("degrades on tail latency even when average FPS is just above the old threshold", () => {
    const renderer = {
      setPixelRatio: vi.fn(),
      setSize: vi.fn(),
    } as unknown as Pick<THREE.WebGLRenderer, "setPixelRatio" | "setSize">;
    const manager = new QualityManager(renderer, 1, 1.25);
    for (let index = 0; index < 3; index += 1) {
      expect(manager.observe(22.5, 7.5, 999.9, 300)).toBe(false);
    }
    expect(manager.observe(22.5, 7.5, 999.9, 300)).toBe(true);
    expect(manager.snapshot().level).toBe("balanced");
  });

  it("does not permanently degrade for a low-load transition stall", () => {
    const renderer = {
      setPixelRatio: vi.fn(),
      setSize: vi.fn(),
    } as unknown as Pick<THREE.WebGLRenderer, "setPixelRatio" | "setSize">;
    const manager = new QualityManager(renderer, 1, 1.25);
    for (let index = 0; index < 8; index += 1) {
      expect(manager.observe(12, 2, 900, 40)).toBe(false);
    }
    expect(manager.snapshot().level).toBe("native");
  });

  it("reserves CPU headroom in degraded modes", () => {
    expect(targetFrameRate("native")).toBe(30);
    expect(targetFrameRate("balanced")).toBe(24);
    expect(targetFrameRate("performance")).toBe(20);
  });
});
