import * as THREE from "three";
import type {CoordinateService} from "../core/CoordinateService";
import type {TrafficLightEntity, VehicleEntity} from "../network/digitalTwinTypes";
import type {ControlCorridor, SceneLane, SceneTrafficLight} from "../scene/types";

export type AnalyticsLayerStats = {
  activeLanes: number;
  severeLanes: number;
  queuedVehicles: number;
  lineSegments: number;
  queueMarkers: number;
  greenWaveSegments: number;
  openGreenWindows: number;
};

type LaneAggregate = {
  speedTotal: number;
  vehicles: number;
  waiting: number;
};

const MAX_SEGMENTS = 3200;
const MAX_QUEUE_MARKERS = 240;

function congestionColor(averageSpeed: number, waiting: number): THREE.Color {
  if (averageSpeed < 2 || waiting >= 3) return new THREE.Color(0xff3b4e);
  if (averageSpeed < 5 || waiting >= 1) return new THREE.Color(0xff8b5c);
  if (averageSpeed < 8) return new THREE.Color(0xe8c95e);
  return new THREE.Color(0x36ddb2);
}

export class AnalyticsLayerManager {
  readonly root = new THREE.Group();
  readonly stats: AnalyticsLayerStats = {
    activeLanes: 0,
    severeLanes: 0,
    queuedVehicles: 0,
    lineSegments: 0,
    queueMarkers: 0,
    greenWaveSegments: 0,
    openGreenWindows: 0,
  };

  private readonly laneById: Map<string, SceneLane>;
  private readonly positions = new Float32Array(MAX_SEGMENTS * 2 * 3);
  private readonly colors = new Float32Array(MAX_SEGMENTS * 2 * 3);
  private readonly lineGeometry = new THREE.BufferGeometry();
  private readonly lineMaterial = new THREE.LineBasicMaterial({
    vertexColors: true,
    transparent: true,
    opacity: 0.82,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  });
  private readonly congestionLines: THREE.LineSegments;
  private readonly queueGeometry = new THREE.BoxGeometry(0.8, 1, 0.8);
  private readonly queueMaterial = new THREE.MeshBasicMaterial({
    color: 0xff6f4d,
    transparent: true,
    opacity: 0.68,
    depthWrite: false,
  });
  private readonly queueMarkers: THREE.InstancedMesh;
  private readonly greenWaveGeometry = new THREE.BufferGeometry();
  private readonly greenWaveMaterial = new THREE.LineBasicMaterial({
    color: 0x72ffe1,
    transparent: true,
    opacity: 0.72,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  });
  private readonly greenWaveLines: THREE.LineSegments;
  private readonly coreLaneIds = new Set<string>();
  private readonly tlsByLane = new Map<string, {tlsId: string; linkIndex: number}>();

  constructor(
    private readonly coordinates: CoordinateService,
    lanes: SceneLane[],
    trafficLights: SceneTrafficLight[] = [],
    corridors: ControlCorridor[] = [],
  ) {
    this.root.name = "AnalyticsLayerManager";
    this.laneById = new Map(lanes.map((lane) => [lane.sumoLaneId, lane]));
    const positionAttribute = new THREE.BufferAttribute(this.positions, 3);
    const colorAttribute = new THREE.BufferAttribute(this.colors, 3);
    positionAttribute.setUsage(THREE.DynamicDrawUsage);
    colorAttribute.setUsage(THREE.DynamicDrawUsage);
    this.lineGeometry.setAttribute("position", positionAttribute);
    this.lineGeometry.setAttribute("color", colorAttribute);
    this.lineGeometry.setDrawRange(0, 0);
    this.congestionLines = new THREE.LineSegments(this.lineGeometry, this.lineMaterial);
    this.congestionLines.name = "RealtimeLaneCongestion";
    this.congestionLines.frustumCulled = false;
    this.queueMarkers = new THREE.InstancedMesh(
      this.queueGeometry,
      this.queueMaterial,
      MAX_QUEUE_MARKERS,
    );
    this.queueMarkers.name = "RealtimeQueueMarkers";
    this.queueMarkers.count = 0;
    this.queueMarkers.frustumCulled = false;
    const corridorEdges = new Set(corridors.flatMap((corridor) => corridor.edgeIds));
    for (const lane of lanes) {
      if (corridorEdges.has(lane.sumoEdgeId)) this.coreLaneIds.add(lane.sumoLaneId);
    }
    for (const controller of trafficLights) {
      for (const link of controller.links) {
        if (!this.tlsByLane.has(link.fromLaneId)) {
          this.tlsByLane.set(link.fromLaneId, {
            tlsId: controller.sumoTlsId,
            linkIndex: link.linkIndex,
          });
        }
      }
    }
    this.greenWaveLines = new THREE.LineSegments(
      this.greenWaveGeometry,
      this.greenWaveMaterial,
    );
    this.greenWaveLines.name = "SUMOGreenWaveWindows";
    this.greenWaveLines.frustumCulled = false;
    this.root.add(this.congestionLines, this.queueMarkers, this.greenWaveLines);
  }

  applySnapshot(
    vehicles: ReadonlyMap<string, VehicleEntity>,
    trafficLights: ReadonlyMap<string, TrafficLightEntity> = new Map(),
  ): void {
    const byLane = new Map<string, LaneAggregate>();
    for (const vehicle of vehicles.values()) {
      if (!vehicle.laneId || !this.laneById.has(vehicle.laneId)) continue;
      const aggregate = byLane.get(vehicle.laneId) ?? {
        speedTotal: 0,
        vehicles: 0,
        waiting: 0,
      };
      aggregate.speedTotal += vehicle.speed;
      aggregate.vehicles += 1;
      if (vehicle.status === "waiting" || vehicle.speed < 0.5) aggregate.waiting += 1;
      byLane.set(vehicle.laneId, aggregate);
    }

    let segmentIndex = 0;
    let queueIndex = 0;
    let severeLanes = 0;
    let queuedVehicles = 0;
    const matrix = new THREE.Matrix4();
    const position = new THREE.Vector3();
    const scale = new THREE.Vector3();
    for (const [laneId, aggregate] of byLane) {
      const lane = this.laneById.get(laneId);
      if (!lane || lane.shape.length < 2) continue;
      const averageSpeed = aggregate.speedTotal / Math.max(aggregate.vehicles, 1);
      const color = congestionColor(averageSpeed, aggregate.waiting);
      if (averageSpeed < 2 || aggregate.waiting >= 3) severeLanes += 1;
      queuedVehicles += aggregate.waiting;
      for (let index = 1; index < lane.shape.length && segmentIndex < MAX_SEGMENTS; index += 1) {
        const from = lane.shape[index - 1];
        const to = lane.shape[index];
        if (!from || !to) continue;
        const dx = to.x - from.x;
        const dy = to.y - from.y;
        const length = Math.hypot(dx, dy);
        if (length < 0.01) continue;
        const normalX = -dy / length;
        const normalY = dx / length;
        // Three narrow parallel lines remain legible in a regional bird's-eye
        // view while still sharing one geometry/material draw call.
        for (const lateral of [-0.42, 0, 0.42]) {
          if (segmentIndex >= MAX_SEGMENTS) break;
          const worldFrom = this.coordinates.sumoToWorld(
            from.x + normalX * lateral,
            from.y + normalY * lateral,
            0.22,
          );
          const worldTo = this.coordinates.sumoToWorld(
            to.x + normalX * lateral,
            to.y + normalY * lateral,
            0.22,
          );
          const offset = segmentIndex * 6;
          this.positions.set(
            [worldFrom.x, worldFrom.y, worldFrom.z, worldTo.x, worldTo.y, worldTo.z],
            offset,
          );
          this.colors.set([color.r, color.g, color.b, color.r, color.g, color.b], offset);
          segmentIndex += 1;
        }
      }
      const laneEnd = lane.shape.at(-1);
      if (aggregate.waiting > 0 && laneEnd && queueIndex < MAX_QUEUE_MARKERS) {
        const world = this.coordinates.sumoToWorld(laneEnd.x, laneEnd.y);
        const height = Math.min(12, 0.8 + aggregate.waiting * 1.25);
        position.set(world.x, height / 2 + 0.24, world.z);
        scale.set(1, height, 1);
        matrix.compose(position, new THREE.Quaternion(), scale);
        this.queueMarkers.setMatrixAt(queueIndex, matrix);
        queueIndex += 1;
      }
    }
    this.lineGeometry.setDrawRange(0, segmentIndex * 2);
    this.lineGeometry.getAttribute("position").needsUpdate = true;
    this.lineGeometry.getAttribute("color").needsUpdate = true;
    this.queueMarkers.count = queueIndex;
    this.queueMarkers.instanceMatrix.needsUpdate = true;
    this.stats.activeLanes = byLane.size;
    this.stats.severeLanes = severeLanes;
    this.stats.queuedVehicles = queuedVehicles;
    this.stats.lineSegments = segmentIndex;
    this.stats.queueMarkers = queueIndex;
    const greenPositions: number[] = [];
    const openControllers = new Set<string>();
    for (const laneId of this.coreLaneIds) {
      const lane = this.laneById.get(laneId);
      const mapping = this.tlsByLane.get(laneId);
      const controller = mapping ? trafficLights.get(mapping.tlsId) : undefined;
      const state = mapping && controller ? controller.state[mapping.linkIndex] : undefined;
      if (!lane || (state !== "g" && state !== "G")) continue;
      if (mapping) openControllers.add(mapping.tlsId);
      for (let index = 1; index < lane.shape.length; index += 1) {
        const from = lane.shape[index - 1];
        const to = lane.shape[index];
        if (!from || !to) continue;
        const worldFrom = this.coordinates.sumoToWorld(from.x, from.y, 0.48);
        const worldTo = this.coordinates.sumoToWorld(to.x, to.y, 0.48);
        greenPositions.push(
          worldFrom.x,
          worldFrom.y,
          worldFrom.z,
          worldTo.x,
          worldTo.y,
          worldTo.z,
        );
      }
    }
    this.greenWaveGeometry.setAttribute(
      "position",
      new THREE.Float32BufferAttribute(greenPositions, 3),
    );
    this.stats.greenWaveSegments = greenPositions.length / 6;
    this.stats.openGreenWindows = openControllers.size;
  }

  setVisible(visible: boolean): void {
    this.root.visible = visible;
  }

  dispose(): void {
    this.root.removeFromParent();
    this.lineGeometry.dispose();
    this.lineMaterial.dispose();
    this.queueGeometry.dispose();
    this.queueMaterial.dispose();
    this.greenWaveGeometry.dispose();
    this.greenWaveMaterial.dispose();
    this.root.clear();
  }
}
