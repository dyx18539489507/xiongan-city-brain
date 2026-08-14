import type {SceneCoordinateSystem} from "../core/CoordinateService";

export type Point2 = {x: number; y: number};
export type SceneBounds = {minX: number; minY: number; maxX: number; maxY: number};

export type SceneMetadata = {
  schemaVersion: string;
  sceneId: string;
  scenarioId: string;
  counts: Record<string, number>;
};

export type SceneJunction = {
  sceneId: string;
  sumoJunctionId: string;
  junctionType: string;
  position: Point2;
  shape: Point2[];
  controlled: boolean;
  displayId: string | null;
  displayName: string | null;
  role: string | null;
};

export type SceneEdge = {
  sumoEdgeId: string;
  fromJunctionId: string | null;
  toJunctionId: string | null;
  function: string;
  roadType: string | null;
  laneIds: string[];
};

export type SceneLane = {
  sceneId: string;
  sumoLaneId: string;
  sumoEdgeId: string;
  index: number;
  edgeFunction: string;
  laneKind: string;
  shape: Point2[];
  widthM: number;
};

export type SceneCrossing = {
  sceneId: string;
  sumoEdgeId: string;
  junctionId: string;
  laneId: string;
  shape: Point2[];
  widthM: number;
};

export type SceneTrafficLightPhase = {
  index: number;
  durationS: number;
  state: string;
  minDurationS: number | null;
  maxDurationS: number | null;
};

export type SceneTrafficLightLink = {
  linkIndex: number;
  fromLaneId: string;
  toLaneId: string;
  viaLaneId: string | null;
};

export type SceneTrafficLight = {
  sceneId: string;
  sumoTlsId: string;
  controlledJunctionId: string;
  programId: string;
  programType: string;
  offsetS: number;
  phases: SceneTrafficLightPhase[];
  links: SceneTrafficLightLink[];
  displayId: string | null;
};

export type SceneBuilding = {
  sceneId: string;
  sourceId: string;
  name: string | null;
  buildingType: string;
  footprint: Point2[];
  heightM: number | null;
  levels: number | null;
  heightSource: string;
  tags: Record<string, string>;
  provenance: string;
};

export type SceneVegetationArea = {
  sceneId: string;
  sourceId: string;
  areaType: string;
  shape: Point2[];
  tags: Record<string, string>;
  provenance: string;
};

export type SceneZone = {
  sceneId: string;
  sourceId: string;
  areaType: string;
  shape: Point2[];
  tags: Record<string, string>;
  provenance: string;
};

export type SceneRoadsideDevice = {
  deviceId: string;
  deviceType: string;
  position: Point2;
  status: string;
  managedJunctions: string[];
  communicationStatus: string;
  provenance: string;
};

export type CorridorSegment = {
  fromJunctionId: string;
  toJunctionId: string;
  forwardEdgeIds: string[];
  reverseEdgeIds: string[];
};

export type ControlCorridor = {
  corridorId: string;
  junctionIds: string[];
  edgeIds: string[];
  displayIds: string[];
  segments: CorridorSegment[];
};

export type StaticSceneDocument = {
  metadata: SceneMetadata;
  coordinateSystem: SceneCoordinateSystem & {
    sceneBounds: SceneBounds;
  };
  junctions: SceneJunction[];
  edges: SceneEdge[];
  lanes: SceneLane[];
  crossings: SceneCrossing[];
  trafficLights: SceneTrafficLight[];
  buildings: SceneBuilding[];
  vegetation: SceneVegetationArea[];
  zones: SceneZone[];
  roadsideDevices: SceneRoadsideDevice[];
  controlCorridors: ControlCorridor[];
};

export function assertStaticScene(value: unknown): asserts value is StaticSceneDocument {
  if (!value || typeof value !== "object") throw new Error("scene payload is not an object");
  const scene = value as Partial<StaticSceneDocument>;
  if (scene.metadata?.sceneId !== "xiongan_rongdong_20") {
    throw new Error("unexpected or missing sceneId");
  }
  if (
    !scene.coordinateSystem ||
    !Array.isArray(scene.junctions) ||
    !Array.isArray(scene.edges) ||
    !Array.isArray(scene.lanes) ||
    !Array.isArray(scene.crossings) ||
    !Array.isArray(scene.trafficLights) ||
    !Array.isArray(scene.buildings) ||
    !Array.isArray(scene.vegetation) ||
    !Array.isArray(scene.zones) ||
    !Array.isArray(scene.roadsideDevices) ||
    !Array.isArray(scene.controlCorridors)
  ) {
    throw new Error("scene payload is incomplete");
  }
}
