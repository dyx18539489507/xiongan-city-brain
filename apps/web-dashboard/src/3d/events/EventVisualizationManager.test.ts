import {describe, expect, it} from "vitest";
import {CoordinateService} from "../core/CoordinateService";
import type {RealtimeEvent} from "../network/digitalTwinTypes";
import type {SceneLane} from "../scene/types";
import {EventVisualizationManager} from "./EventVisualizationManager";

const coordinates = new CoordinateService({
  units: "m",
  projection: "+proj=utm +zone=50",
  utmZone: 50,
  northernHemisphere: true,
  netOffset: {x: 0, y: 0},
  worldOriginSumo: {x: 0, y: 0},
});
const lane: SceneLane = {
  sceneId: "lane:edge_0",
  sumoLaneId: "edge_0",
  sumoEdgeId: "edge",
  index: 0,
  edgeFunction: "ordinary",
  laneKind: "motor",
  shape: [{x: 0, y: 0}, {x: 30, y: 0}],
  widthM: 3.2,
};

function event(eventId: string, name: string): RealtimeEvent {
  return {
    eventId,
    simulationTime: 10,
    event: name,
    detail: "edge_0",
    payload: {disturbance_id: "works"},
  };
}

describe("EventVisualizationManager", () => {
  it("maps lane closure and reopening events to pooled construction instances", () => {
    const manager = new EventVisualizationManager(coordinates, [lane]);
    manager.applyEvents([event("start", "ROADWORK_LANE_CLOSED")], new Map());
    expect(manager.activeCount()).toBe(1);
    expect(manager.stats.activeRoadworks).toBe(1);
    expect(manager.stats.cones).toBeGreaterThan(0);
    expect(manager.stats.barriers).toBe(1);

    manager.reset();
    expect(manager.activeCount()).toBe(0);
    expect(manager.stats.cones).toBe(0);
    expect(manager.stats.barriers).toBe(0);

    manager.applyEvents([event("restart", "ROADWORK_LANE_CLOSED")], new Map());
    expect(manager.activeCount()).toBe(1);

    manager.applyEvents(
      [event("restart", "ROADWORK_LANE_CLOSED"), event("end", "ROADWORK_LANE_REOPENED")],
      new Map(),
    );
    expect(manager.activeCount()).toBe(0);
    expect(manager.stats.cones).toBe(0);
    manager.dispose();
  });
});
