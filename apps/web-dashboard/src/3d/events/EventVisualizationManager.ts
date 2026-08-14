import * as THREE from "three";
import type {CoordinateService} from "../core/CoordinateService";
import type {RealtimeEvent, VehicleEntity} from "../network/digitalTwinTypes";
import type {SceneLane, SceneZone} from "../scene/types";

export type EventVisualizationStats = {
  activeRoadworks: number;
  activeIncidents: number;
  activeActivityZones: number;
  cones: number;
  barriers: number;
  incidentMarkers: number;
};

const MAX_CONES = 320;
const MAX_BARRIERS = 32;
const MAX_INCIDENTS = 32;
const MAX_ACTIVITY_ZONES = 8;

function disturbanceKey(event: RealtimeEvent): string {
  const identifier = event.payload.disturbance_id;
  return typeof identifier === "string" && identifier ? identifier : event.eventId;
}

function sampleLane(shape: SceneLane["shape"], spacingM: number): Array<{
  point: {x: number; y: number};
  tangent: {x: number; y: number};
}> {
  const result: Array<{
    point: {x: number; y: number};
    tangent: {x: number; y: number};
  }> = [];
  let carry = 0;
  for (let index = 1; index < shape.length; index += 1) {
    const start = shape[index - 1];
    const end = shape[index];
    if (!start || !end) continue;
    const dx = end.x - start.x;
    const dy = end.y - start.y;
    const length = Math.hypot(dx, dy);
    if (length < 0.01) continue;
    for (let distance = Math.max(0, spacingM - carry); distance <= length; distance += spacingM) {
      const ratio = distance / length;
      result.push({
        point: {x: start.x + dx * ratio, y: start.y + dy * ratio},
        tangent: {x: dx / length, y: dy / length},
      });
    }
    carry = (carry + length) % spacingM;
  }
  if (!result.length && shape.length >= 2) {
    const start = shape[0];
    const end = shape.at(-1);
    if (start && end) {
      const length = Math.hypot(end.x - start.x, end.y - start.y);
      if (length > 0.01) {
        result.push({
          point: {x: (start.x + end.x) / 2, y: (start.y + end.y) / 2},
          tangent: {x: (end.x - start.x) / length, y: (end.y - start.y) / length},
        });
      }
    }
  }
  return result;
}

export class EventVisualizationManager {
  readonly root = new THREE.Group();
  readonly stats: EventVisualizationStats = {
    activeRoadworks: 0,
    activeIncidents: 0,
    activeActivityZones: 0,
    cones: 0,
    barriers: 0,
    incidentMarkers: 0,
  };

  private readonly laneById: Map<string, SceneLane>;
  private readonly activeRoadworks = new Map<string, string>();
  private readonly activeIncidents = new Map<string, string>();
  private readonly activeActivityZones = new Map<string, string>();
  private readonly processedIds = new Set<string>();
  private readonly processedOrder: string[] = [];
  private readonly cones: THREE.InstancedMesh;
  private readonly barriers: THREE.InstancedMesh;
  private readonly incidentMarkers: THREE.InstancedMesh;
  private readonly activityZones: THREE.InstancedMesh;
  private readonly geometries: THREE.BufferGeometry[];
  private readonly materials: THREE.Material[];
  private readonly focus = new THREE.Vector3();
  private hasFocus = false;

  constructor(
    private readonly coordinates: CoordinateService,
    lanes: SceneLane[],
    private readonly zones: SceneZone[] = [],
  ) {
    this.root.name = "EventVisualizationManager";
    this.laneById = new Map(lanes.map((lane) => [lane.sumoLaneId, lane]));
    const coneGeometry = new THREE.ConeGeometry(0.24, 0.68, 8);
    const barrierGeometry = new THREE.BoxGeometry(2.2, 0.62, 0.24);
    const incidentGeometry = new THREE.OctahedronGeometry(0.62, 0);
    // A thin physical boundary keeps the activity area legible without laying
    // a large translucent plate over vehicles, lanes, or roadside facilities.
    const activityGeometry = new THREE.TorusGeometry(8.6, 0.12, 6, 48);
    const coneMaterial = new THREE.MeshStandardMaterial({
      color: 0xf16f22,
      emissive: 0x3d1303,
      emissiveIntensity: 0.35,
      roughness: 0.62,
    });
    const barrierMaterial = new THREE.MeshStandardMaterial({
      color: 0xf0e5cf,
      emissive: 0x44200b,
      emissiveIntensity: 0.15,
      roughness: 0.72,
    });
    const incidentMaterial = new THREE.MeshBasicMaterial({
      color: 0xff3048,
      toneMapped: false,
    });
    const activityMaterial = new THREE.MeshBasicMaterial({
      color: 0xffc857,
      transparent: true,
      opacity: 0.82,
      side: THREE.DoubleSide,
      depthWrite: false,
      toneMapped: false,
    });
    this.geometries = [coneGeometry, barrierGeometry, incidentGeometry, activityGeometry];
    this.materials = [coneMaterial, barrierMaterial, incidentMaterial, activityMaterial];
    this.cones = new THREE.InstancedMesh(coneGeometry, coneMaterial, MAX_CONES);
    this.barriers = new THREE.InstancedMesh(barrierGeometry, barrierMaterial, MAX_BARRIERS);
    this.incidentMarkers = new THREE.InstancedMesh(
      incidentGeometry,
      incidentMaterial,
      MAX_INCIDENTS,
    );
    this.activityZones = new THREE.InstancedMesh(
      activityGeometry,
      activityMaterial,
      MAX_ACTIVITY_ZONES,
    );
    this.cones.name = "RoadworkCones";
    this.barriers.name = "RoadworkBarriers";
    this.incidentMarkers.name = "IncidentMarkers";
    this.activityZones.name = "ActivityZoneMarkers";
    // These pools are tiny (384 instances maximum) and move between arbitrary
    // lanes. Disabling object-level frustum culling avoids stale instance bounds
    // across HMR/replay seeks while preserving camera frustum culling elsewhere.
    this.cones.frustumCulled = false;
    this.barriers.frustumCulled = false;
    this.incidentMarkers.frustumCulled = false;
    this.activityZones.frustumCulled = false;
    this.cones.count = 0;
    this.barriers.count = 0;
    this.incidentMarkers.count = 0;
    this.activityZones.count = 0;
    this.root.add(this.cones, this.barriers, this.incidentMarkers, this.activityZones);
  }

  applyEvents(
    events: RealtimeEvent[],
    vehicles: ReadonlyMap<string, VehicleEntity>,
    bicycles: ReadonlyMap<string, VehicleEntity> = new Map(),
  ): void {
    for (const event of events) {
      if (this.processedIds.has(event.eventId)) continue;
      this.remember(event.eventId);
      const key = disturbanceKey(event);
      if (event.event === "ROADWORK_LANE_CLOSED" && event.detail) {
        this.activeRoadworks.set(key, event.detail);
      } else if (event.event === "ROADWORK_LANE_REOPENED") {
        this.activeRoadworks.delete(key);
      } else if (event.event === "INCIDENT_VEHICLE_STOPPED" && event.detail) {
        this.activeIncidents.set(key, event.detail);
      } else if (
        event.event === "INCIDENT_CLEARED" ||
        event.event === "INCIDENT_STOP_CANCELLED" ||
        event.event === "INCIDENT_ALREADY_RELEASED"
      ) {
        this.activeIncidents.delete(key);
      } else if (
        event.event === "EVENT_DISPERSAL_STARTED" &&
        event.detail &&
        event.detail.toLowerCase().includes("activity")
      ) {
        this.activeActivityZones.set(key, event.detail);
      } else if (event.event === "EVENT_DISPERSAL_ENDED") {
        this.activeActivityZones.delete(key);
      }
    }
    this.rebuildInstances(vehicles, bicycles);
  }

  activeCount(): number {
    return this.activeRoadworks.size + this.activeIncidents.size + this.activeActivityZones.size;
  }

  focusPoint(): THREE.Vector3 | null {
    return this.hasFocus ? this.focus.clone() : null;
  }

  reset(): void {
    this.activeRoadworks.clear();
    this.activeIncidents.clear();
    this.activeActivityZones.clear();
    this.processedIds.clear();
    this.processedOrder.length = 0;
    this.rebuildInstances(new Map(), new Map());
  }

  dispose(): void {
    this.root.removeFromParent();
    this.geometries.forEach((geometry) => geometry.dispose());
    this.materials.forEach((material) => material.dispose());
    this.activeRoadworks.clear();
    this.activeIncidents.clear();
    this.activeActivityZones.clear();
    this.processedIds.clear();
    this.processedOrder.length = 0;
    this.root.clear();
  }

  private remember(eventId: string): void {
    this.processedIds.add(eventId);
    this.processedOrder.push(eventId);
    while (this.processedOrder.length > 256) {
      const removed = this.processedOrder.shift();
      if (removed) this.processedIds.delete(removed);
    }
  }

  private rebuildInstances(
    vehicles: ReadonlyMap<string, VehicleEntity>,
    bicycles: ReadonlyMap<string, VehicleEntity>,
  ): void {
    const matrix = new THREE.Matrix4();
    const quaternion = new THREE.Quaternion();
    let coneIndex = 0;
    let barrierIndex = 0;
    const coneEntities: Array<Record<string, unknown>> = [];
    const barrierEntities: Array<Record<string, unknown>> = [];
    this.hasFocus = false;
    const activeLaneIds = [...this.activeRoadworks.values()];
    const preferredLaneId = activeLaneIds.at(-1);
    for (const laneId of activeLaneIds) {
      const lane = this.laneById.get(laneId);
      if (!lane) continue;
      const points = sampleLane(lane.shape, 4.5).slice(0, 24);
      if (!this.hasFocus && laneId === preferredLaneId) {
        const midpoint = points[Math.floor(points.length / 2)];
        if (midpoint) {
          const world = this.coordinates.sumoToWorld(
            midpoint.point.x,
            midpoint.point.y,
            0.34,
          );
          this.focus.set(world.x, 0.6, world.z);
          this.hasFocus = true;
        }
      }
      for (const sample of points) {
        if (coneIndex >= MAX_CONES) break;
        const world = this.coordinates.sumoToWorld(sample.point.x, sample.point.y, 0.34);
        matrix.makeTranslation(world.x, world.y, world.z);
        this.cones.setMatrixAt(coneIndex, matrix);
        coneEntities.push({kind: "event", id: `roadwork:${laneId}`, laneId, deviceType: "cone"});
        coneIndex += 1;
      }
      const start = lane.shape[0];
      const next = lane.shape[1];
      if (start && next && barrierIndex < MAX_BARRIERS) {
        const world = this.coordinates.sumoToWorld(start.x, start.y, 0.42);
        const worldYaw = Math.atan2(next.x - start.x, next.y - start.y);
        quaternion.setFromAxisAngle(new THREE.Vector3(0, 1, 0), -worldYaw);
        matrix.compose(
          new THREE.Vector3(world.x, world.y, world.z),
          quaternion,
          new THREE.Vector3(Math.max(lane.widthM / 2.2, 1), 1, 1),
        );
        this.barriers.setMatrixAt(barrierIndex, matrix);
        barrierEntities.push({kind: "event", id: `roadwork:${laneId}`, laneId, deviceType: "barrier"});
        barrierIndex += 1;
      }
    }
    let incidentIndex = 0;
    const incidentEntities: Array<Record<string, unknown>> = [];
    for (const vehicleId of this.activeIncidents.values()) {
      const vehicle = vehicles.get(vehicleId) ?? bicycles.get(vehicleId);
      if (!vehicle || incidentIndex >= MAX_INCIDENTS) continue;
      const world = this.coordinates.sumoToWorld(vehicle.x, vehicle.y, 2.2);
      if (!this.hasFocus) {
        this.focus.set(world.x, 0.8, world.z);
        this.hasFocus = true;
      }
      matrix.makeTranslation(world.x, world.y, world.z);
      this.incidentMarkers.setMatrixAt(incidentIndex, matrix);
      incidentEntities.push({kind: "event", id: `incident:${vehicleId}`, deviceType: "incident_vehicle"});
      incidentIndex += 1;
    }
    this.cones.count = coneIndex;
    this.barriers.count = barrierIndex;
    this.incidentMarkers.count = incidentIndex;
    const activityEntities: Array<Record<string, unknown>> = [];
    const flat = new THREE.Quaternion().setFromAxisAngle(
      new THREE.Vector3(1, 0, 0),
      -Math.PI / 2,
    );
    let activityIndex = 0;
    const renderedTargets = new Set<string>();
    for (const [eventId, target] of this.activeActivityZones) {
      if (activityIndex >= MAX_ACTIVITY_ZONES) break;
      if (renderedTargets.has(target)) continue;
      const mappedZone = this.zoneForTarget(target);
      if (!mappedZone) continue;
      renderedTargets.add(target);
      const centroid = mappedZone.shape.reduce(
        (sum, point) => ({x: sum.x + point.x, y: sum.y + point.y}),
        {x: 0, y: 0},
      );
      const world = this.coordinates.sumoToWorld(
        centroid.x / mappedZone.shape.length,
        centroid.y / mappedZone.shape.length,
        0.22,
      );
      matrix.compose(
        new THREE.Vector3(world.x, world.y, world.z),
        flat,
        new THREE.Vector3(1, 1, 1),
      );
      this.activityZones.setMatrixAt(activityIndex, matrix);
      activityEntities.push({
        kind: "event",
        id: eventId,
        laneId: target,
        deviceType: `activity_zone:${mappedZone.sceneId}`,
      });
      if (!this.hasFocus) {
        this.focus.set(world.x, 0.8, world.z);
        this.hasFocus = true;
      }
      activityIndex += 1;
    }
    this.activityZones.count = activityIndex;
    this.cones.userData.instanceEntities = coneEntities;
    this.barriers.userData.instanceEntities = barrierEntities;
    this.incidentMarkers.userData.instanceEntities = incidentEntities;
    this.activityZones.userData.instanceEntities = activityEntities;
    this.cones.instanceMatrix.needsUpdate = true;
    this.barriers.instanceMatrix.needsUpdate = true;
    this.incidentMarkers.instanceMatrix.needsUpdate = true;
    this.activityZones.instanceMatrix.needsUpdate = true;
    // Instance matrices move after construction; invalidate the lazily cached
    // bounds or Three.js may frustum-cull active facilities at their old origin.
    this.cones.computeBoundingSphere();
    this.barriers.computeBoundingSphere();
    this.incidentMarkers.computeBoundingSphere();
    this.activityZones.computeBoundingSphere();
    this.stats.activeRoadworks = this.activeRoadworks.size;
    this.stats.activeIncidents = this.activeIncidents.size;
    this.stats.activeActivityZones = this.activeActivityZones.size;
    this.stats.cones = coneIndex;
    this.stats.barriers = barrierIndex;
    this.stats.incidentMarkers = incidentIndex;
  }

  private zoneForTarget(target: string): SceneZone | null {
    if (!this.zones.length) return null;
    if (target === "north_activity") {
      const exhibition = this.zones.find(
        (zone) =>
          zone.areaType === "exhibition_centre" ||
          zone.tags.amenity === "exhibition_centre",
      );
      if (exhibition) return exhibition;
      return this.zones.reduce((north, candidate) => {
        const meanY = (zone: SceneZone) =>
          zone.shape.reduce((sum, point) => sum + point.y, 0) / Math.max(zone.shape.length, 1);
        return meanY(candidate) > meanY(north) ? candidate : north;
      });
    }
    return this.zones.find((zone) => zone.sceneId === target || zone.sourceId === target) ?? null;
  }
}
