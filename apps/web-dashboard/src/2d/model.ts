export type SimulationViewMode = "2d" | "3d";

export type LayerKey =
  | "baseMap"
  | "buildings"
  | "roadMarkings"
  | "vehicles"
  | "buses"
  | "trucks"
  | "bicycles"
  | "pedestrians"
  | "signals"
  | "trafficState"
  | "queues"
  | "trails"
  | "algorithm"
  | "events"
  | "corridor"
  | "rsu"
  | "labels";

export type LayerVisibility = Record<LayerKey, boolean>;

export const defaultLayerVisibility: LayerVisibility = {
  baseMap: true,
  buildings: true,
  roadMarkings: true,
  vehicles: true,
  buses: true,
  trucks: true,
  bicycles: true,
  pedestrians: true,
  signals: true,
  trafficState: true,
  queues: true,
  trails: false,
  algorithm: true,
  events: true,
  corridor: true,
  rsu: false,
  labels: true,
};

export type MapSelection =
  | {kind: "junction"; id: string}
  | {kind: "edge"; id: string}
  | {kind: "vehicle"; id: string}
  | {kind: "bicycle"; id: string}
  | {kind: "pedestrian"; id: string}
  | {kind: "event"; id: string};

export type SceneLoadState = {
  status: "loading" | "ready" | "error";
  message: string;
  loadedBytes: number;
  totalBytes: number | null;
};

export type CanvasViewport = {
  width: number;
  height: number;
  dpr: number;
  centerX: number;
  centerY: number;
  scale: number;
};

export type CameraPreset = "overview" | "corridor" | "selection";
