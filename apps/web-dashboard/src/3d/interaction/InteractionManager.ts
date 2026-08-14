import * as THREE from "three";
import type {CoordinateService} from "../core/CoordinateService";
import type {DigitalTwinState} from "../network/digitalTwinTypes";
import type {
  SceneJunction,
  SceneLane,
  StaticSceneDocument,
} from "../scene/types";

export type SelectableKind =
  | "vehicle"
  | "bicycle"
  | "pedestrian"
  | "trafficLight"
  | "roadsideDevice"
  | "event"
  | "conflict"
  | "junction"
  | "road";

export type SceneSelection = {
  kind: SelectableKind;
  id: string;
  title: string;
  subtitle: string;
  fields: Array<{label: string; value: string}>;
};

type InstanceEntity = {
  kind: SelectableKind;
  id: string;
  linkIndex?: number;
  laneId?: string;
  deviceType?: string;
};

type TaggedObject = THREE.Object3D & {
  userData: {
    entityKind?: SelectableKind;
    entityId?: string;
    instanceEntities?: InstanceEntity[];
  };
};

function display(value: unknown, suffix = ""): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") return `${Number.isInteger(value) ? value : value.toFixed(2)}${suffix}`;
  return `${String(value)}${suffix}`;
}

function distanceToSegment(
  point: {x: number; y: number},
  start: {x: number; y: number},
  end: {x: number; y: number},
): number {
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const lengthSquared = dx * dx + dy * dy;
  if (lengthSquared <= Number.EPSILON) return Math.hypot(point.x - start.x, point.y - start.y);
  const ratio = THREE.MathUtils.clamp(
    ((point.x - start.x) * dx + (point.y - start.y) * dy) / lengthSquared,
    0,
    1,
  );
  return Math.hypot(point.x - (start.x + ratio * dx), point.y - (start.y + ratio * dy));
}

export function distanceToLane(
  point: {x: number; y: number},
  lane: SceneLane,
): number {
  let nearest = Number.POSITIVE_INFINITY;
  for (let index = 1; index < lane.shape.length; index += 1) {
    const start = lane.shape[index - 1];
    const end = lane.shape[index];
    if (start && end) nearest = Math.min(nearest, distanceToSegment(point, start, end));
  }
  return nearest;
}

export function pointInJunction(
  point: {x: number; y: number},
  junction: SceneJunction,
): boolean {
  if (junction.shape.length < 3) {
    return Math.hypot(point.x - junction.position.x, point.y - junction.position.y) <= 8;
  }
  let inside = false;
  for (let current = 0, previous = junction.shape.length - 1; current < junction.shape.length; previous = current++) {
    const a = junction.shape[current];
    const b = junction.shape[previous];
    if (!a || !b) continue;
    const crosses =
      a.y > point.y !== b.y > point.y &&
      point.x < ((b.x - a.x) * (point.y - a.y)) / (b.y - a.y || Number.EPSILON) + a.x;
    if (crosses) inside = !inside;
  }
  return inside;
}

export class InteractionManager {
  private readonly raycaster = new THREE.Raycaster();
  private readonly pointer = new THREE.Vector2();
  private readonly ground = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
  private readonly worldPoint = new THREE.Vector3();
  private pointerDown: {x: number; y: number} | null = null;

  constructor(
    private readonly canvas: HTMLCanvasElement,
    private readonly camera: THREE.Camera,
    private readonly scene: THREE.Scene,
    private readonly coordinates: CoordinateService,
    private readonly document: StaticSceneDocument,
    private readonly state: () => DigitalTwinState,
    private readonly onSelection: (selection: SceneSelection | null) => void,
  ) {
    canvas.addEventListener("pointerdown", this.handlePointerDown);
    canvas.addEventListener("pointerup", this.handlePointerUp);
  }

  pick(clientX: number, clientY: number): SceneSelection | null {
    const bounds = this.canvas.getBoundingClientRect();
    if (!bounds.width || !bounds.height) return null;
    this.pointer.set(
      ((clientX - bounds.left) / bounds.width) * 2 - 1,
      -((clientY - bounds.top) / bounds.height) * 2 + 1,
    );
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const intersections = this.raycaster.intersectObjects(this.scene.children, true);
    for (const intersection of intersections) {
      const object = intersection.object as TaggedObject;
      const instance = object.userData.instanceEntities?.[intersection.instanceId ?? -1];
      if (instance) return this.describe(instance);
      let current: TaggedObject | null = object;
      while (current) {
        if (current.userData.entityKind && current.userData.entityId) {
          return this.describe({kind: current.userData.entityKind, id: current.userData.entityId});
        }
        current = current.parent as TaggedObject | null;
      }
    }
    if (!this.raycaster.ray.intersectPlane(this.ground, this.worldPoint)) return null;
    return this.describeStaticGround(
      this.coordinates.worldToSumo(this.worldPoint.x, this.worldPoint.z),
    );
  }

  dispose(): void {
    this.canvas.removeEventListener("pointerdown", this.handlePointerDown);
    this.canvas.removeEventListener("pointerup", this.handlePointerUp);
    this.pointerDown = null;
  }

  private readonly handlePointerDown = (event: PointerEvent): void => {
    this.pointerDown = {x: event.clientX, y: event.clientY};
  };

  private readonly handlePointerUp = (event: PointerEvent): void => {
    const start = this.pointerDown;
    this.pointerDown = null;
    if (!start || Math.hypot(event.clientX - start.x, event.clientY - start.y) > 5) return;
    this.onSelection(this.pick(event.clientX, event.clientY));
  };

  private describe(entity: InstanceEntity): SceneSelection | null {
    const current = this.state();
    if (entity.kind === "vehicle" || entity.kind === "bicycle") {
      const source = entity.kind === "vehicle"
        ? current.vehicles.get(entity.id)
        : current.bicycles.get(entity.id);
      if (!source) return null;
      return {
        kind: entity.kind,
        id: entity.id,
        title: entity.kind === "vehicle" ? `机动车 ${entity.id}` : `非机动车 ${entity.id}`,
        subtitle: `${source.type} · ${source.status}`,
        fields: [
          {label: "速度", value: display(source.speed, " m/s")},
          {label: "加速度", value: display(source.acceleration, " m/s²")},
          {label: "车道", value: display(source.laneId)},
          {label: "道路", value: display(source.edgeId)},
          {label: "路线", value: display(source.routeId)},
          {label: "信号/制动", value: `${source.signals} / ${source.brake ? "制动" : "正常"}`},
        ],
      };
    }
    if (entity.kind === "pedestrian") {
      const source = current.pedestrians.get(entity.id);
      if (!source) return null;
      return {
        kind: entity.kind,
        id: entity.id,
        title: `行人 ${entity.id}`,
        subtitle: `${source.type} · ${source.status}`,
        fields: [
          {label: "速度", value: display(source.speed, " m/s")},
          {label: "车道/步道", value: display(source.laneId)},
          {label: "道路", value: display(source.edgeId)},
          {label: "过街", value: display(source.crossingId)},
          {label: "等待区", value: display(source.waitingAreaId)},
        ],
      };
    }
    if (entity.kind === "trafficLight") {
      const source = current.trafficLights.get(entity.id);
      return {
        kind: entity.kind,
        id: entity.id,
        title: `信号控制器 ${entity.id}`,
        subtitle: entity.laneId ? `进口车道 ${entity.laneId}` : "SUMO TLS 真值",
        fields: [
          {label: "相位", value: display(source?.phaseIndex)},
          {label: "灯态串", value: display(source?.state)},
          {label: "剩余", value: display(source?.remainingS, " s")},
          {label: "控制链接", value: display(entity.linkIndex)},
        ],
      };
    }
    if (entity.kind === "roadsideDevice") {
      const device = this.document.roadsideDevices.find((item) => item.deviceId === entity.id);
      if (!device) return null;
      const current = this.state();
      const sumoBound = device.managedJunctions.some((id) => current.trafficLights.has(id));
      const transportOnline = current.metrics.cloud_online !== false && current.metrics.mqtt_online !== false;
      return {
        kind: entity.kind,
        id: entity.id,
        title: `${device.deviceType.toUpperCase()} ${device.deviceId}`,
        subtitle: device.provenance,
        fields: [
          {label: "状态", value: display(device.status)},
          {
            label: "仿真绑定",
            value: sumoBound ? (transportOnline ? "SUMO 在线" : "SUMO 在线/通信降级") : "等待 SUMO 状态",
          },
          {label: "管辖路口", value: device.managedJunctions.join(", ") || "—"},
          {label: "坐标", value: `${device.position.x.toFixed(1)}, ${device.position.y.toFixed(1)}`},
        ],
      };
    }
    if (entity.kind === "event") {
      return {
        kind: entity.kind,
        id: entity.id,
        title: `交通事件 ${entity.id}`,
        subtitle: entity.laneId ? `SUMO 车道 ${entity.laneId}` : "仿真事件真值",
        fields: [{label: "对象", value: entity.deviceType ?? "事件设施"}],
      };
    }
    if (entity.kind === "conflict") {
      const conflict = current.conflicts.find((item) => item.id === entity.id);
      if (!conflict) return null;
      return {
        kind: entity.kind,
        id: entity.id,
        title: `实测冲突 ${conflict.conflictType}`,
        subtitle: `${conflict.participantAId} × ${conflict.participantBId}`,
        fields: [
          {label: "严重度", value: display(conflict.severity)},
          {label: "TTC", value: display(conflict.ttcS, " s")},
          {label: "PET", value: display(conflict.petS, " s")},
          {label: "最小距离", value: display(conflict.minimumDistanceM, " m")},
          {label: "相对速度", value: display(conflict.relativeSpeedMS, " m/s")},
          {label: "SUMO 坐标", value: `${conflict.x.toFixed(1)}, ${conflict.y.toFixed(1)}`},
        ],
      };
    }
    return null;
  }

  private describeStaticGround(point: {x: number; y: number}): SceneSelection | null {
    const junction = this.document.junctions.find((item) => pointInJunction(point, item));
    if (junction) {
      return {
        kind: "junction",
        id: junction.sumoJunctionId,
        title: `路口 ${junction.displayId ?? junction.sumoJunctionId}`,
        subtitle: `SUMO ${junction.sumoJunctionId}`,
        fields: [
          {label: "类型", value: junction.junctionType},
          {label: "信控", value: junction.controlled ? "是" : "否"},
          {label: "角色", value: display(junction.role)},
          {label: "坐标", value: `${junction.position.x.toFixed(1)}, ${junction.position.y.toFixed(1)}`},
        ],
      };
    }
    let nearest: SceneLane | null = null;
    let nearestDistance = Number.POSITIVE_INFINITY;
    for (const lane of this.document.lanes) {
      const distance = distanceToLane(point, lane);
      if (distance < nearestDistance) {
        nearestDistance = distance;
        nearest = lane;
      }
    }
    if (!nearest || nearestDistance > Math.max(3, nearest.widthM / 2 + 1.2)) return null;
    return {
      kind: "road",
      id: nearest.sumoEdgeId,
      title: `道路 ${nearest.sumoEdgeId}`,
      subtitle: `车道 ${nearest.sumoLaneId}`,
      fields: [
        {label: "车道类型", value: nearest.laneKind},
        {label: "道路等级", value: nearest.edgeFunction},
        {label: "车道宽度", value: display(nearest.widthM, " m")},
        {label: "距中心线", value: display(nearestDistance, " m")},
      ],
    };
  }
}
