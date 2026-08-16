import type {DigitalTwinState, PedestrianEntity, VehicleEntity} from "../3d/network/digitalTwinTypes";
import type {Point2, StaticSceneDocument} from "../3d/scene/types";
import type {RealtimeSnapshot} from "../types";
import {MapCamera} from "./camera/MapCamera";
import {BicycleLayer, PedestrianLayer, TrailLayer, VehicleLayer} from "./layers/ActorLayers";
import type {LayerRenderContext, RenderEntities, TrafficMapLayer} from "./layers/LayerTypes";
import {AlgorithmLayer, EventLayer, LabelLayer, resolveEventMarkers, RoadsideDeviceLayer, SelectionLayer} from "./layers/OperationalLayers";
import {CorridorLayer, RoadMarkingLayer, RoadSurfaceLayer} from "./layers/RoadLayers";
import {SignalLayer} from "./layers/SignalLayer";
import {QueueLayer, TrafficStateLayer} from "./layers/TrafficStateLayers";
import {BackgroundLayer, BuildingLayer} from "./layers/UrbanContextLayers";
import type {LayerVisibility, MapSelection} from "./model";
import {EntityInterpolator} from "./motion/EntityInterpolator";
import {TrafficWorldStateAdapter, type TrafficWorldState} from "./world/TrafficWorldState";

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

function distanceToSegment(point: Point2, start: Point2, end: Point2): number {
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  if (!dx && !dy) return Math.hypot(point.x - start.x, point.y - start.y);
  const ratio = clamp(((point.x - start.x) * dx + (point.y - start.y) * dy) / (dx * dx + dy * dy), 0, 1);
  return Math.hypot(point.x - (start.x + ratio * dx), point.y - (start.y + ratio * dy));
}

function countVisibleEntities(
  entities: readonly {renderX: number; renderY: number}[],
  bounds: ReturnType<MapCamera["visibleBounds"]>,
): number {
  let visible = 0;
  for (const entity of entities) {
    if (entity.renderX >= bounds.minX && entity.renderX <= bounds.maxX && entity.renderY >= bounds.minY && entity.renderY <= bounds.maxY) visible += 1;
  }
  return visible;
}

export type RendererStats = {fps: number; targetFps: number; drawMs: number; visibleEntities: number; totalEntities: number};

const MAX_CANVAS_PIXELS = 6_000_000;

/**
 * Layer orchestrator for the 2D presentation. It receives WorldState snapshots,
 * owns no WebSocket, and keeps high-frequency drawing outside React's DOM tree.
 */
export class TrafficCanvasRenderer {
  private readonly camera = new MapCamera();
  private readonly dynamicContext: CanvasRenderingContext2D | null;
  private readonly staticContext: CanvasRenderingContext2D | null;
  private readonly adapter = new TrafficWorldStateAdapter();
  private readonly vehicles = new EntityInterpolator<VehicleEntity>();
  private readonly bicycles = new EntityInterpolator<VehicleEntity>();
  private readonly pedestrians = new EntityInterpolator<PedestrianEntity>();
  private readonly layers: TrafficMapLayer[];
  private layerVisibility: LayerVisibility;
  private world: TrafficWorldState | null = null;
  private lastDigitalTwin: DigitalTwinState | null = null;
  private lastEntitySequence = -1;
  private lastEntityExperimentId: string | null = null;
  private lastSnapshot: RealtimeSnapshot = {status: "idle"};
  private entities: RenderEntities = {vehicles: [], bicycles: [], pedestrians: []};
  private selection: MapSelection | null = null;
  private hover: MapSelection | null = null;
  private staticDirty = true;
  private lastCameraRevision = -1;
  private stats: RendererStats = {fps: 0, targetFps: 60, drawMs: 0, visibleEntities: 0, totalEntities: 0};
  private frameCounter = 0;
  private fpsWindowStarted = performance.now();
  private lastRenderedAt = 0;
  private frameIntervalMs = 1000 / 60;
  private averageDrawMs = 0;
  private lastFrameBudgetUpdate = performance.now();

  constructor(
    private readonly canvas: HTMLCanvasElement,
    private readonly staticCanvas: HTMLCanvasElement,
    layers: LayerVisibility,
  ) {
    this.dynamicContext = canvas.getContext("2d", {alpha: true});
    this.staticContext = staticCanvas.getContext("2d", {alpha: false});
    this.layerVisibility = layers;
    this.layers = [
      new BackgroundLayer(),
      new BuildingLayer(),
      new CorridorLayer(),
      new RoadSurfaceLayer(),
      new RoadMarkingLayer(),
      new TrafficStateLayer(),
      new QueueLayer(),
      new TrailLayer((id) => this.vehicles.getTrail(id), (id) => this.bicycles.getTrail(id)),
      new SignalLayer(),
      new VehicleLayer(),
      new BicycleLayer(),
      new PedestrianLayer(),
      new AlgorithmLayer(),
      new EventLayer(),
      new RoadsideDeviceLayer(),
      new LabelLayer(),
      new SelectionLayer(),
    ];
  }

  setScene(scene: StaticSceneDocument): void {
    this.adapter.setScene(scene);
    this.camera.setSceneBounds(scene.coordinateSystem.sceneBounds);
    if (this.lastDigitalTwin) this.world = this.adapter.compose(this.lastDigitalTwin, this.lastSnapshot);
    this.staticDirty = true;
  }

  setData(digitalTwin: DigitalTwinState, snapshot: RealtimeSnapshot, now: number): void {
    this.lastDigitalTwin = digitalTwin;
    this.lastSnapshot = snapshot;
    this.world = this.adapter.compose(digitalTwin, snapshot);
    const streamRestarted = digitalTwin.sequence < this.lastEntitySequence;
    const experimentChanged = digitalTwin.experimentId !== this.lastEntityExperimentId;
    if (streamRestarted || experimentChanged) {
      this.vehicles.reset();
      this.bicycles.reset();
      this.pedestrians.reset();
      this.lastEntitySequence = -1;
    }
    this.lastEntityExperimentId = digitalTwin.experimentId;
    if (digitalTwin.initialized && digitalTwin.sequence !== this.lastEntitySequence) {
      this.vehicles.update(digitalTwin.vehicles, now, digitalTwin.tickHz);
      this.bicycles.update(digitalTwin.bicycles, now, digitalTwin.tickHz);
      this.pedestrians.update(digitalTwin.pedestrians, now, digitalTwin.tickHz);
      this.lastEntitySequence = digitalTwin.sequence;
    }
  }

  setLayers(layers: LayerVisibility): void {
    const staticChanged = this.layers.some((layer) => layer.isStatic && layer.id !== "selection" && layers[layer.id] !== this.layerVisibility[layer.id]);
    this.layerVisibility = layers;
    if (staticChanged) this.staticDirty = true;
  }

  setSelection(selection: MapSelection | null): void { this.selection = selection; }
  setHover(selection: MapSelection | null): void { this.hover = selection; }

  resize(width: number, height: number): void {
    const cssWidth = Math.max(1, Math.round(width));
    const cssHeight = Math.max(1, Math.round(height));
    const cssPixels = cssWidth * cssHeight;
    const deviceDpr = window.devicePixelRatio || 1;
    const pixelBudgetDpr = Math.sqrt(MAX_CANVAS_PIXELS / cssPixels);
    const dpr = Math.min(deviceDpr, 1.75, Math.max(.85, pixelBudgetDpr));
    this.camera.resize(cssWidth, cssHeight, dpr);
    this.canvas.width = Math.round(cssWidth * dpr);
    this.canvas.height = Math.round(cssHeight * dpr);
    this.staticCanvas.width = this.canvas.width;
    this.staticCanvas.height = this.canvas.height;
    this.staticDirty = true;
  }

  fitScene(): void {
    if (!this.world) return;
    this.camera.fitBounds(this.world.scene.coordinateSystem.sceneBounds, 158, true);
    this.staticDirty = true;
  }

  focusCorridor(): void {
    if (!this.world) return;
    const points = [...this.world.corridorJunctionIds]
      .map((id) => this.world?.junctionById.get(id)?.position)
      .filter((point): point is Point2 => Boolean(point));
    if (points.length) this.camera.fitPoints(points, 190, true);
  }

  focusSelection(selection: MapSelection | null): void {
    if (!selection || !this.world) return;
    if (selection.kind === "junction") {
      const point = this.world.junctionById.get(selection.id)?.position;
      if (point) this.camera.focusPoint(point, Math.max(.82, this.camera.scale * 1.7));
    } else if (selection.kind === "edge") {
      const shape = this.world.edgeById.get(selection.id)?.shape;
      if (shape) this.camera.fitPoints(shape, 240, true);
    } else {
      const entity = [...this.entities.vehicles, ...this.entities.bicycles, ...this.entities.pedestrians].find((item) => item.id === selection.id);
      if (entity) this.camera.focusPoint({x: entity.renderX, y: entity.renderY}, Math.max(1, this.camera.scale * 1.5));
    }
  }

  focusJunction(id: string): void { this.focusSelection({kind: "junction", id}); }
  pan(deltaX: number, deltaY: number): void { this.camera.pan(deltaX, deltaY); this.staticDirty = true; }
  zoomAt(screenX: number, screenY: number, factor: number): void { this.camera.zoomAt(screenX, screenY, factor); this.staticDirty = true; }
  getScale(): number { return this.camera.scale; }
  getStats(): RendererStats { return {...this.stats}; }

  render(now: number): void {
    const elapsed = now - this.lastRenderedAt;
    if (this.lastRenderedAt && elapsed + .5 < this.frameIntervalMs) return;
    this.lastRenderedAt = this.lastRenderedAt
      ? now - Math.min(this.frameIntervalMs, elapsed % this.frameIntervalMs)
      : now;
    const started = performance.now();
    const ctx = this.dynamicContext;
    if (!ctx) return;
    if (this.camera.update(now)) this.staticDirty = true;
    if (!this.world) {
      ctx.setTransform(this.camera.dpr, 0, 0, this.camera.dpr, 0, 0);
      ctx.clearRect(0, 0, this.camera.width, this.camera.height);
      return;
    }
    this.entities.vehicles = this.vehicles.sample(now);
    this.entities.bicycles = this.bicycles.sample(now);
    this.entities.pedestrians = this.pedestrians.sample(now);
    const context = this.renderContext(ctx, now);
    if (this.staticDirty || this.lastCameraRevision !== this.camera.revision) this.rebuildStatic(context);
    ctx.setTransform(this.camera.dpr, 0, 0, this.camera.dpr, 0, 0);
    ctx.clearRect(0, 0, this.camera.width, this.camera.height);
    for (const layer of this.layers) {
      if (layer.isStatic || (layer.id !== "selection" && !this.layerVisibility[layer.id])) continue;
      layer.render(context);
    }
    this.updateStats(started, context.visibleBounds);
  }

  pick(screenX: number, screenY: number): MapSelection | null {
    if (!this.world) return null;
    if (this.camera.scale > .2) {
      let nearest: {kind: "vehicle" | "bicycle" | "pedestrian"; id: string; distance: number} | null = null;
      const groups = [
        ["vehicle" as const, this.layerVisibility.vehicles ? this.entities.vehicles : []],
        ["bicycle" as const, this.layerVisibility.bicycles ? this.entities.bicycles : []],
        ["pedestrian" as const, this.layerVisibility.pedestrians ? this.entities.pedestrians : []],
      ] as const;
      for (const [kind, entities] of groups) {
        for (const entity of entities) {
          const entityScreenX = (entity.renderX - this.camera.centerX) * this.camera.scale + this.camera.width / 2;
          const entityScreenY = (this.camera.centerY - entity.renderY) * this.camera.scale + this.camera.height / 2;
          const distance = Math.hypot(entityScreenX - screenX, entityScreenY - screenY);
          if (distance <= 12 && (!nearest || distance < nearest.distance)) nearest = {kind, id: entity.id, distance};
        }
      }
      if (nearest) return {kind: nearest.kind, id: nearest.id};
    }

    if (!this.dynamicContext) return null;
    const context = this.renderContext(this.dynamicContext, performance.now());
    if (this.layerVisibility.events) {
      for (const marker of resolveEventMarkers(context)) {
        const point = this.camera.worldToScreen(marker);
        if (Math.hypot(point.x - screenX, point.y - screenY) <= 14) return {kind: "event", id: marker.id};
      }
    }

    const worldPoint = this.camera.screenToWorld(screenX, screenY);
    let junctionPick: {id: string; distance: number} | null = null;
    const junctionTolerance = 18 / this.camera.scale;
    for (const junction of this.world.scene.junctions) {
      if (!junction.controlled) continue;
      const distance = Math.hypot(worldPoint.x - junction.position.x, worldPoint.y - junction.position.y);
      if (distance <= junctionTolerance && (!junctionPick || distance < junctionPick.distance)) junctionPick = {id: junction.sumoJunctionId, distance};
    }
    if (junctionPick) return {kind: "junction", id: junctionPick.id};

    let edgePick: {id: string; distance: number} | null = null;
    const tolerance = 8 / this.camera.scale;
    for (const indexed of this.world.indexedEdges) {
      if (worldPoint.x < indexed.minX - tolerance || worldPoint.x > indexed.maxX + tolerance || worldPoint.y < indexed.minY - tolerance || worldPoint.y > indexed.maxY + tolerance) continue;
      for (let index = 0; index < indexed.shape.length - 1; index += 1) {
        const distance = distanceToSegment(worldPoint, indexed.shape[index], indexed.shape[index + 1]);
        if (distance <= tolerance && (!edgePick || distance < edgePick.distance)) edgePick = {id: indexed.edge.sumoEdgeId, distance};
      }
    }
    return edgePick ? {kind: "edge", id: edgePick.id} : null;
  }

  destroy(): void { for (const layer of this.layers) layer.destroy(); }

  private rebuildStatic(dynamicContext: LayerRenderContext): void {
    const ctx = this.staticContext;
    if (!ctx) return;
    ctx.setTransform(this.camera.dpr, 0, 0, this.camera.dpr, 0, 0);
    ctx.clearRect(0, 0, this.camera.width, this.camera.height);
    const context = {...dynamicContext, ctx};
    for (const layer of this.layers) {
      if (!layer.isStatic || layer.id === "selection" || !this.layerVisibility[layer.id]) continue;
      layer.render(context);
    }
    this.staticDirty = false;
    this.lastCameraRevision = this.camera.revision;
  }

  private renderContext(ctx: CanvasRenderingContext2D, now: number): LayerRenderContext {
    return {
      ctx,
      camera: this.camera,
      world: this.world!,
      entities: this.entities,
      selection: this.selection,
      hover: this.hover,
      now,
      visibleBounds: this.camera.visibleBounds(),
      layers: this.layerVisibility,
    };
  }

  private updateStats(started: number, bounds: ReturnType<MapCamera["visibleBounds"]>): void {
    const total = this.entities.vehicles.length + this.entities.bicycles.length + this.entities.pedestrians.length;
    const visible = countVisibleEntities(this.entities.vehicles, bounds)
      + countVisibleEntities(this.entities.bicycles, bounds)
      + countVisibleEntities(this.entities.pedestrians, bounds);
    this.frameCounter += 1;
    const now = performance.now();
    const drawMs = now - started;
    this.averageDrawMs = this.averageDrawMs ? this.averageDrawMs * .9 + drawMs * .1 : drawMs;
    if (now - this.lastFrameBudgetUpdate >= 1000) {
      const targetFps = this.averageDrawMs > 20 ? 30 : this.averageDrawMs > 11 ? 45 : 60;
      this.frameIntervalMs = 1000 / targetFps;
      this.stats.targetFps = targetFps;
      this.lastFrameBudgetUpdate = now;
    }
    if (now - this.fpsWindowStarted >= 800) {
      this.stats.fps = this.frameCounter * 1000 / (now - this.fpsWindowStarted);
      this.frameCounter = 0;
      this.fpsWindowStarted = now;
    }
    this.stats.drawMs = drawMs;
    this.stats.visibleEntities = visible;
    this.stats.totalEntities = total;
  }
}
