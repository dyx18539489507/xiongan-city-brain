import {describe, expect, it} from "vitest";
import type {StaticSceneDocument} from "../3d/scene/types";
import {sceneGeometryBounds} from "./sceneBounds";

describe("sceneGeometryBounds", () => {
  it("fits actual network geometry instead of authored scene padding", () => {
    const scene = {
      coordinateSystem: {sceneBounds: {minX: -2000, minY: -2000, maxX: 2000, maxY: 2000}},
      junctions: [],
      edges: [],
      lanes: [{shape: [{x: 0, y: 10}, {x: 160, y: 190}]}],
      crossings: [],
      buildings: [],
      vegetation: [],
      zones: [],
    } as unknown as StaticSceneDocument;

    expect(sceneGeometryBounds(scene)).toEqual({minX: -14.4, minY: -4.4, maxX: 174.4, maxY: 204.4});
  });

  it("ignores visual context outside the traffic network", () => {
    const scene = {
      coordinateSystem: {sceneBounds: {minX: -5000, minY: -5000, maxX: 5000, maxY: 5000}},
      junctions: [],
      edges: [],
      lanes: [{shape: [{x: 0, y: 0}, {x: 100, y: 200}]}],
      crossings: [],
      buildings: [{footprint: [{x: 4000, y: 4000}, {x: 4500, y: 4500}]}],
      vegetation: [{shape: [{x: -3500, y: -3500}]}],
      zones: [{shape: [{x: 3000, y: -3000}]}],
    } as unknown as StaticSceneDocument;

    expect(sceneGeometryBounds(scene)).toEqual({minX: -16, minY: -16, maxX: 116, maxY: 216});
  });
});
