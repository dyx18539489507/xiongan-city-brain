import {describe, expect, it} from "vitest";
import type {StaticSceneDocument} from "../../3d/scene/types";
import {resolveSignalApproachState} from "./ReferenceControlPanel";

function signalScene(): StaticSceneDocument {
  const lanes = [
    ["north", [{x: 50, y: 100}, {x: 50, y: 50}]],
    ["east", [{x: 100, y: 50}, {x: 50, y: 50}]],
    ["south", [{x: 50, y: 0}, {x: 50, y: 50}]],
    ["west", [{x: 0, y: 50}, {x: 50, y: 50}]],
  ].map(([id, shape], index) => ({
    sceneId: String(id), sumoLaneId: String(id), sumoEdgeId: String(id), index,
    edgeFunction: "normal", laneKind: "motor", shape: shape as Array<{x: number; y: number}>, widthM: 3.2,
  }));
  return {
    metadata: {schemaVersion: "1", sceneId: "test", scenarioId: "test", counts: {}},
    coordinateSystem: {units: "m", projection: "!", utmZone: 0, northernHemisphere: true, netOffset: {x: 0, y: 0}, worldOriginSumo: {x: 0, y: 0}, sceneBounds: {minX: 0, minY: 0, maxX: 100, maxY: 100}},
    junctions: [], roads: [], edges: [], lanes, crossings: [], buildings: [], vegetation: [], zones: [], roadsideDevices: [], controlCorridors: [],
    trafficLights: [{
      sceneId: "tls:test", sumoTlsId: "tls-test", controlledJunctionId: "junction-test", programId: "0", programType: "static", offsetS: 0, phases: [], displayId: "T01",
      links: lanes.map((lane, index) => ({linkIndex: index, fromLaneId: lane.sumoLaneId, toLaneId: `${lane.sumoLaneId}-out`, viaLaneId: null})),
    }],
  };
}

describe("resolveSignalApproachState", () => {
  it("maps SUMO controlled links to their true incoming cardinal approaches", () => {
    expect(resolveSignalApproachState(signalScene(), "junction-test", "Gyrs")).toEqual({
      hasData: true,
      colors: {north: "green", east: "yellow", south: "red", west: "green"},
    });
  });

  it("does not invent lamp colors before a live phase is available", () => {
    expect(resolveSignalApproachState(signalScene(), "junction-test")).toEqual({
      hasData: false,
      colors: {north: "off", east: "off", south: "off", west: "off"},
    });
  });
});
