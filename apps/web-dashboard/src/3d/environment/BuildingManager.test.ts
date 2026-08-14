import {describe, expect, it} from "vitest";
import type {SceneBuilding} from "../scene/types";
import {visualBuildingHeight} from "./BuildingManager";

function building(overrides: Partial<SceneBuilding> = {}): SceneBuilding {
  return {
    sceneId: "building:osm:way:1",
    sourceId: "osm:way:1",
    name: null,
    buildingType: "yes",
    footprint: [{x: 0, y: 0}, {x: 10, y: 0}, {x: 10, y: 10}],
    heightM: null,
    levels: null,
    heightSource: "not_available",
    tags: {building: "yes"},
    provenance: "openstreetmap",
    ...overrides,
  };
}

describe("visualBuildingHeight", () => {
  it("preserves explicit OSM height", () => {
    expect(visualBuildingHeight(building({heightM: 21}))).toEqual({
      heightM: 21,
      modeled: false,
    });
  });

  it("derives levels and marks only missing height as modeled", () => {
    expect(visualBuildingHeight(building({levels: 6}))).toEqual({
      heightM: 18.9,
      modeled: false,
    });
    const first = visualBuildingHeight(building());
    const second = visualBuildingHeight(building());
    expect(first.modeled).toBe(true);
    expect(first.heightM).toBe(second.heightM);
    expect(first.heightM).toBeGreaterThanOrEqual(10);
  });
});
