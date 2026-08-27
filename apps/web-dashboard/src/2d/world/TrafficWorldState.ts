import type {DigitalTwinState} from "../../3d/network/digitalTwinTypes";
import type {
  Point2,
  SceneBuilding,
  SceneEdge,
  SceneJunction,
  SceneLane,
  SceneTrafficLight,
  StaticSceneDocument,
} from "../../3d/scene/types";
import type {IntersectionRealtime, LaneRealtime, RealtimeSnapshot} from "../../types";

export type GeometryBounds = {minX: number; minY: number; maxX: number; maxY: number};

export type IndexedEdge = GeometryBounds & {edge: SceneEdge; shape: Point2[]};
export type IndexedLane = GeometryBounds & {lane: SceneLane};
export type IndexedBuilding = GeometryBounds & {building: SceneBuilding};
export type IndexedJunction = GeometryBounds & {junction: SceneJunction};

const SPATIAL_CELL_SIZE_M = 400;
const MAX_INDEXED_QUERY_CELLS = 64;

/** A compact uniform-grid index for the immutable SUMO scene geometry. */
export class GeometrySpatialIndex<T extends GeometryBounds> {
  private readonly cells = new Map<string, T[]>();

  constructor(
    private readonly items: readonly T[],
    private readonly cellSize = SPATIAL_CELL_SIZE_M,
  ) {
    for (const item of items) {
      const range = this.cellRange(item);
      for (let x = range.minX; x <= range.maxX; x += 1) {
        for (let y = range.minY; y <= range.maxY; y += 1) {
          const key = `${x}:${y}`;
          const cell = this.cells.get(key);
          if (cell) cell.push(item);
          else this.cells.set(key, [item]);
        }
      }
    }
  }

  query(bounds: GeometryBounds): readonly T[] {
    if (!this.items.length) return this.items;
    const range = this.cellRange(bounds);
    const cellCount = (range.maxX - range.minX + 1) * (range.maxY - range.minY + 1);
    if (cellCount > MAX_INDEXED_QUERY_CELLS) return this.items;
    const matches = new Set<T>();
    for (let x = range.minX; x <= range.maxX; x += 1) {
      for (let y = range.minY; y <= range.maxY; y += 1) {
        for (const item of this.cells.get(`${x}:${y}`) ?? []) {
          if (
            item.maxX >= bounds.minX && item.minX <= bounds.maxX
            && item.maxY >= bounds.minY && item.minY <= bounds.maxY
          ) matches.add(item);
        }
      }
    }
    return [...matches];
  }

  private cellRange(bounds: GeometryBounds) {
    return {
      minX: Math.floor(bounds.minX / this.cellSize),
      minY: Math.floor(bounds.minY / this.cellSize),
      maxX: Math.floor(bounds.maxX / this.cellSize),
      maxY: Math.floor(bounds.maxY / this.cellSize),
    };
  }
}

function geometryBounds(points: readonly Point2[]): GeometryBounds | null {
  if (!points.length) return null;
  let minX = points[0].x;
  let minY = points[0].y;
  let maxX = minX;
  let maxY = minY;
  for (let index = 1; index < points.length; index += 1) {
    const point = points[index];
    if (point.x < minX) minX = point.x;
    if (point.y < minY) minY = point.y;
    if (point.x > maxX) maxX = point.x;
    if (point.y > maxY) maxY = point.y;
  }
  return {minX, minY, maxX, maxY};
}

export type TrafficWorldState = {
  scene: StaticSceneDocument;
  digitalTwin: DigitalTwinState;
  snapshot: RealtimeSnapshot;
  edgeById: ReadonlyMap<string, SceneEdge>;
  laneById: ReadonlyMap<string, SceneLane>;
  junctionById: ReadonlyMap<string, SceneJunction>;
  controlledJunctions: readonly SceneJunction[];
  roadNameById: ReadonlyMap<string, string>;
  trafficLightByJunctionId: ReadonlyMap<string, SceneTrafficLight>;
  indexedEdges: readonly IndexedEdge[];
  indexedLanes: readonly IndexedLane[];
  indexedBuildings: readonly IndexedBuilding[];
  indexedJunctions: readonly IndexedJunction[];
  edgeSpatialIndex: GeometrySpatialIndex<IndexedEdge>;
  laneSpatialIndex: GeometrySpatialIndex<IndexedLane>;
  buildingSpatialIndex: GeometrySpatialIndex<IndexedBuilding>;
  junctionSpatialIndex: GeometrySpatialIndex<IndexedJunction>;
  corridorEdgeIds: ReadonlySet<string>;
  corridorJunctionIds: ReadonlySet<string>;
  laneRealtime: ReadonlyMap<string, LaneRealtime>;
  intersectionRealtime: ReadonlyMap<string, IntersectionRealtime>;
};

/**
 * Protocol adapter between immutable scene + live stores and presentation layers.
 * Render layers never open sockets and never mutate simulation state.
 */
export class TrafficWorldStateAdapter {
  private scene: StaticSceneDocument | null = null;
  private edgeById = new Map<string, SceneEdge>();
  private laneById = new Map<string, SceneLane>();
  private junctionById = new Map<string, SceneJunction>();
  private controlledJunctions: SceneJunction[] = [];
  private roadNameById = new Map<string, string>();
  private trafficLightByJunctionId = new Map<string, SceneTrafficLight>();
  private indexedEdges: IndexedEdge[] = [];
  private indexedLanes: IndexedLane[] = [];
  private indexedBuildings: IndexedBuilding[] = [];
  private indexedJunctions: IndexedJunction[] = [];
  private edgeSpatialIndex = new GeometrySpatialIndex<IndexedEdge>([]);
  private laneSpatialIndex = new GeometrySpatialIndex<IndexedLane>([]);
  private buildingSpatialIndex = new GeometrySpatialIndex<IndexedBuilding>([]);
  private junctionSpatialIndex = new GeometrySpatialIndex<IndexedJunction>([]);
  private corridorEdgeIds = new Set<string>();
  private corridorJunctionIds = new Set<string>();

  setScene(scene: StaticSceneDocument): void {
    this.scene = scene;
    this.edgeById = new Map(scene.edges.map((edge) => [edge.sumoEdgeId, edge]));
    this.laneById = new Map(scene.lanes.map((lane) => [lane.sumoLaneId, lane]));
    this.junctionById = new Map(scene.junctions.map((junction) => [junction.sumoJunctionId, junction]));
    this.controlledJunctions = scene.junctions.filter((junction) => junction.controlled);
    this.roadNameById = new Map(
      (scene.roads ?? []).map((road) => [road.sceneId, road.name ?? road.sourceRoadId]),
    );
    this.trafficLightByJunctionId = new Map(scene.trafficLights.map((light) => [light.controlledJunctionId, light]));
    this.corridorEdgeIds = new Set(scene.controlCorridors.flatMap((corridor) => corridor.edgeIds));
    this.corridorJunctionIds = new Set(scene.controlCorridors.flatMap((corridor) => corridor.junctionIds));
    this.indexedEdges = scene.edges.flatMap((edge) => {
      const shape = edge.shape ?? [];
      const bounds = geometryBounds(shape);
      return shape.length >= 2 && bounds ? [{edge, shape, ...bounds}] : [];
    });
    this.indexedLanes = scene.lanes.flatMap((lane) => {
      const bounds = geometryBounds(lane.shape);
      return lane.shape.length >= 2 && bounds ? [{lane, ...bounds}] : [];
    });
    this.indexedBuildings = scene.buildings.flatMap((building) => {
      const bounds = geometryBounds(building.footprint);
      return building.footprint.length >= 3 && bounds ? [{building, ...bounds}] : [];
    });
    this.indexedJunctions = scene.junctions.flatMap((junction) => {
      const points = junction.shape.length >= 3 ? junction.shape : [junction.position];
      const bounds = geometryBounds(points);
      return bounds ? [{junction, ...bounds}] : [];
    });
    this.edgeSpatialIndex = new GeometrySpatialIndex(this.indexedEdges);
    this.laneSpatialIndex = new GeometrySpatialIndex(this.indexedLanes);
    this.buildingSpatialIndex = new GeometrySpatialIndex(this.indexedBuildings);
    this.junctionSpatialIndex = new GeometrySpatialIndex(this.indexedJunctions);
  }

  compose(digitalTwin: DigitalTwinState, snapshot: RealtimeSnapshot): TrafficWorldState | null {
    if (!this.scene) return null;
    const intersections = snapshot.intersections ?? [];
    return {
      scene: this.scene,
      digitalTwin,
      snapshot,
      edgeById: this.edgeById,
      laneById: this.laneById,
      junctionById: this.junctionById,
      controlledJunctions: this.controlledJunctions,
      roadNameById: this.roadNameById,
      trafficLightByJunctionId: this.trafficLightByJunctionId,
      indexedEdges: this.indexedEdges,
      indexedLanes: this.indexedLanes,
      indexedBuildings: this.indexedBuildings,
      indexedJunctions: this.indexedJunctions,
      edgeSpatialIndex: this.edgeSpatialIndex,
      laneSpatialIndex: this.laneSpatialIndex,
      buildingSpatialIndex: this.buildingSpatialIndex,
      junctionSpatialIndex: this.junctionSpatialIndex,
      corridorEdgeIds: this.corridorEdgeIds,
      corridorJunctionIds: this.corridorJunctionIds,
      laneRealtime: new Map(intersections.flatMap((item) => item.lane_states ?? []).map((lane) => [lane.lane_id, lane])),
      intersectionRealtime: new Map(intersections.map((item) => [item.intersection_id, item])),
    };
  }
}
