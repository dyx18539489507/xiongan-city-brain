import type {
  DigitalTwinDelta,
  DigitalTwinInit,
  DigitalTwinMessage,
  DigitalTwinState,
  EntityStateSet,
  PedestrianEntity,
  TrafficLightEntity,
  VehicleEntity,
} from "./digitalTwinTypes";

export class DigitalTwinProtocolError extends Error {}

export class DigitalTwinSequenceGapError extends DigitalTwinProtocolError {
  constructor(expected: number, received: number) {
    super(`digital-twin sequence gap: expected ${expected}, received ${received}`);
    this.name = "DigitalTwinSequenceGapError";
  }
}

export const emptyDigitalTwinState: DigitalTwinState = {
  initialized: false,
  sequence: -1,
  status: "idle",
  experimentId: null,
  scenarioId: null,
  simulationTimeS: 0,
  tickHz: 1,
  scene: null,
  vehicleTypes: [],
  vehicles: new Map(),
  bicycles: new Map(),
  pedestrians: new Map(),
  trafficLights: new Map(),
  conflicts: [],
  events: [],
  metrics: {},
  intersectionMetrics: [],
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requireNumber(record: Record<string, unknown>, key: string): number {
  const value = record[key];
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new DigitalTwinProtocolError(`${key} must be a finite number`);
  }
  return value;
}

function requireArray(record: Record<string, unknown>, key: string): unknown[] {
  const value = record[key];
  if (!Array.isArray(value)) {
    throw new DigitalTwinProtocolError(`${key} must be an array`);
  }
  return value;
}

function requireStateSet(value: unknown, key: string): EntityStateSet {
  if (!isRecord(value)) {
    throw new DigitalTwinProtocolError(`${key} must be an object`);
  }
  for (const collection of ["vehicles", "bicycles", "pedestrians"]) {
    const items = value[collection];
    if (!Array.isArray(items)) {
      throw new DigitalTwinProtocolError(`${key}.${collection} must be an array`);
    }
    if (items.some((item) => !isRecord(item) || typeof item.id !== "string")) {
      throw new DigitalTwinProtocolError(`${key}.${collection} contains an invalid entity`);
    }
  }
  return value as EntityStateSet;
}

export function parseDigitalTwinMessage(value: unknown): DigitalTwinMessage {
  if (!isRecord(value)) {
    throw new DigitalTwinProtocolError("digital-twin message must be an object");
  }
  if (value.protocolVersion !== "1.0") {
    throw new DigitalTwinProtocolError("unsupported digital-twin protocol version");
  }
  const sequence = requireNumber(value, "sequence");
  if (!Number.isInteger(sequence) || sequence < 0) {
    throw new DigitalTwinProtocolError("sequence must be a non-negative integer");
  }
  requireNumber(value, "simulationTimeS");
  requireArray(value, "trafficLights");
  if (value.conflicts !== undefined) {
    const conflicts = requireArray(value, "conflicts");
    if (conflicts.some((item) => !isRecord(item) || typeof item.id !== "string")) {
      throw new DigitalTwinProtocolError("conflicts contains an invalid entity");
    }
  }
  if (value.metrics !== undefined && !isRecord(value.metrics)) {
    throw new DigitalTwinProtocolError("metrics must be an object");
  }
  if (value.intersectionMetrics !== undefined && !Array.isArray(value.intersectionMetrics)) {
    throw new DigitalTwinProtocolError("intersectionMetrics must be an array");
  }
  if (value.type === "init") {
    requireStateSet(value.entities, "entities");
    requireNumber(value, "tickHz");
    if (!isRecord(value.scene) || typeof value.scenarioId !== "string") {
      throw new DigitalTwinProtocolError("init message is missing its scene reference");
    }
    if (value.activeEvents !== undefined && !Array.isArray(value.activeEvents)) {
      throw new DigitalTwinProtocolError("activeEvents must be an array");
    }
    return value as DigitalTwinInit;
  }
  if (value.type === "delta") {
    requireStateSet(value.spawn, "spawn");
    requireStateSet(value.update, "update");
    if (!isRecord(value.remove) || typeof value.experimentId !== "string") {
      throw new DigitalTwinProtocolError("delta message is missing removal or experiment state");
    }
    for (const collection of ["vehicles", "bicycles", "pedestrians"]) {
      if (!Array.isArray(value.remove[collection])) {
        throw new DigitalTwinProtocolError(`remove.${collection} must be an array`);
      }
    }
    requireArray(value, "events");
    return value as DigitalTwinDelta;
  }
  throw new DigitalTwinProtocolError("unknown digital-twin message type");
}

function mapById<Entity extends {id: string}>(items: Entity[]): Map<string, Entity> {
  return new Map(items.map((item) => [item.id, item]));
}

function applyCollection<Entity extends {id: string}>(
  previous: ReadonlyMap<string, Entity>,
  spawned: Entity[],
  updated: Entity[],
  removed: string[],
): Map<string, Entity> {
  const next = new Map(previous);
  for (const identifier of removed) next.delete(identifier);
  for (const item of spawned) next.set(item.id, item);
  for (const item of updated) next.set(item.id, item);
  return next;
}

function applyInit(message: DigitalTwinInit): DigitalTwinState {
  return {
    initialized: true,
    sequence: message.sequence,
    status: message.status,
    experimentId: message.experimentId,
    scenarioId: message.scenarioId,
    simulationTimeS: message.simulationTimeS,
    tickHz: message.tickHz,
    scene: message.scene,
    vehicleTypes: message.vehicleTypes,
    vehicles: mapById<VehicleEntity>(message.entities.vehicles),
    bicycles: mapById<VehicleEntity>(message.entities.bicycles),
    pedestrians: mapById<PedestrianEntity>(message.entities.pedestrians),
    trafficLights: mapById<TrafficLightEntity>(message.trafficLights),
    conflicts: message.conflicts ?? [],
    events: message.activeEvents ?? [],
    metrics: message.metrics ?? {},
    intersectionMetrics: message.intersectionMetrics ?? [],
  };
}

export function applyDigitalTwinMessage(
  previous: DigitalTwinState,
  message: DigitalTwinMessage,
): DigitalTwinState {
  if (message.type === "init") return applyInit(message);
  if (!previous.initialized) {
    throw new DigitalTwinProtocolError("delta received before initialization");
  }
  if (message.sequence <= previous.sequence) return previous;
  if (message.sequence !== previous.sequence + 1) {
    throw new DigitalTwinSequenceGapError(previous.sequence + 1, message.sequence);
  }
  if (previous.experimentId !== null && previous.experimentId !== message.experimentId) {
    throw new DigitalTwinProtocolError("experiment changed without a new initialization snapshot");
  }
  const trafficLights = new Map(previous.trafficLights);
  for (const item of message.trafficLights) trafficLights.set(item.id, item);
  return {
    ...previous,
    sequence: message.sequence,
    status: "running",
    experimentId: message.experimentId,
    simulationTimeS: message.simulationTimeS,
    vehicles: applyCollection(
      previous.vehicles,
      message.spawn.vehicles,
      message.update.vehicles,
      message.remove.vehicles,
    ),
    bicycles: applyCollection(
      previous.bicycles,
      message.spawn.bicycles,
      message.update.bicycles,
      message.remove.bicycles,
    ),
    pedestrians: applyCollection(
      previous.pedestrians,
      message.spawn.pedestrians,
      message.update.pedestrians,
      message.remove.pedestrians,
    ),
    trafficLights,
    conflicts: message.conflicts ?? [],
    events: [...previous.events, ...message.events].slice(-60),
    metrics: message.metrics ?? previous.metrics,
    intersectionMetrics: message.intersectionMetrics ?? previous.intersectionMetrics,
  };
}
