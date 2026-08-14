import {describe, expect, it} from "vitest";
import {CoordinateService} from "../core/CoordinateService";
import type {SceneLane, SceneTrafficLight} from "../scene/types";
import {buildSignalPlacements, classifySignalAspect} from "./TrafficLightManager";

const coordinateService = new CoordinateService({
  units: "m",
  projection: "+proj=utm +zone=50",
  utmZone: 50,
  northernHemisphere: true,
  netOffset: {x: 0, y: 0},
  worldOriginSumo: {x: 100, y: 100},
});

const lanes: SceneLane[] = [
  {
    sceneId: "lane:in_0",
    sumoLaneId: "in_0",
    sumoEdgeId: "in",
    index: 0,
    edgeFunction: "ordinary",
    laneKind: "motor",
    shape: [{x: 90, y: 80}, {x: 90, y: 100}],
    widthM: 3.2,
  },
  {
    sceneId: "lane:out_0",
    sumoLaneId: "out_0",
    sumoEdgeId: "out",
    index: 0,
    edgeFunction: "ordinary",
    laneKind: "motor",
    shape: [{x: 90, y: 100}, {x: 90, y: 120}],
    widthM: 3.2,
  },
  {
    sceneId: "lane:left_0",
    sumoLaneId: "left_0",
    sumoEdgeId: "left",
    index: 0,
    edgeFunction: "ordinary",
    laneKind: "motor",
    shape: [{x: 90, y: 100}, {x: 70, y: 100}],
    widthM: 3.2,
  },
  {
    sceneId: "lane:right_0",
    sumoLaneId: "right_0",
    sumoEdgeId: "right",
    index: 0,
    edgeFunction: "ordinary",
    laneKind: "motor",
    shape: [{x: 90, y: 100}, {x: 110, y: 100}],
    widthM: 3.2,
  },
];

const controllers: SceneTrafficLight[] = [
  {
    sceneId: "tls:J1:0",
    sumoTlsId: "J1",
    controlledJunctionId: "J1",
    programId: "0",
    programType: "static",
    offsetS: 0,
    phases: [],
    links: [
      {linkIndex: 0, fromLaneId: "in_0", toLaneId: "out_0", viaLaneId: ":J1_0_0"},
      {linkIndex: 1, fromLaneId: "in_0", toLaneId: "left_0", viaLaneId: ":J1_1_0"},
      {linkIndex: 2, fromLaneId: "missing_0", toLaneId: "out_0", viaLaneId: null},
    ],
    displayId: "K01",
  },
];

describe("buildSignalPlacements", () => {
  it("maps every link to its real incoming lane and shares one physical pole per lane", () => {
    const result = buildSignalPlacements(coordinateService, controllers, lanes);

    expect(result.placements).toHaveLength(2);
    expect(result.placements.map((item) => item.linkIndex)).toEqual([0, 1]);
    expect(result.placements.map((item) => item.aspect)).toEqual(["straight", "left"]);
    expect(result.poleKeys.size).toBe(1);
    expect(result.missingLanes).toBe(1);
    expect(result.placements[0]?.position.y).toBe(4.8);
  });

  it("classifies movement geometry and vulnerable road-user signal heads", () => {
    const incoming = lanes[0] as SceneLane;
    expect(classifySignalAspect(incoming, lanes[1])).toBe("straight");
    expect(classifySignalAspect(incoming, lanes[2])).toBe("left");
    expect(classifySignalAspect(incoming, lanes[3])).toBe("right");
    expect(classifySignalAspect({...incoming, laneKind: "pedestrian_area"}, lanes[1])).toBe(
      "pedestrian",
    );
    expect(classifySignalAspect({...incoming, laneKind: "bicycle"}, lanes[1])).toBe("bicycle");
  });
});
