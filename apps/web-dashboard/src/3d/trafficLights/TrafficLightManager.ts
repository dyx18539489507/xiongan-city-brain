import * as THREE from "three";
import type {CoordinateService} from "../core/CoordinateService";
import type {TrafficLightEntity} from "../network/digitalTwinTypes";
import type {
  SceneLane,
  SceneTrafficLight,
  StaticSceneDocument,
} from "../scene/types";

type SignalPlacement = {
  tlsId: string;
  linkIndex: number;
  fromLaneId: string;
  position: THREE.Vector3;
  yaw: number;
  pedestrian: boolean;
  bicycle: boolean;
  aspect: SignalAspect;
};

export type SignalAspect = "left" | "straight" | "right" | "pedestrian" | "bicycle";

export type TrafficLightStats = {
  controllers: number;
  mappedLinks: number;
  physicalPoles: number;
  missingLanes: number;
  directionalHeads: number;
  pedestrianHeads: number;
  bicycleHeads: number;
};

const RED_ON = new THREE.Color(0xff382f);
const RED_OFF = new THREE.Color(0x260806);
const YELLOW_ON = new THREE.Color(0xffc400);
const YELLOW_OFF = new THREE.Color(0x211800);
const GREEN_ON = new THREE.Color(0x20ee8a);
const GREEN_OFF = new THREE.Color(0x052417);

function laneDirection(lane: SceneLane): {x: number; z: number; yaw: number} | null {
  const end = lane.shape.at(-1);
  const previous = lane.shape.at(-2);
  if (!end || !previous) return null;
  const x = end.x - previous.x;
  const z = previous.y - end.y;
  const length = Math.hypot(x, z);
  if (length < 0.01) return null;
  return {x: x / length, z: z / length, yaw: Math.atan2(x, z)};
}

function laneStartDirection(lane: SceneLane): {x: number; z: number} | null {
  const start = lane.shape[0];
  const next = lane.shape[1];
  if (!start || !next) return null;
  const x = next.x - start.x;
  const z = start.y - next.y;
  const length = Math.hypot(x, z);
  return length < 0.01 ? null : {x: x / length, z: z / length};
}

export function classifySignalAspect(lane: SceneLane, toLane?: SceneLane): SignalAspect {
  const kind = lane.laneKind.toLowerCase();
  if (kind.includes("pedestrian")) return "pedestrian";
  if (kind.includes("bicycle") || kind.includes("cycle")) return "bicycle";
  const incoming = laneDirection(lane);
  const outgoing = toLane ? laneStartDirection(toLane) : null;
  if (!incoming || !outgoing) return "straight";
  const dot = incoming.x * outgoing.x + incoming.z * outgoing.z;
  if (dot > 0.65) return "straight";
  const crossY = incoming.z * outgoing.x - incoming.x * outgoing.z;
  if (crossY > 0.15) return "left";
  if (crossY < -0.15) return "right";
  return "straight";
}

function circleShape(x: number, y: number, radius: number, holeRadius = 0): THREE.Shape {
  const shape = new THREE.Shape();
  shape.absarc(x, y, radius, 0, Math.PI * 2, false);
  if (holeRadius > 0) {
    const hole = new THREE.Path();
    hole.absarc(x, y, holeRadius, 0, Math.PI * 2, true);
    shape.holes.push(hole);
  }
  return shape;
}

function polygonShape(points: Array<[number, number]>): THREE.Shape {
  const shape = new THREE.Shape();
  const [first, ...rest] = points;
  if (!first) return shape;
  shape.moveTo(first[0], first[1]);
  rest.forEach(([x, y]) => shape.lineTo(x, y));
  shape.closePath();
  return shape;
}

function createSignalIconGeometry(aspect: SignalAspect): THREE.ShapeGeometry {
  let shapes: THREE.Shape[];
  if (aspect === "pedestrian") {
    shapes = [
      circleShape(0, 0.09, 0.032),
      polygonShape([[-0.022, 0.052], [0.022, 0.052], [0.03, -0.02], [-0.03, -0.02]]),
      polygonShape([[-0.02, 0.03], [-0.085, -0.02], [-0.07, -0.04], [0, 0.005]]),
      polygonShape([[0.02, 0.03], [0.085, -0.02], [0.07, -0.04], [0, 0.005]]),
      polygonShape([[-0.02, -0.01], [-0.085, -0.105], [-0.055, -0.12], [0.005, -0.035]]),
      polygonShape([[0.02, -0.01], [0.085, -0.105], [0.055, -0.12], [-0.005, -0.035]]),
    ];
  } else if (aspect === "bicycle") {
    shapes = [
      circleShape(-0.072, -0.045, 0.054, 0.037),
      circleShape(0.072, -0.045, 0.054, 0.037),
      polygonShape([[-0.07, -0.045], [-0.018, 0.03], [0.035, -0.045], [0.002, -0.045], [-0.02, -0.005], [-0.048, -0.045]]),
      polygonShape([[-0.018, 0.03], [0.05, 0.04], [0.045, 0.055], [-0.03, 0.047]]),
    ];
  } else {
    shapes = [polygonShape([
      [-0.035, -0.12],
      [0.035, -0.12],
      [0.035, 0.025],
      [0.095, 0.025],
      [0, 0.125],
      [-0.095, 0.025],
      [-0.035, 0.025],
    ])];
  }
  const geometry = new THREE.ShapeGeometry(shapes, 2);
  if (aspect === "left") geometry.rotateZ(Math.PI / 2);
  if (aspect === "right") geometry.rotateZ(-Math.PI / 2);
  return geometry;
}

export function buildSignalPlacements(
  coordinateService: CoordinateService,
  trafficLights: SceneTrafficLight[],
  lanes: SceneLane[],
): {placements: SignalPlacement[]; missingLanes: number; poleKeys: Set<string>} {
  const laneById = new Map(lanes.map((lane) => [lane.sumoLaneId, lane]));
  const placements: SignalPlacement[] = [];
  const poleKeys = new Set<string>();
  let missingLanes = 0;

  for (const controller of trafficLights) {
    const linksByLane = new Map<string, typeof controller.links>();
    for (const link of controller.links) {
      const group = linksByLane.get(link.fromLaneId) ?? [];
      group.push(link);
      linksByLane.set(link.fromLaneId, group);
    }
    for (const [laneId, links] of linksByLane) {
      const lane = laneById.get(laneId);
      const direction = lane ? laneDirection(lane) : null;
      const end = lane?.shape.at(-1);
      if (!lane || !direction || !end) {
        missingLanes += links.length;
        continue;
      }
      const world = coordinateService.sumoToWorld(end.x, end.y, 0);
      const laneKind = lane.laneKind.toLowerCase();
      const pedestrian = laneKind.includes("pedestrian");
      const bicycle = laneKind.includes("bicycle") || laneKind.includes("cycle");
      const lowHead = pedestrian || bicycle;
      const roadsideOffset = lowHead ? 0.65 : lane.widthM / 2 + 1.05;
      const poleX = world.x + direction.z * roadsideOffset;
      const poleZ = world.z - direction.x * roadsideOffset;
      poleKeys.add(`${controller.sumoTlsId}:${laneId}`);

      const sorted = [...links].sort((a, b) => a.linkIndex - b.linkIndex);
      sorted.forEach((link, order) => {
        const lateralHeadOffset = (order - (sorted.length - 1) / 2) * (lowHead ? 0.38 : 0.62);
        const aspect = classifySignalAspect(lane, laneById.get(link.toLaneId));
        placements.push({
          tlsId: controller.sumoTlsId,
          linkIndex: link.linkIndex,
          fromLaneId: laneId,
          position: new THREE.Vector3(
            poleX + direction.z * lateralHeadOffset,
            lowHead ? 2.35 : 4.8,
            poleZ - direction.x * lateralHeadOffset,
          ),
          yaw: direction.yaw,
          pedestrian,
          bicycle,
          aspect,
        });
      });
    }
  }
  return {placements, missingLanes, poleKeys};
}

export class TrafficLightManager {
  readonly root = new THREE.Group();
  readonly stats: TrafficLightStats;

  private readonly placements: SignalPlacement[];
  private readonly red: THREE.InstancedMesh;
  private readonly yellow: THREE.InstancedMesh;
  private readonly green: THREE.InstancedMesh;
  private readonly materials: THREE.Material[] = [];
  private readonly geometries: THREE.BufferGeometry[] = [];

  constructor(
    coordinateService: CoordinateService,
    document: StaticSceneDocument,
  ) {
    this.root.name = "TrafficLightManager";
    const built = buildSignalPlacements(
      coordinateService,
      document.trafficLights,
      document.lanes,
    );
    this.placements = built.placements;
    this.stats = {
      controllers: document.trafficLights.length,
      mappedLinks: built.placements.length,
      physicalPoles: built.poleKeys.size,
      missingLanes: built.missingLanes,
      directionalHeads: built.placements.filter((placement) =>
        placement.aspect === "left" || placement.aspect === "straight" || placement.aspect === "right"
      ).length,
      pedestrianHeads: built.placements.filter((placement) => placement.aspect === "pedestrian").length,
      bicycleHeads: built.placements.filter((placement) => placement.aspect === "bicycle").length,
    };

    const poleGeometry = new THREE.CylinderGeometry(0.075, 0.1, 4.8, 8);
    const housingGeometry = new THREE.BoxGeometry(0.48, 1.28, 0.3);
    const lensGeometry = new THREE.CircleGeometry(0.18, 12);
    this.geometries.push(poleGeometry, housingGeometry, lensGeometry);

    const poleMaterial = new THREE.MeshStandardMaterial({color: 0x30393b, roughness: 0.62});
    const housingMaterial = new THREE.MeshStandardMaterial({color: 0x111719, roughness: 0.52});
    const redMaterial = new THREE.MeshBasicMaterial({
      color: 0xffffff,
      side: THREE.DoubleSide,
      toneMapped: false,
    });
    const yellowMaterial = new THREE.MeshBasicMaterial({
      color: 0xffffff,
      side: THREE.DoubleSide,
      toneMapped: false,
    });
    const greenMaterial = new THREE.MeshBasicMaterial({
      color: 0xffffff,
      side: THREE.DoubleSide,
      toneMapped: false,
    });
    const iconMaterial = new THREE.MeshBasicMaterial({
      color: 0x020405,
      transparent: true,
      opacity: 0.82,
      depthWrite: false,
      side: THREE.DoubleSide,
      toneMapped: false,
    });
    this.materials.push(
      poleMaterial,
      housingMaterial,
      redMaterial,
      yellowMaterial,
      greenMaterial,
      iconMaterial,
    );

    const polePositions = new Map<string, SignalPlacement>();
    for (const placement of this.placements) {
      const key = `${placement.tlsId}:${placement.fromLaneId}`;
      if (!polePositions.has(key)) polePositions.set(key, placement);
    }
    const poleMesh = new THREE.InstancedMesh(poleGeometry, poleMaterial, polePositions.size);
    poleMesh.name = "TrafficSignalPoles";
    const matrix = new THREE.Matrix4();
    let poleIndex = 0;
    for (const placement of polePositions.values()) {
      const height = placement.pedestrian || placement.bicycle ? 2.45 : 4.8;
      matrix.compose(
        new THREE.Vector3(placement.position.x, height / 2, placement.position.z),
        new THREE.Quaternion(),
        new THREE.Vector3(1, height / 4.8, 1),
      );
      poleMesh.setMatrixAt(poleIndex, matrix);
      poleIndex += 1;
    }
    poleMesh.instanceMatrix.needsUpdate = true;

    const housingMesh = new THREE.InstancedMesh(
      housingGeometry,
      housingMaterial,
      this.placements.length,
    );
    housingMesh.name = "TrafficSignalHousings";
    this.red = new THREE.InstancedMesh(lensGeometry, redMaterial, this.placements.length);
    this.yellow = new THREE.InstancedMesh(lensGeometry, yellowMaterial, this.placements.length);
    this.green = new THREE.InstancedMesh(lensGeometry, greenMaterial, this.placements.length);
    this.red.name = "TrafficSignalRedLenses";
    this.yellow.name = "TrafficSignalYellowLenses";
    this.green.name = "TrafficSignalGreenLenses";
    const instanceEntities = this.placements.map((placement) => ({
      kind: "trafficLight",
      id: placement.tlsId,
      linkIndex: placement.linkIndex,
      laneId: placement.fromLaneId,
    }));
    housingMesh.userData.instanceEntities = instanceEntities;
    this.red.userData.instanceEntities = instanceEntities;
    this.yellow.userData.instanceEntities = instanceEntities;
    this.green.userData.instanceEntities = instanceEntities;

    const rotation = new THREE.Quaternion();
    const scale = new THREE.Vector3();
    const position = new THREE.Vector3();
    this.placements.forEach((placement, index) => {
      rotation.setFromAxisAngle(new THREE.Vector3(0, 1, 0), placement.yaw + Math.PI);
      const lowHead = placement.pedestrian || placement.bicycle;
      scale.set(lowHead ? 0.68 : 1, lowHead ? 0.68 : 1, 1);
      matrix.compose(placement.position, rotation, scale);
      housingMesh.setMatrixAt(index, matrix);
      const lensOffset = lowHead ? 0.28 : 0.36;
      const forwardX = Math.sin(placement.yaw) * 0.17;
      const forwardZ = Math.cos(placement.yaw) * 0.17;
      ([lensOffset, 0, -lensOffset] as const).forEach((verticalOffset, lightIndex) => {
        position.set(
          placement.position.x - forwardX,
          placement.position.y + verticalOffset,
          placement.position.z - forwardZ,
        );
        const lensScale = lowHead && lightIndex === 1 ? new THREE.Vector3(0, 0, 0) : scale;
        matrix.compose(position, rotation, lensScale);
        [this.red, this.yellow, this.green][lightIndex]?.setMatrixAt(index, matrix);
      });
      this.red.setColorAt(index, RED_OFF);
      this.yellow.setColorAt(index, YELLOW_OFF);
      this.green.setColorAt(index, GREEN_OFF);
    });
    housingMesh.instanceMatrix.needsUpdate = true;
    for (const mesh of [this.red, this.yellow, this.green]) {
      mesh.instanceMatrix.needsUpdate = true;
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    }
    const iconMeshes: THREE.InstancedMesh[] = [];
    const iconGroups: Array<{
      name: string;
      aspects: SignalAspect[];
      geometryAspect: SignalAspect;
    }> = [
      {name: "directional", aspects: ["left", "straight", "right"], geometryAspect: "straight"},
      {name: "pedestrian", aspects: ["pedestrian"], geometryAspect: "pedestrian"},
      {name: "bicycle", aspects: ["bicycle"], geometryAspect: "bicycle"},
    ];
    const iconRoll = new THREE.Quaternion();
    for (const group of iconGroups) {
      const matching = this.placements.filter((placement) =>
        group.aspects.includes(placement.aspect)
      );
      if (!matching.length) continue;
      const iconGeometry = createSignalIconGeometry(group.geometryAspect);
      this.geometries.push(iconGeometry);
      const repeat = group.name === "pedestrian" || group.name === "bicycle" ? 2 : 1;
      const iconMesh = new THREE.InstancedMesh(iconGeometry, iconMaterial, matching.length * repeat);
      iconMesh.name = `TrafficSignalIcon_${group.name}`;
      const iconEntities: Array<Record<string, unknown>> = [];
      let iconIndex = 0;
      for (const placement of matching) {
        const lowHead = placement.pedestrian || placement.bicycle;
        const lensOffset = lowHead ? 0.28 : 0.36;
        const offsets = repeat === 2 ? [lensOffset, -lensOffset] : [-lensOffset];
        rotation.setFromAxisAngle(new THREE.Vector3(0, 1, 0), placement.yaw + Math.PI);
        const roll = placement.aspect === "left"
          ? Math.PI / 2
          : placement.aspect === "right"
            ? -Math.PI / 2
            : 0;
        iconRoll.setFromAxisAngle(new THREE.Vector3(0, 0, 1), roll);
        rotation.multiply(iconRoll);
        scale.set(lowHead ? 0.68 : 1, lowHead ? 0.68 : 1, 1);
        const forwardX = Math.sin(placement.yaw) * 0.181;
        const forwardZ = Math.cos(placement.yaw) * 0.181;
        for (const verticalOffset of offsets) {
          position.set(
            placement.position.x - forwardX,
            placement.position.y + verticalOffset,
            placement.position.z - forwardZ,
          );
          matrix.compose(position, rotation, scale);
          iconMesh.setMatrixAt(iconIndex, matrix);
          iconEntities.push({
            kind: "trafficLight",
            id: placement.tlsId,
            linkIndex: placement.linkIndex,
            laneId: placement.fromLaneId,
          });
          iconIndex += 1;
        }
      }
      iconMesh.userData.instanceEntities = iconEntities;
      iconMesh.instanceMatrix.needsUpdate = true;
      iconMeshes.push(iconMesh);
    }
    this.root.add(poleMesh, housingMesh, this.red, this.yellow, this.green, ...iconMeshes);
  }

  applySnapshot(trafficLights: ReadonlyMap<string, TrafficLightEntity>): void {
    this.placements.forEach((placement, index) => {
      const state = trafficLights.get(placement.tlsId)?.state[placement.linkIndex] ?? "o";
      this.red.setColorAt(index, state === "r" || state === "R" ? RED_ON : RED_OFF);
      this.yellow.setColorAt(index, state === "y" || state === "Y" ? YELLOW_ON : YELLOW_OFF);
      this.green.setColorAt(index, state === "g" || state === "G" ? GREEN_ON : GREEN_OFF);
    });
    for (const mesh of [this.red, this.yellow, this.green]) {
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    }
  }

  dispose(): void {
    this.root.removeFromParent();
    this.geometries.forEach((geometry) => geometry.dispose());
    this.materials.forEach((material) => material.dispose());
    this.root.clear();
  }
}
