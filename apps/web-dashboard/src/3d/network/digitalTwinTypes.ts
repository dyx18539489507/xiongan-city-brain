export type DigitalTwinConnection =
  | "connecting"
  | "resyncing"
  | "online"
  | "offline";

export type VehicleEntity = {
  id: string;
  type: string;
  vehicleClass: string;
  x: number;
  y: number;
  angle: number;
  speed: number;
  acceleration: number;
  laneId: string;
  edgeId: string;
  routeId: string;
  signals: number;
  color: string;
  brake: boolean;
  status: "moving" | "waiting";
};

export type PedestrianEntity = {
  id: string;
  type: string;
  x: number;
  y: number;
  angle: number;
  speed: number;
  laneId: string;
  edgeId: string;
  crossingId: string | null;
  waitingAreaId: string | null;
  status: "walking" | "waiting";
};

export type TrafficLightEntity = {
  id: string;
  phaseIndex: number;
  state: string;
  phaseDurationS: number;
  remainingS: number;
};

export type SafetyConflictEntity = {
  id: string;
  participantAId: string;
  participantBId: string;
  conflictType: string;
  x: number;
  y: number;
  minimumDistanceM: number;
  relativeSpeedMS: number;
  ttcS: number | null;
  petS: number | null;
  severity: string;
};

export type EntityStateSet = {
  vehicles: VehicleEntity[];
  bicycles: VehicleEntity[];
  pedestrians: PedestrianEntity[];
};

export type EntityRemovalSet = {
  vehicles: string[];
  bicycles: string[];
  pedestrians: string[];
};

export type RealtimeEvent = {
  eventId: string;
  simulationTime: number;
  event: string;
  detail: string | null;
  payload: Record<string, unknown>;
};

export type SceneReference = {
  sceneId: string;
  schemaVersion: string;
  url: string;
  sha256: string;
  bytes: number;
  counts: Record<string, number>;
};

export type DigitalTwinInit = {
  type: "init";
  protocolVersion: "1.0";
  sequence: number;
  status: string;
  experimentId: string | null;
  scenarioId: string;
  simulationTimeS: number;
  tickHz: number;
  scene: SceneReference;
  vehicleTypes: string[];
  entities: EntityStateSet;
  trafficLights: TrafficLightEntity[];
  conflicts?: SafetyConflictEntity[];
  activeEvents?: RealtimeEvent[];
  metrics?: Record<string, number | string | boolean | null>;
  intersectionMetrics?: Array<Record<string, number | string | boolean | null>>;
};

export type DigitalTwinDelta = {
  type: "delta";
  protocolVersion: "1.0";
  sequence: number;
  experimentId: string;
  simulationTimeS: number;
  spawn: EntityStateSet;
  update: EntityStateSet;
  remove: EntityRemovalSet;
  trafficLights: TrafficLightEntity[];
  conflicts?: SafetyConflictEntity[];
  events: RealtimeEvent[];
  metrics?: Record<string, number | string | boolean | null>;
  intersectionMetrics?: Array<Record<string, number | string | boolean | null>>;
};

export type DigitalTwinMessage = DigitalTwinInit | DigitalTwinDelta;

export type DigitalTwinState = {
  initialized: boolean;
  sequence: number;
  status: string;
  experimentId: string | null;
  scenarioId: string | null;
  simulationTimeS: number;
  tickHz: number;
  scene: SceneReference | null;
  vehicleTypes: string[];
  vehicles: ReadonlyMap<string, VehicleEntity>;
  bicycles: ReadonlyMap<string, VehicleEntity>;
  pedestrians: ReadonlyMap<string, PedestrianEntity>;
  trafficLights: ReadonlyMap<string, TrafficLightEntity>;
  conflicts: SafetyConflictEntity[];
  events: RealtimeEvent[];
  metrics: Readonly<Record<string, number | string | boolean | null>>;
  intersectionMetrics: ReadonlyArray<
    Readonly<Record<string, number | string | boolean | null>>
  >;
};

export type DigitalTwinStream = {
  connection: DigitalTwinConnection;
  state: DigitalTwinState;
  issue: string | null;
};
