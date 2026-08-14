import {describe, expect, it} from "vitest";
import {distanceToLane, pointInJunction} from "./InteractionManager";

describe("InteractionManager geometry selection", () => {
  it("finds the metric distance to a SUMO lane centerline", () => {
    expect(distanceToLane({x: 5, y: 3}, {
      sceneId: "lane:a",
      sumoLaneId: "a_0",
      sumoEdgeId: "a",
      index: 0,
      edgeFunction: "normal",
      laneKind: "motor_vehicle",
      shape: [{x: 0, y: 0}, {x: 10, y: 0}],
      widthM: 3.2,
    })).toBeCloseTo(3);
  });

  it("selects a point inside a junction polygon", () => {
    expect(pointInJunction({x: 5, y: 5}, {
      sceneId: "junction:j",
      sumoJunctionId: "j",
      junctionType: "traffic_light",
      position: {x: 5, y: 5},
      shape: [{x: 0, y: 0}, {x: 10, y: 0}, {x: 10, y: 10}, {x: 0, y: 10}],
      controlled: true,
      displayId: "K01",
      displayName: null,
      role: "core_corridor",
    })).toBe(true);
  });
});
