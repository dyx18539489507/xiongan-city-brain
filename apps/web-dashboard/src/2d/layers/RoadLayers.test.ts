import {describe, expect, it} from "vitest";
import {offsetPolyline, roadLevelOfDetail} from "./RoadLayers";

describe("2D road level of detail", () => {
  it("reveals lane detail only after meaningful scene-relative zoom", () => {
    expect(roadLevelOfDetail(1)).toBe("overview");
    expect(roadLevelOfDetail(4)).toBe("district");
    expect(roadLevelOfDetail(12)).toBe("street");
  });

  it("offsets a straight lane boundary in world metres", () => {
    expect(offsetPolyline([{x: 0, y: 0}, {x: 10, y: 0}], 2)).toEqual([
      {x: 0, y: 2},
      {x: 10, y: 2},
    ]);
  });
});
