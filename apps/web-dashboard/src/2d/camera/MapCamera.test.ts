import {describe, expect, it} from "vitest";
import {MapCamera} from "./MapCamera";

describe("MapCamera safe viewport", () => {
  it("fits and centers the scene inside overlay insets", () => {
    const camera = new MapCamera();
    camera.resize(1000, 600, 1);
    camera.setViewportInsets({top: 80, right: 300, bottom: 180, left: 250});
    camera.setSceneBounds({minX: 0, minY: 0, maxX: 1000, maxY: 500});

    const safeViewport = camera.viewportBounds();
    const sceneCenter = camera.worldToScreen({x: 500, y: 250});
    expect(sceneCenter.x).toBeCloseTo((safeViewport.left + safeViewport.right) / 2);
    expect(sceneCenter.y).toBeCloseTo((safeViewport.top + safeViewport.bottom) / 2);

    const topLeft = camera.worldToScreen({x: 0, y: 500});
    const bottomRight = camera.worldToScreen({x: 1000, y: 0});
    expect(camera.getZoomRatio()).toBeCloseTo(1);
    expect(topLeft.x).toBeGreaterThanOrEqual(safeViewport.left + 35);
    expect(topLeft.y).toBeGreaterThanOrEqual(safeViewport.top + 35);
    expect(bottomRight.x).toBeLessThanOrEqual(safeViewport.right - 35);
    expect(bottomRight.y).toBeLessThanOrEqual(safeViewport.bottom - 35);
  });
});

describe("MapCamera synchronized pose", () => {
  it("copies a pan and zoom pose without animation", () => {
    const source = new MapCamera();
    const target = new MapCamera();
    source.resize(800, 500, 1);
    target.resize(800, 500, 1);
    const bounds = {minX: 0, minY: 0, maxX: 1000, maxY: 600};
    source.setSceneBounds(bounds);
    target.setSceneBounds(bounds);
    source.pan(60, -25);
    source.zoomAt(400, 250, 1.4);

    target.setPose(source.getPose());

    expect(target.getPose()).toEqual(source.getPose());
  });

  it("does not revise an already synchronized pose", () => {
    const camera = new MapCamera();
    camera.resize(800, 500, 1);
    camera.setSceneBounds({minX: 0, minY: 0, maxX: 1000, maxY: 600});
    const pose = camera.getPose();
    const revision = camera.revision;

    camera.setPose(pose);

    expect(camera.revision).toBe(revision);
  });
});

describe("MapCamera resize and navigation bounds", () => {
  it("preserves an intentional zoom when the canvas size changes", () => {
    const camera = new MapCamera();
    camera.resize(800, 500, 1);
    camera.setSceneBounds({minX: 0, minY: 0, maxX: 1000, maxY: 600});
    camera.zoomAt(400, 250, 2);
    const before = camera.getPose();

    camera.resize(1200, 700, 1.5);

    expect(camera.getPose().centerX).toBeCloseTo(before.centerX);
    expect(camera.getPose().centerY).toBeCloseTo(before.centerY);
    expect(camera.getPose().scale).toBeCloseTo(before.scale);
  });

  it("keeps the camera center inside the scene after extreme panning", () => {
    const camera = new MapCamera();
    camera.resize(800, 500, 1);
    camera.setSceneBounds({minX: 0, minY: 0, maxX: 1000, maxY: 600});

    camera.pan(1_000_000, -1_000_000);

    const pose = camera.getPose();
    expect(pose.centerX).toBeGreaterThanOrEqual(0);
    expect(pose.centerX).toBeLessThanOrEqual(1000);
    expect(pose.centerY).toBeGreaterThanOrEqual(0);
    expect(pose.centerY).toBeLessThanOrEqual(600);
  });

  it("re-fits an overview when its viewport changes", () => {
    const camera = new MapCamera();
    camera.resize(800, 500, 1);
    camera.setSceneBounds({minX: 0, minY: 0, maxX: 1000, maxY: 600});
    const before = camera.getPose();

    camera.resize(1200, 700, 1);

    expect(camera.getZoomRatio()).toBeCloseTo(1);
    expect(camera.getPose().scale).toBeGreaterThan(before.scale);
    expect(camera.getPose().centerX).toBeCloseTo(500);
    expect(camera.getPose().centerY).toBeCloseTo(300);
  });
});
