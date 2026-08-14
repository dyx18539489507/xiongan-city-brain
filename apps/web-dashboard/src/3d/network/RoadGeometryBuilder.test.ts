import {describe, expect, it} from "vitest";
import {CoordinateService} from "../core/CoordinateService";
import {MaterialManager} from "../scene/MaterialManager";
import type {StaticSceneDocument} from "../scene/types";
import {disposeObject} from "./geometry";
import {RoadGeometryBuilder} from "./RoadGeometryBuilder";

const scene: StaticSceneDocument = {
  metadata: {
    schemaVersion: "1.1",
    sceneId: "xiongan_rongdong_20",
    scenarioId: "xiongan_rongdong_20",
    counts: {junctions: 2, lanes: 2, crossings: 1, trafficLights: 1},
  },
  coordinateSystem: {
    units: "m",
    projection: "+proj=utm +zone=50 +datum=WGS84 +units=m",
    utmZone: 50,
    northernHemisphere: true,
    netOffset: {x: 0, y: 0},
    worldOriginSumo: {x: 0, y: 0},
    sceneBounds: {minX: -20, minY: -20, maxX: 120, maxY: 20},
  },
  junctions: [
    {
      sceneId: "junction:a",
      sumoJunctionId: "a",
      junctionType: "traffic_light",
      position: {x: 0, y: 0},
      shape: [
        {x: -5, y: -5},
        {x: 5, y: -5},
        {x: 5, y: 5},
        {x: -5, y: 5},
      ],
      controlled: false,
      displayId: null,
      displayName: null,
      role: null,
    },
    {
      sceneId: "junction:b",
      sumoJunctionId: "b",
      junctionType: "traffic_light",
      position: {x: 100, y: 0},
      shape: [
        {x: 95, y: -5},
        {x: 105, y: -5},
        {x: 105, y: 5},
        {x: 95, y: 5},
      ],
      controlled: true,
      displayId: "K01",
      displayName: "测试路口",
      role: "core_corridor",
    },
  ],
  edges: [
    {
      sumoEdgeId: "a-b",
      fromJunctionId: "a",
      toJunctionId: "b",
      function: "ordinary",
      roadType: "highway.primary",
      laneIds: ["a-b_0"],
    },
    {
      sumoEdgeId: ":b_c0",
      fromJunctionId: null,
      toJunctionId: null,
      function: "crossing",
      roadType: null,
      laneIds: [":b_c0_0"],
    },
  ],
  lanes: [
    {
      sceneId: "lane:a-b_0",
      sumoLaneId: "a-b_0",
      sumoEdgeId: "a-b",
      index: 0,
      edgeFunction: "ordinary",
      laneKind: "motor",
      shape: [
        {x: 5, y: 0},
        {x: 95, y: 0},
      ],
      widthM: 3.2,
    },
    {
      sceneId: "lane::b_c0_0",
      sumoLaneId: ":b_c0_0",
      sumoEdgeId: ":b_c0",
      index: 0,
      edgeFunction: "crossing",
      laneKind: "pedestrian_crossing",
      shape: [
        {x: 97, y: -6},
        {x: 97, y: 6},
      ],
      widthM: 4,
    },
  ],
  crossings: [
    {
      sceneId: "crossing::b_c0",
      sumoEdgeId: ":b_c0",
      junctionId: "b",
      laneId: ":b_c0_0",
      shape: [
        {x: 97, y: -6},
        {x: 97, y: 6},
      ],
      widthM: 4,
    },
  ],
  trafficLights: [],
  buildings: [],
  vegetation: [],
  zones: [],
  roadsideDevices: [],
  controlCorridors: [
    {
      corridorId: "core",
      junctionIds: ["a", "b"],
      edgeIds: ["a-b"],
      displayIds: ["K00", "K01"],
      segments: [
        {
          fromJunctionId: "a",
          toJunctionId: "b",
          forwardEdgeIds: ["a-b"],
          reverseEdgeIds: [],
        },
      ],
    },
  ],
};

describe("RoadGeometryBuilder", () => {
  it("builds merged geometry and a stop line from SUMO IDs", () => {
    const coordinates = new CoordinateService(scene.coordinateSystem);
    const materials = new MaterialManager();
    const result = new RoadGeometryBuilder(coordinates, materials).build(scene);
    expect(result.root.name).toBe("XionganConnected20RoadNetwork");
    expect(result.stats.laneTriangles).toBeGreaterThan(0);
    expect(result.stats.crossingTriangles).toBeGreaterThan(0);
    expect(result.stats.junctionTriangles).toBe(4);
    expect(result.stats.stopLines).toBe(1);
    expect(result.stats.drawObjects).toBeLessThanOrEqual(10);
    disposeObject(result.root);
  });
});
