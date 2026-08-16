import {describe, expect, it} from "vitest";
import {sumoAngleToCanvasRadians} from "./heading";

describe("sumoAngleToCanvasRadians", () => {
  it.each([
    [0, -Math.PI / 2],
    [90, 0],
    [180, Math.PI / 2],
    [270, Math.PI],
    [360, -Math.PI / 2],
  ])("maps SUMO heading %s° to the Canvas sprite axis", (sumo, canvas) => {
    expect(sumoAngleToCanvasRadians(sumo)).toBeCloseTo(canvas, 8);
  });

  it("normalizes negative headings", () => {
    expect(sumoAngleToCanvasRadians(-90)).toBeCloseTo(Math.PI, 8);
  });
});
