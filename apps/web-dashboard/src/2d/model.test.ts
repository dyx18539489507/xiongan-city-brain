import {describe, expect, it} from "vitest";
import {defaultLayerVisibility} from "./model";

describe("defaultLayerVisibility", () => {
  it("starts with the geographic base map hidden", () => {
    expect(defaultLayerVisibility.baseMap).toBe(false);
  });

  it("starts with the 3D algorithm evidence lines hidden", () => {
    expect(defaultLayerVisibility.algorithm).toBe(false);
  });
});
