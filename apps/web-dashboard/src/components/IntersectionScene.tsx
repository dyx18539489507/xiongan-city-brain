import {useEffect, useMemo, useRef, useState} from "react";
import * as THREE from "three";
import {OrbitControls} from "three/addons/controls/OrbitControls.js";
import type {IntersectionNode, IntersectionRealtime} from "../types";
import {CoordinateService} from "../3d/core/CoordinateService";
import {loadStaticScene} from "../3d/network/SceneLoader";
import {
  RoadGeometryBuilder,
  type RoadBuildStage,
  type RoadBuildStats,
} from "../3d/network/RoadGeometryBuilder";
import {disposeObject} from "../3d/network/geometry";
import {MaterialManager} from "../3d/scene/MaterialManager";
import type {StaticSceneDocument} from "../3d/scene/types";
import type {DigitalTwinStream} from "../3d/network/digitalTwinTypes";
import {VehicleManager} from "../3d/vehicles/VehicleManager";
import {
  emptyPerformanceSnapshot,
  PerformanceMonitor,
  type PerformanceSnapshot,
} from "../3d/performance/PerformanceMonitor";
import {TrafficLightManager} from "../3d/trafficLights/TrafficLightManager";
import {BuildingManager} from "../3d/environment/BuildingManager";
import {HeroContextManager} from "../3d/environment/HeroContextManager";
import {VegetationManager} from "../3d/environment/VegetationManager";
import {StreetFurnitureManager} from "../3d/environment/StreetFurnitureManager";
import {BicycleManager} from "../3d/bicycles/BicycleManager";
import {PedestrianManager} from "../3d/pedestrians/PedestrianManager";
import {EventVisualizationManager} from "../3d/events/EventVisualizationManager";
import {LightingManager} from "../3d/environment/LightingManager";
import {WeatherManager, type WeatherMode} from "../3d/environment/WeatherManager";
import {
  AnalyticsLayerManager,
  type AnalyticsLayerStats,
} from "../3d/analytics/AnalyticsLayerManager";
import {ConflictAreaManager} from "../3d/analytics/ConflictAreaManager";
import {
  RoadsideDeviceManager,
  type RoadsideDeviceStats,
} from "../3d/roadside/RoadsideDeviceManager";
import {
  QualityManager,
  targetFrameRate,
  type QualitySnapshot,
} from "../3d/performance/QualityManager";
import {CameraManager} from "../3d/camera/CameraManager";
import {LODManager, type StaticLODSnapshot} from "../3d/performance/LODManager";
import {ShadowBudgetManager} from "../3d/performance/ShadowBudgetManager";
import {
  TextureManager,
  type TextureBudgetSnapshot,
} from "../3d/assets/TextureManager";
import {
  DemoDirector,
  type DemoSnapshot,
  type DemoTimeline,
} from "../3d/camera/DemoDirector";
import {
  InteractionManager,
  type SceneSelection,
} from "../3d/interaction/InteractionManager";
import cameraPresetConfig from "../3d/camera/camera_presets.json";
import demoTimelineConfig from "../3d/camera/demo_timeline.json";
import lodConfig from "../3d/performance/lod_config.json";

type ViewMode =
  | "overview"
  | "corridor"
  | "urban"
  | "vehicles"
  | "multimodal"
  | "pedestrians"
  | "events"
  | "rsu"
  | "monitor"
  | "driver"
  | "cruise"
  | "junction";
type AssetState = "loading" | "ready" | "error";
type DisplayMode = "real" | "analysis";

type IntersectionSceneProps = {
  scenarioId: string;
  digitalTwin: DigitalTwinStream;
  node: IntersectionNode | null;
  realtime: IntersectionRealtime | null;
  simulationTime?: number;
  status: string;
  websocketOnline: boolean;
  sourceMode: "live" | "replay";
};

type CameraController = {
  setView: (view: ViewMode, junctionId: string | null) => void;
  resetPerformance: () => void;
};

type SceneSummary = {
  junctions: number;
  lanes: number;
  crossings: number;
  trafficLights: number;
  triangles: number;
  stopLines: number;
  drawObjects: number;
  buildings: number;
  trees: number;
  streetLights: number;
  roadsideDevices: number;
};

const defaultSummary: SceneSummary = {
  junctions: 0,
  lanes: 0,
  crossings: 0,
  trafficLights: 0,
  triangles: 0,
  stopLines: 0,
  drawObjects: 0,
  buildings: 0,
  trees: 0,
  streetLights: 0,
  roadsideDevices: 0,
};

const stageLabels: Record<RoadBuildStage, string> = {
  junctions: "构建 SUMO 路口面",
  lanes: "合批构建道路与车道",
  crossings: "构建人行横道",
  markings: "构建边界线与停止线",
};

const cameraPresets = new Map(
  cameraPresetConfig.presets.map((preset) => [preset.id, preset]),
);

const initialDemoSnapshot: DemoSnapshot = {
  running: false,
  elapsedS: 0,
  durationS: demoTimelineConfig.durationS,
  cueIndex: -1,
  label: "待机",
};

function formatCount(value: number): string {
  return new Intl.NumberFormat("zh-CN").format(value);
}

function nextPaint(): Promise<void> {
  return new Promise((resolve) => window.requestAnimationFrame(() => resolve()));
}

function triangleCount(stats: RoadBuildStats): number {
  return (
    stats.laneTriangles +
    stats.junctionTriangles +
    stats.crossingTriangles +
    stats.markingTriangles
  );
}

export function IntersectionScene({
  scenarioId,
  digitalTwin,
  node,
  realtime,
  simulationTime,
  status,
  websocketOnline,
  sourceMode,
}: IntersectionSceneProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const controllerRef = useRef<CameraController | null>(null);
  const vehicleManagerRef = useRef<VehicleManager | null>(null);
  const trafficLightManagerRef = useRef<TrafficLightManager | null>(null);
  const bicycleManagerRef = useRef<BicycleManager | null>(null);
  const pedestrianManagerRef = useRef<PedestrianManager | null>(null);
  const eventVisualizationManagerRef = useRef<EventVisualizationManager | null>(null);
  const weatherManagerRef = useRef<WeatherManager | null>(null);
  const analyticsLayerManagerRef = useRef<AnalyticsLayerManager | null>(null);
  const conflictAreaManagerRef = useRef<ConflictAreaManager | null>(null);
  const roadsideDeviceManagerRef = useRef<RoadsideDeviceManager | null>(null);
  const demoDirectorRef = useRef<DemoDirector | null>(null);
  const shadowBudgetManagerRef = useRef<ShadowBudgetManager | null>(null);
  const analysisModeRef = useRef<DisplayMode>("real");
  const eventExperimentRef = useRef<string | null>(null);
  const digitalTwinStateRef = useRef(digitalTwin.state);
  const [view, setView] = useState<ViewMode>("overview");
  const [weatherMode] = useState<WeatherMode>("clear");
  const [displayMode, setDisplayMode] = useState<DisplayMode>("real");
  const [assetState, setAssetState] = useState<AssetState>("loading");
  const [assetMessage, setAssetMessage] = useState("下载统一场景数据");
  const [summary, setSummary] = useState<SceneSummary>(defaultSummary);
  const [renderedVehicles, setRenderedVehicles] = useState(0);
  const [mappedSignals, setMappedSignals] = useState(0);
  const [renderedBicycles, setRenderedBicycles] = useState(0);
  const [renderedPedestrians, setRenderedPedestrians] = useState(0);
  const [activeEventVisuals, setActiveEventVisuals] = useState(0);
  const [eventInstanceCounts, setEventInstanceCounts] = useState({cones: 0, barriers: 0});
  const [analyticsStats, setAnalyticsStats] = useState<AnalyticsLayerStats>({
    activeLanes: 0,
    severeLanes: 0,
    queuedVehicles: 0,
    lineSegments: 0,
    queueMarkers: 0,
    greenWaveSegments: 0,
    openGreenWindows: 0,
  });
  const [deviceStats, setDeviceStats] = useState<RoadsideDeviceStats>({
    devices: 0,
    rsus: 0,
    cameras: 0,
    runtimeBound: 0,
    drawObjects: 0,
    triangles: 0,
  });
  const [renderPerformance, setRenderPerformance] = useState<PerformanceSnapshot>(
    emptyPerformanceSnapshot,
  );
  const [quality, setQuality] = useState<QualitySnapshot>({
    level: "native",
    renderScale: 1,
    pixelRatio: 1,
  });
  const [demo, setDemo] = useState<DemoSnapshot>(initialDemoSnapshot);
  const [sceneSelection, setSceneSelection] = useState<SceneSelection | null>(null);
  const [staticLod, setStaticLod] = useState<StaticLODSnapshot>({
    tier: "near",
    managedObjects: 0,
    hiddenObjects: 0,
  });
  const [textureBudget, setTextureBudget] = useState<TextureBudgetSnapshot>({
    textures: 0,
    estimatedBytes: 0,
    budgetBytes: 192 * 1024 * 1024,
    withinBudget: true,
  });
  const hasRealtimeMetrics = realtime !== null;
  const entityStreamOnline = digitalTwin.connection === "online";
  const entityCount =
    digitalTwin.state.vehicles.size +
    digitalTwin.state.bicycles.size +
    digitalTwin.state.pedestrians.size;
  digitalTwinStateRef.current = digitalTwin.state;
  analysisModeRef.current = displayMode;

  useEffect(() => {
    const manager = vehicleManagerRef.current;
    const nowMs = performance.now();
    if (manager) {
      manager.applySnapshot(
        digitalTwin.state.vehicles,
        digitalTwin.state.tickHz,
        nowMs,
      );
      setRenderedVehicles(manager.count());
      const shadowManager = shadowBudgetManagerRef.current;
      if (shadowManager) shadowManager.capture(manager.root);
    }
    const bicycleManager = bicycleManagerRef.current;
    if (bicycleManager) {
      bicycleManager.applySnapshot(
        digitalTwin.state.bicycles,
        digitalTwin.state.tickHz,
        nowMs,
      );
      setRenderedBicycles(bicycleManager.count());
    }
    const pedestrianManager = pedestrianManagerRef.current;
    if (pedestrianManager) {
      pedestrianManager.applySnapshot(
        digitalTwin.state.pedestrians,
        digitalTwin.state.tickHz,
        nowMs,
      );
      setRenderedPedestrians(pedestrianManager.count());
    }
    trafficLightManagerRef.current?.applySnapshot(digitalTwin.state.trafficLights);
    const roadsideManager = roadsideDeviceManagerRef.current;
    if (roadsideManager) {
      roadsideManager.applyRuntimeState(
        digitalTwin.state.trafficLights,
        digitalTwin.state.metrics,
      );
      setDeviceStats({...roadsideManager.stats});
    }
    const eventManager = eventVisualizationManagerRef.current;
    if (eventManager) {
      if (eventExperimentRef.current !== digitalTwin.state.experimentId) {
        eventManager.reset();
        eventExperimentRef.current = digitalTwin.state.experimentId;
      }
      eventManager.applyEvents(
        digitalTwin.state.events,
        digitalTwin.state.vehicles,
        digitalTwin.state.bicycles,
      );
      setActiveEventVisuals(eventManager.activeCount());
      setEventInstanceCounts({
        cones: eventManager.stats.cones,
        barriers: eventManager.stats.barriers,
      });
    }
    const analyticsManager = analyticsLayerManagerRef.current;
    if (analyticsManager) {
      analyticsManager.applySnapshot(
        digitalTwin.state.vehicles,
        digitalTwin.state.trafficLights,
      );
      setAnalyticsStats({...analyticsManager.stats});
    }
    conflictAreaManagerRef.current?.applySnapshot(digitalTwin.state.conflicts);
  }, [digitalTwin.state.sequence, digitalTwin.state]);

  useEffect(() => {
    controllerRef.current?.resetPerformance();
    controllerRef.current?.setView(view, node?.intersection_id ?? null);
  }, [node?.intersection_id, view]);

  useEffect(() => {
    controllerRef.current?.resetPerformance();
    weatherManagerRef.current?.apply(weatherMode);
  }, [weatherMode]);

  useEffect(() => {
    analyticsLayerManagerRef.current?.setVisible(displayMode === "analysis");
    conflictAreaManagerRef.current?.setVisible(displayMode === "analysis");
    roadsideDeviceManagerRef.current?.setAnalysisVisible(displayMode === "analysis");
  }, [displayMode]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const stage = stageRef.current;
    if (!canvas || !stage) return;

    const abortController = new AbortController();
    let cancelled = false;
    let frameId = 0;
    let renderRoot: THREE.Group | null = null;
    let coordinateService: CoordinateService | null = null;
    let materialManager: MaterialManager | null = null;
    let vehicleManager: VehicleManager | null = null;
    let trafficLightManager: TrafficLightManager | null = null;
    let buildingManager: BuildingManager | null = null;
    let heroContextManager: HeroContextManager | null = null;
    let vegetationManager: VegetationManager | null = null;
    let streetFurnitureManager: StreetFurnitureManager | null = null;
    let bicycleManager: BicycleManager | null = null;
    let pedestrianManager: PedestrianManager | null = null;
    let eventVisualizationManager: EventVisualizationManager | null = null;
    let lightingManager: LightingManager | null = null;
    let weatherManager: WeatherManager | null = null;
    let analyticsLayerManager: AnalyticsLayerManager | null = null;
    let conflictAreaManager: ConflictAreaManager | null = null;
    let roadsideDeviceManager: RoadsideDeviceManager | null = null;
    let interactionManager: InteractionManager | null = null;
    let lodManager: LODManager | null = null;
    let shadowBudgetManager: ShadowBudgetManager | null = null;
    let textureManager: TextureManager | null = null;
    let loadedScene: StaticSceneDocument | null = null;
    const performanceMonitor = new PerformanceMonitor();
    const junctionWorld = new Map<string, THREE.Vector3>();
    const desiredPosition = new THREE.Vector3(0, 1800, 1800);
    const desiredTarget = new THREE.Vector3();

    const renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: false,
      powerPreference: "high-performance",
    });
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 0.92;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFShadowMap;
    const qualityManager = new QualityManager(renderer, window.devicePixelRatio, 1.25);
    setQuality(qualityManager.snapshot());

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(43, 1, 1, 10_000);
    camera.position.copy(desiredPosition);
    lightingManager = new LightingManager(scene, renderer);
    weatherManager = new WeatherManager(scene, lightingManager);
    weatherManagerRef.current = weatherManager;
    weatherManager.apply(weatherMode);

    const controls = new OrbitControls(camera, canvas);
    controls.enableDamping = true;
    controls.dampingFactor = 0.075;
    controls.zoomSpeed = 0.65;
    controls.target.copy(desiredTarget);
    controls.minDistance = 10;
    controls.maxDistance = 6200;
    controls.maxPolarAngle = Math.PI * 0.485;
    const cameraManager = new CameraManager(camera, controls);
    let lastCameraMotionMs = Number.NEGATIVE_INFINITY;
    const handleControlStart = () => cameraManager.cancel();
    const handleCameraMotion = () => {
      lastCameraMotionMs = performance.now();
      lodManager?.notifyCameraMotion(lastCameraMotionMs);
    };
    controls.addEventListener("start", handleControlStart);
    controls.addEventListener("change", handleCameraMotion);

    const placeCamera = (nextView: ViewMode, junctionId: string | null) => {
      if (!loadedScene || !coordinateService) return;
      const heroActive = nextView === "junction" && junctionId === "11122023451";
      if (!heroActive && buildingManager) buildingManager.root.visible = true;
      if (heroContextManager) {
        void heroContextManager.setActive(heroActive).then((visible) => {
          if (!cancelled && buildingManager && heroActive) {
            buildingManager.root.visible = !visible;
          }
        });
      }
      const bounds = loadedScene.coordinateSystem.sceneBounds;
      const minimum = coordinateService.sumoToWorld(bounds.minX, bounds.minY);
      const maximum = coordinateService.sumoToWorld(bounds.maxX, bounds.maxY);
      const width = Math.abs(maximum.x - minimum.x);
      const depth = Math.abs(maximum.z - minimum.z);
      const extent = Math.max(width, depth);
      let target = new THREE.Vector3((minimum.x + maximum.x) / 2, 0, (minimum.z + maximum.z) / 2);
      let distance = extent;

      if (nextView === "corridor") {
        const corridorIds = loadedScene.controlCorridors[0]?.junctionIds ?? [];
        const points = corridorIds.map((id) => junctionWorld.get(id)).filter((item) => item !== undefined);
        if (points.length) {
          const box = new THREE.Box3().setFromPoints(points);
          target = box.getCenter(new THREE.Vector3());
          distance = Math.max(box.getSize(new THREE.Vector3()).length(), 480);
        }
      } else if (nextView === "urban") {
        const buildingCenters = loadedScene.buildings
          .filter((building) => building.footprint.length >= 3)
          .map((building) => {
            const sum = building.footprint.reduce(
              (current, point) => ({x: current.x + point.x, y: current.y + point.y}),
              {x: 0, y: 0},
            );
            const world = coordinateService?.sumoToWorld(
              sum.x / building.footprint.length,
              sum.y / building.footprint.length,
            );
            return new THREE.Vector3(world?.x ?? 0, 8, world?.z ?? 0);
          });
        if (buildingCenters.length) {
          const allCenter = new THREE.Box3()
            .setFromPoints(buildingCenters)
            .getCenter(new THREE.Vector3());
          const anchor = buildingCenters.reduce((nearest, point) =>
            point.distanceToSquared(allCenter) < nearest.distanceToSquared(allCenter)
              ? point
              : nearest,
          );
          const nearby = buildingCenters.filter((point) => point.distanceTo(anchor) < 260);
          const box = new THREE.Box3().setFromPoints(nearby.length ? nearby : [anchor]);
          target = box.getCenter(new THREE.Vector3());
          distance = Math.max(box.getSize(new THREE.Vector3()).length() * 0.58, 145);
        }
      } else if (nextView === "vehicles") {
        const vehiclePoints = [...digitalTwinStateRef.current.vehicles.values()].map((vehicle) => {
          const world = coordinateService?.sumoToWorld(vehicle.x, vehicle.y, 1.2);
          return new THREE.Vector3(world?.x ?? 0, world?.y ?? 1.2, world?.z ?? 0);
        });
        if (vehiclePoints.length) {
          const box = new THREE.Box3().setFromPoints(vehiclePoints);
          const fleetCenter = box.getCenter(new THREE.Vector3());
          target = vehiclePoints.reduce((nearest, point) =>
            point.distanceToSquared(fleetCenter) < nearest.distanceToSquared(fleetCenter)
              ? point
              : nearest,
          );
          distance = 36;
        }
      } else if (nextView === "multimodal") {
        const sceneBounds = loadedScene.coordinateSystem.sceneBounds;
        const inside = (entity: {x: number; y: number}) =>
          entity.x >= sceneBounds.minX - 80 && entity.x <= sceneBounds.maxX + 80 &&
          entity.y >= sceneBounds.minY - 80 && entity.y <= sceneBounds.maxY + 80;
        const bicycles = [...digitalTwinStateRef.current.bicycles.values()]
          .filter(inside)
          .map((entity) => {
            const world = coordinateService!.sumoToWorld(entity.x, entity.y, 0.8);
            return new THREE.Vector3(world.x, world.y, world.z);
          });
        const bicycle = bicycles[0];
        if (bicycle) {
          target = new THREE.Vector3(bicycle.x, bicycle.y, bicycle.z);
          distance = 18;
        }
      } else if (nextView === "pedestrians") {
        const pedestrian = [...digitalTwinStateRef.current.pedestrians.values()].find((entity) => {
          const sceneBounds = loadedScene?.coordinateSystem.sceneBounds;
          return sceneBounds &&
            entity.x >= sceneBounds.minX - 80 && entity.x <= sceneBounds.maxX + 80 &&
            entity.y >= sceneBounds.minY - 80 && entity.y <= sceneBounds.maxY + 80;
        });
        if (pedestrian) {
          const world = coordinateService.sumoToWorld(pedestrian.x, pedestrian.y, 0.85);
          target = new THREE.Vector3(world.x, world.y, world.z);
          distance = 16;
        }
      } else if (nextView === "events") {
        const eventPoint = eventVisualizationManagerRef.current?.focusPoint();
        if (eventPoint) {
          target = eventPoint;
          // Event acceptance is a facility-level close-up: at the former
          // corridor distance real 0.68 m cones were technically rendered but
          // not visually distinguishable at 720p.
          distance = 18;
        }
      } else if (nextView === "rsu" || nextView === "monitor") {
        const wantedType = nextView === "rsu" ? "rsu" : "camera";
        const device = loadedScene.roadsideDevices.find(
          (item) => item.deviceType === wantedType,
        );
        const managed = device?.managedJunctions[0];
        const managedPoint = managed ? junctionWorld.get(managed) : undefined;
        if (device) {
          const world = coordinateService.sumoToWorld(
            device.position.x,
            device.position.y,
            nextView === "rsu" ? 4.5 : 5.05,
          );
          target = managedPoint?.clone() ?? new THREE.Vector3(world.x + 16, 0, world.z);
          desiredTarget.copy(target);
          desiredPosition.set(world.x, world.y, world.z);
          cameraManager.transitionTo({
            position: desiredPosition.toArray() as [number, number, number],
            target: desiredTarget.toArray() as [number, number, number],
            fov: nextView === "monitor" ? 58 : 48,
            transitionDuration: 900,
          });
          return;
        }
      } else if (nextView === "driver") {
        const vehicle = [...digitalTwinStateRef.current.vehicles.values()][0];
        if (vehicle) {
          const world = coordinateService.sumoToWorld(vehicle.x, vehicle.y, 1.55);
          const yaw = coordinateService.sumoAngleToThree(vehicle.angle);
          const forward = new THREE.Vector3(Math.sin(yaw), 0, Math.cos(yaw));
          desiredPosition.set(world.x, world.y, world.z).addScaledVector(forward, 1.4);
          desiredTarget.copy(desiredPosition).addScaledVector(forward, 22);
          cameraManager.transitionTo({
            position: desiredPosition.toArray() as [number, number, number],
            target: desiredTarget.toArray() as [number, number, number],
            fov: 62,
            transitionDuration: 700,
          });
          return;
        }
      } else if (nextView === "cruise") {
        const corridorIds = loadedScene.controlCorridors[0]?.junctionIds ?? [];
        const points = corridorIds
          .map((id) => junctionWorld.get(id))
          .filter((item): item is THREE.Vector3 => item !== undefined);
        if (points.length) {
          const box = new THREE.Box3().setFromPoints(points);
          target = box.getCenter(new THREE.Vector3());
          distance = Math.max(260, box.getSize(new THREE.Vector3()).length() * 0.42);
        }
      } else if (nextView === "junction" && junctionId) {
        const point = junctionWorld.get(junctionId);
        if (point) {
          target = point.clone();
          distance = 88;
        }
      }

      desiredTarget.copy(target);
      if (
        nextView === "junction" ||
        nextView === "vehicles" ||
        nextView === "multimodal" ||
        nextView === "pedestrians" ||
        nextView === "events" ||
        nextView === "cruise"
      ) {
        desiredPosition.set(target.x + distance * 0.62, distance * 0.72, target.z + distance * 0.78);
      } else if (nextView === "urban") {
        desiredPosition.set(target.x + distance * 0.72, distance * 0.58, target.z + distance * 0.82);
      } else if (nextView === "overview") {
        desiredPosition.set(target.x + distance * 0.08, distance * 0.78, target.z + distance * 0.44);
      } else {
        desiredPosition.set(target.x + distance * 0.14, distance * 0.76, target.z + distance * 0.62);
      }
      const presetId = nextView === "junction"
        ? "hero-k06"
        : nextView === "corridor"
          ? "corridor"
          : nextView === "overview"
            ? "overview"
            : null;
      const preset = presetId ? cameraPresets.get(presetId) : undefined;
      cameraManager.transitionTo({
        position: desiredPosition.toArray() as [number, number, number],
        target: desiredTarget.toArray() as [number, number, number],
        fov: preset?.fov ?? 43,
        transitionDuration: preset?.transitionDuration ?? 1100,
      });
    };
    controllerRef.current = {
      setView: placeCamera,
      resetPerformance: () => {
        performanceMonitor.reset();
        setRenderPerformance(emptyPerformanceSnapshot());
      },
    };
    const demoDirector = new DemoDirector(
      demoTimelineConfig as DemoTimeline,
      (cue) => {
        setView(cue.view);
        if (cue.displayMode) setDisplayMode(cue.displayMode);
        placeCamera(cue.view, cue.junctionId ?? null);
      },
    );
    demoDirectorRef.current = demoDirector;
    let lastDemoSecond = -1;
    let lastDemoCue = -1;
    let lastDemoRunning = false;

    const resize = () => {
      const {clientWidth, clientHeight} = stage;
      qualityManager.applyViewport(clientWidth, clientHeight);
      camera.aspect = clientWidth / Math.max(clientHeight, 1);
      camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(stage);
    resize();

    const load = async () => {
      try {
        const document = await loadStaticScene(
          scenarioId,
          abortController.signal,
          (progress) => {
            if (cancelled) return;
            if (progress.stage === "download") {
              const percent = progress.totalBytes
                ? ` ${Math.min(100, Math.round((progress.loadedBytes / progress.totalBytes) * 100))}%`
                : "";
              setAssetMessage(`下载统一场景数据${percent}`);
            } else if (progress.stage === "parse") {
              setAssetMessage("解析 scene.json 与 ID 映射");
            }
          },
        );
        if (cancelled) return;
        loadedScene = document;
        coordinateService = new CoordinateService(document.coordinateSystem);
        for (const junction of document.junctions) {
          const world = coordinateService.sumoToWorld(junction.position.x, junction.position.y, 0.08);
          junctionWorld.set(junction.sumoJunctionId, new THREE.Vector3(world.x, world.y, world.z));
        }

        materialManager = new MaterialManager();
        setAssetMessage("加载并验证 KTX2 路面纹理");
        await materialManager.prepareCompressedTextures(renderer);
        if (cancelled) {
          materialManager.dispose();
          materialManager = null;
          return;
        }
        const materials = materialManager;
        const bounds = document.coordinateSystem.sceneBounds;
        const center = coordinateService.sumoToWorld(
          (bounds.minX + bounds.maxX) / 2,
          (bounds.minY + bounds.maxY) / 2,
          -0.08,
        );
        const groundGeometry = new THREE.PlaneGeometry(
          bounds.maxX - bounds.minX + 500,
          bounds.maxY - bounds.minY + 500,
        );
        groundGeometry.rotateX(-Math.PI / 2);
        const ground = new THREE.Mesh(groundGeometry, materials.ground());
        ground.name = "SceneGround";
        ground.receiveShadow = true;
        ground.position.set(center.x, center.y, center.z);
        scene.add(ground);

        const builder = new RoadGeometryBuilder(coordinateService, materials);
        const result = await builder.buildStaged(document, nextPaint, (buildStage) => {
          if (!cancelled) setAssetMessage(stageLabels[buildStage]);
        });
        if (cancelled) {
          disposeObject(result.root);
          return;
        }
        renderRoot = result.root;
        renderRoot.traverse((object) => {
          if (object instanceof THREE.Mesh) object.receiveShadow = true;
        });
        scene.add(renderRoot);
        setAssetMessage("构建 OSM 建筑体量");
        buildingManager = new BuildingManager(coordinateService, document.buildings);
        scene.add(buildingManager.root);
        const heroJunction = document.junctions.find(
          (junction) => junction.sumoJunctionId === "11122023451",
        );
        if (heroJunction) {
          heroContextManager = new HeroContextManager(
            coordinateService,
            renderer,
            heroJunction,
          );
          scene.add(heroContextManager.root);
        }
        setAssetMessage("实例化 OSM 绿地与树木");
        vegetationManager = new VegetationManager(
          coordinateService,
          document.vegetation,
          document.lanes,
        );
        scene.add(vegetationManager.root);
        setAssetMessage("实例化道路照明设施");
        streetFurnitureManager = new StreetFurnitureManager(
          coordinateService,
          document.lanes,
        );
        scene.add(streetFurnitureManager.root);
        setAssetMessage("实例化 RSU 与路侧摄像头");
        roadsideDeviceManager = new RoadsideDeviceManager(
          coordinateService,
          document.roadsideDevices,
          document.junctions,
        );
        roadsideDeviceManager.setAnalysisVisible(analysisModeRef.current === "analysis");
        roadsideDeviceManagerRef.current = roadsideDeviceManager;
        scene.add(roadsideDeviceManager.root);
        roadsideDeviceManager.applyRuntimeState(
          digitalTwinStateRef.current.trafficLights,
          digitalTwinStateRef.current.metrics,
        );
        setDeviceStats({...roadsideDeviceManager.stats});
        setAssetMessage("初始化非机动车与行人对象池");
        bicycleManager = new BicycleManager(
          coordinateService,
          document.coordinateSystem.sceneBounds,
        );
        pedestrianManager = new PedestrianManager(
          coordinateService,
          document.coordinateSystem.sceneBounds,
        );
        scene.add(bicycleManager.root, pedestrianManager.root);
        bicycleManagerRef.current = bicycleManager;
        pedestrianManagerRef.current = pedestrianManager;
        const currentDynamicState = digitalTwinStateRef.current;
        bicycleManager.applySnapshot(
          currentDynamicState.bicycles,
          currentDynamicState.tickHz,
          performance.now(),
        );
        pedestrianManager.applySnapshot(
          currentDynamicState.pedestrians,
          currentDynamicState.tickHz,
          performance.now(),
        );
        setRenderedBicycles(bicycleManager.count());
        setRenderedPedestrians(pedestrianManager.count());
        eventVisualizationManager = new EventVisualizationManager(
          coordinateService,
          document.lanes,
          document.zones,
        );
        scene.add(eventVisualizationManager.root);
        eventVisualizationManagerRef.current = eventVisualizationManager;
        eventExperimentRef.current = currentDynamicState.experimentId;
        eventVisualizationManager.applyEvents(
          currentDynamicState.events,
          currentDynamicState.vehicles,
          currentDynamicState.bicycles,
        );
        setActiveEventVisuals(eventVisualizationManager.activeCount());
        setEventInstanceCounts({
          cones: eventVisualizationManager.stats.cones,
          barriers: eventVisualizationManager.stats.barriers,
        });
        setAssetMessage("构建逐进口道信号灯映射");
        trafficLightManager = new TrafficLightManager(coordinateService, document);
        scene.add(trafficLightManager.root);
        trafficLightManagerRef.current = trafficLightManager;
        trafficLightManager.applySnapshot(digitalTwinStateRef.current.trafficLights);
        setMappedSignals(trafficLightManager.stats.mappedLinks);
        setAssetMessage("加载共享车辆模型与对象池");
        vehicleManager = new VehicleManager(
          coordinateService,
          document.coordinateSystem.sceneBounds,
          renderer,
        );
        await vehicleManager.initialize();
        if (cancelled) {
          vehicleManager.dispose();
          vehicleManager = null;
          return;
        }
        scene.add(vehicleManager.root);
        vehicleManagerRef.current = vehicleManager;
        const currentEntityState = digitalTwinStateRef.current;
        vehicleManager.applySnapshot(
          currentEntityState.vehicles,
          currentEntityState.tickHz,
          performance.now(),
        );
        setRenderedVehicles(vehicleManager.count());
        shadowBudgetManager = new ShadowBudgetManager(8, 80, 15);
        shadowBudgetManager.capture(vehicleManager.root);
        shadowBudgetManagerRef.current = shadowBudgetManager;
        analyticsLayerManager = new AnalyticsLayerManager(
          coordinateService,
          document.lanes,
          document.trafficLights,
          document.controlCorridors,
        );
        analyticsLayerManager.applySnapshot(
          currentEntityState.vehicles,
          currentEntityState.trafficLights,
        );
        analyticsLayerManager.setVisible(analysisModeRef.current === "analysis");
        analyticsLayerManagerRef.current = analyticsLayerManager;
        scene.add(analyticsLayerManager.root);
        setAnalyticsStats({...analyticsLayerManager.stats});
        conflictAreaManager = new ConflictAreaManager(coordinateService);
        conflictAreaManager.applySnapshot(currentEntityState.conflicts);
        conflictAreaManager.setVisible(analysisModeRef.current === "analysis");
        conflictAreaManagerRef.current = conflictAreaManager;
        scene.add(conflictAreaManager.root);
        lodManager = new LODManager(lodConfig);
        lodManager.capture(scene);
        // Establish the initial tier immediately; later changes wait for camera settle.
        lodManager.update(camera, performance.now(), true);
        setStaticLod(lodManager.snapshot());
        textureManager = new TextureManager();
        textureManager.capture(scene);
        setTextureBudget(textureManager.snapshot());
        interactionManager = new InteractionManager(
          canvas,
          camera,
          scene,
          coordinateService,
          document,
          () => digitalTwinStateRef.current,
          setSceneSelection,
        );
        weatherManager?.captureMaterials(scene);
        setSummary({
          junctions: document.metadata.counts.junctions ?? document.junctions.length,
          lanes: document.metadata.counts.lanes ?? document.lanes.length,
          crossings: document.metadata.counts.crossings ?? document.crossings.length,
          trafficLights: document.metadata.counts.trafficLights ?? 0,
          triangles:
            triangleCount(result.stats) +
            buildingManager.stats.triangles +
            vegetationManager.stats.triangles +
            streetFurnitureManager.stats.triangles +
            roadsideDeviceManager.stats.triangles,
          stopLines: result.stats.stopLines,
          drawObjects:
            result.stats.drawObjects +
            6 +
            buildingManager.stats.drawObjects +
            vegetationManager.stats.drawObjects +
            streetFurnitureManager.stats.drawObjects +
            roadsideDeviceManager.stats.drawObjects,
          buildings: buildingManager.stats.renderedBuildings,
          trees: vegetationManager.stats.trees,
          streetLights: streetFurnitureManager.stats.streetLights,
          roadsideDevices: roadsideDeviceManager.stats.devices,
        });
        placeCamera("overview", null);
        setAssetMessage(`${document.junctions.length} 个 SUMO 路口静态拓扑已载入`);
        setAssetState("ready");
      } catch (error: unknown) {
        if (cancelled || (error instanceof DOMException && error.name === "AbortError")) return;
        console.error("3D scene load failed", error);
        setAssetMessage(error instanceof Error ? error.message : "场景加载失败");
        setAssetState("error");
      }
    };
    void load();

    let lastRender = 0;
    let lastSubmittedFrame = 0;
    let cameraMotionActive = false;
    const render = (frameTime: number) => {
      const renderIntervalMs = 1_000 / targetFrameRate(qualityManager.snapshot().level);
      const elapsed = frameTime - lastRender;
      if (elapsed >= renderIntervalMs - 1) {
        // Never submit a catch-up burst after a throttled/background frame.
        // A hard 30 FPS ceiling is more stable on MX250 and keeps measured FPS
        // from being inflated by two renders in adjacent rAF callbacks.
        lastRender = frameTime;
        const submittedDelta = lastSubmittedFrame > 0
          ? Math.min(frameTime - lastSubmittedFrame, 1000)
          : renderIntervalMs;
        lastSubmittedFrame = frameTime;
        cameraManager.update(submittedDelta);
        const nextDemo = demoDirector.update(submittedDelta / 1000);
        const nextDemoSecond = Math.floor(nextDemo.elapsedS);
        if (
          nextDemoSecond !== lastDemoSecond ||
          nextDemo.cueIndex !== lastDemoCue ||
          nextDemo.running !== lastDemoRunning
        ) {
          lastDemoSecond = nextDemoSecond;
          lastDemoCue = nextDemo.cueIndex;
          lastDemoRunning = nextDemo.running;
          setDemo({...nextDemo});
        }
        controls.update();
        const cameraIsMoving = frameTime - lastCameraMotionMs < lodConfig.settleDelayMs;
        if (cameraMotionActive && !cameraIsMoving) performanceMonitor.reset();
        cameraMotionActive = cameraIsMoving;
        vehicleManager?.update(frameTime, camera);
        bicycleManager?.update(frameTime, camera);
        pedestrianManager?.update(frameTime, camera);
        weatherManager?.update(submittedDelta / 1000, camera);
        if (lodManager?.update(camera, frameTime)) setStaticLod(lodManager.snapshot());
        shadowBudgetManager?.setEnabled(qualityManager.snapshot().level === "native");
        shadowBudgetManager?.update(camera);
        renderer.render(scene, camera);
        const performanceSnapshot = performanceMonitor.record(frameTime, renderer.info);
        if (performanceSnapshot) {
          setRenderPerformance(performanceSnapshot);
          if (
            !cameraIsMoving &&
            qualityManager.observe(
              performanceSnapshot.averageFps,
              performanceSnapshot.p1Fps,
              performanceSnapshot.maxFrameTimeMs,
              (vehicleManager?.count() ?? 0) +
                (bicycleManager?.count() ?? 0) +
                (pedestrianManager?.count() ?? 0),
            )
          ) {
            performanceMonitor.reset();
            resize();
            setQuality(qualityManager.snapshot());
          }
        }
      }
      frameId = window.requestAnimationFrame(render);
    };
    frameId = window.requestAnimationFrame(render);

    return () => {
      cancelled = true;
      abortController.abort();
      window.cancelAnimationFrame(frameId);
      observer.disconnect();
      controls.removeEventListener("start", handleControlStart);
      controls.removeEventListener("change", handleCameraMotion);
      controls.dispose();
      interactionManager?.dispose();
      interactionManager = null;
      vehicleManagerRef.current = null;
      trafficLightManagerRef.current = null;
      bicycleManagerRef.current = null;
      pedestrianManagerRef.current = null;
      eventVisualizationManagerRef.current = null;
      weatherManagerRef.current = null;
      analyticsLayerManagerRef.current = null;
      conflictAreaManagerRef.current = null;
      roadsideDeviceManagerRef.current = null;
      demoDirectorRef.current = null;
      shadowBudgetManagerRef.current = null;
      vehicleManager?.dispose();
      vehicleManager = null;
      trafficLightManager?.dispose();
      trafficLightManager = null;
      buildingManager?.dispose();
      buildingManager = null;
      heroContextManager?.dispose();
      heroContextManager = null;
      vegetationManager?.dispose();
      vegetationManager = null;
      streetFurnitureManager?.dispose();
      streetFurnitureManager = null;
      bicycleManager?.dispose();
      bicycleManager = null;
      pedestrianManager?.dispose();
      pedestrianManager = null;
      eventVisualizationManager?.dispose();
      eventVisualizationManager = null;
      weatherManager?.dispose();
      weatherManager = null;
      lightingManager?.dispose();
      lightingManager = null;
      analyticsLayerManager?.dispose();
      analyticsLayerManager = null;
      conflictAreaManager?.dispose();
      conflictAreaManager = null;
      roadsideDeviceManager?.dispose();
      roadsideDeviceManager = null;
      shadowBudgetManager?.dispose();
      shadowBudgetManager = null;
      textureManager?.dispose();
      textureManager = null;
      materialManager?.dispose();
      materialManager = null;
      lodManager = null;
      disposeObject(scene);
      renderer.dispose();
      renderRoot = null;
      loadedScene = null;
      coordinateService = null;
      controllerRef.current = null;
    };
  }, [scenarioId]);

  const selectedLabel = useMemo(
    () => (node ? `${node.display_id} / SUMO ${node.intersection_id}` : `${scenarioId} / SUMO 场景`),
    [node, scenarioId],
  );

  const performanceTelemetry = JSON.stringify({
    ...renderPerformance,
    quality: {...quality, targetFps: targetFrameRate(quality.level)},
    staticLod,
    textureBudget,
    view,
    weatherMode,
    displayMode,
    sourceMode,
    websocketOnline,
    status,
    simulationTimeS: digitalTwin.state.initialized
      ? digitalTwin.state.simulationTimeS
      : simulationTime,
    entityConnection: digitalTwin.connection,
    entitySequence: digitalTwin.state.sequence,
    experimentId: digitalTwin.state.experimentId,
    vehicleCount: digitalTwin.state.vehicles.size,
    renderedVehicles,
    bicycleCount: digitalTwin.state.bicycles.size,
    renderedBicycles,
    pedestrianCount: digitalTwin.state.pedestrians.size,
    renderedPedestrians,
    mappedSignals,
    deviceStats,
    analyticsStats,
    activeEventVisuals,
    eventInstanceCounts,
    summary,
  });

  return (
    <section className="intersection-stage" aria-labelledby="scene-title">
      <div className="scene-canvas-shell" data-performance={performanceTelemetry} ref={stageRef}>
        <canvas ref={canvasRef} aria-label={`雄安交通 ${scenarioId} 三维道路场景`} />
        <div className="scene-atmosphere" aria-hidden="true" />

        <div className="scene-heading">
          <h1 id="scene-title">雄安交通场景 · {scenarioId}</h1>
          <span>{selectedLabel}</span>
        </div>

        <div className={`scene-asset-state ${assetState}`} role="status">
          <span />
          {assetMessage}
        </div>

        <div className="scene-mode">
          <span className={assetState === "ready" ? "linked" : "preview"} />
          <div>
            <strong>{assetState === "ready" ? "真实 SUMO 静态拓扑" : "场景数据装载中"}</strong>
            <small>
              {sourceMode === "replay"
                ? `真实实验回放 · ${entityCount} 个动态参与者`
                : entityStreamOnline
                ? digitalTwin.state.experimentId
                  ? `实体级同步在线 · ${entityCount} 个动态参与者`
                  : "实体级同步在线 · 等待 SUMO 实验"
                : hasRealtimeMetrics
                  ? "聚合指标在线 · 实体流正在重连"
                  : "无随机车辆或伪信号动画"}
            </small>
          </div>
        </div>

        <div className="scene-readout">
          <dl>
            <div>
              <dt>路口 / TLS</dt>
              <dd>{formatCount(summary.trafficLights)}</dd>
            </div>
            <div>
              <dt>车道</dt>
              <dd>{formatCount(summary.lanes)}</dd>
            </div>
            <div>
              <dt>横道</dt>
              <dd>{formatCount(summary.crossings)}</dd>
            </div>
            <div>
              <dt>三角形</dt>
              <dd>{formatCount(summary.triangles)}</dd>
            </div>
            <div>
              <dt>OSM 建筑</dt>
              <dd>{formatCount(summary.buildings)}</dd>
            </div>
            <div>
              <dt>实例树木</dt>
              <dd>{formatCount(summary.trees)}</dd>
            </div>
            <div>
              <dt>路灯</dt>
              <dd>{formatCount(summary.streetLights)}</dd>
            </div>
            <div>
              <dt>路侧设备</dt>
              <dd>{formatCount(summary.roadsideDevices)}</dd>
            </div>
          </dl>
        </div>

        <div className="scene-view-controls" aria-label="三维视角">
          {(
            [
              ["overview", "全域"],
              ["corridor", "走廊"],
              ["urban", "城市"],
              ["vehicles", "车辆跟随"],
              ["multimodal", "非机动车"],
              ["pedestrians", "行人"],
              ["events", "事件"],
              ["rsu", "RSU"],
              ["monitor", "监控"],
              ["driver", "驾驶员"],
              ["cruise", "巡航"],
              ["junction", "选中路口"],
            ] as Array<[ViewMode, string]>
          ).map(([mode, label]) => (
            <button
              className={view === mode ? "active" : ""}
              disabled={mode === "junction" && !node}
              key={mode}
              onClick={() => {
                const director = demoDirectorRef.current;
                if (director?.snapshot().running) setDemo(director.stop());
                setView(mode);
                controllerRef.current?.setView(mode, node?.intersection_id ?? null);
              }}
              type="button"
            >
              {label}
            </button>
          ))}
        </div>

        <div className="scene-environment-controls" aria-label="天气与时段">
          <button aria-label="环境-大晴天" className="active" disabled type="button">大晴天</button>
        </div>

        <div className="scene-analysis-toggle" aria-label="三维显示模式">
          <button
            className={displayMode === "real" ? "active" : ""}
            onClick={() => setDisplayMode("real")}
            type="button"
          >
            真实模式
          </button>
          <button
            className={displayMode === "analysis" ? "active" : ""}
            onClick={() => setDisplayMode("analysis")}
            type="button"
          >
            分析模式
          </button>
        </div>

        <div className="scene-demo-control" aria-label="自动演示导演">
          <button
            className={demo.running ? "active" : ""}
            disabled={assetState !== "ready"}
            onClick={() => {
              const director = demoDirectorRef.current;
              if (!director) return;
              setDemo(demo.running ? director.stop() : director.start());
            }}
            type="button"
          >
            {demo.running ? "停止演示" : "自动演示"}
          </button>
          <span>
            {demo.label} · {Math.floor(demo.elapsedS)}/{demo.durationS}s
          </span>
        </div>

        <p className="scene-hint">点击车辆/道路/路口/信号灯/RSU 查看真值 · 拖拽旋转 · 滚轮缩放</p>
        {sceneSelection && (
          <aside className="scene-entity-inspector" aria-live="polite">
            <button
              aria-label="关闭三维对象检查器"
              onClick={() => setSceneSelection(null)}
              type="button"
            >
              ×
            </button>
            <h2>{sceneSelection.title}</h2>
            <small>{sceneSelection.subtitle}</small>
            <dl>
              {sceneSelection.fields.map((field) => (
                <div key={field.label}>
                  <dt>{field.label}</dt>
                  <dd title={field.value}>{field.value}</dd>
                </div>
              ))}
            </dl>
          </aside>
        )}
        <p className="scene-evidence">
          {sourceMode === "replay" ? "回放数据来自真实 SUMO 实验录制；" : ""}
          机动车、非机动车、行人、信号与施工/事故事件均由当前场景 {scenarioId} 的 SUMO 真值驱动；建筑与绿地仅在来源文件具备可追溯几何时显示，其余视觉补充均属于明确标注的工程假设
          {digitalTwin.issue ? ` · ${digitalTwin.issue}` : ""}
        </p>
      </div>
    </section>
  );
}
