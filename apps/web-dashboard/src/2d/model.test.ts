import {describe, expect, it} from "vitest";
import {defaultLayerVisibility} from "./model";

describe("defaultLayerVisibility", () => {
  it("shows the simulation roads without enabling the geographic map", () => {
    expect(defaultLayerVisibility.baseMap).toBe(true);
    expect(defaultLayerVisibility.geographicBaseMap).toBe(false);
  });

  it("starts with the 3D algorithm evidence lines hidden", () => {
    expect(defaultLayerVisibility.algorithm).toBe(false);
  });
});
