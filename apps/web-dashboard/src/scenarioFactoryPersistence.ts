import type {ScenarioDraft} from "./api";

export type GeographicBounds = {west: number; south: number; east: number; north: number};
export type ScenarioMapView = {center: {lat: number; lon: number}; zoom: number};
export type ScenarioFactorySession = {
  buildId?: string;
  draftId?: string;
  sourceType: "current_osm" | "osm_bbox" | "planning_file";
  bbox: GeographicBounds | null;
  selectedIntersectionIds: string[];
  displayName: string;
  mapView: ScenarioMapView | null;
};

export type ScenarioFactoryRestoreTarget =
  | {kind: "draft"; draftId: string; buildId: string | null}
  | {kind: "build"; buildId: string}
  | {kind: "session"}
  | {kind: "fallback"};

export const scenarioFactorySessionStorageKey = "xiongan.scenario-factory.state";

export function parseGeographicBounds(value: unknown): GeographicBounds | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Partial<GeographicBounds>;
  const values = [candidate.west, candidate.south, candidate.east, candidate.north];
  if (!values.every((item) => typeof item === "number" && Number.isFinite(item))) return null;
  if (candidate.west! >= candidate.east! || candidate.south! >= candidate.north!) return null;
  return candidate as GeographicBounds;
}

export function draftSelectionBounds(draft: ScenarioDraft): GeographicBounds | null {
  return parseGeographicBounds(draft.source.bbox);
}

export function draftNetworkBounds(draft: ScenarioDraft): GeographicBounds | null {
  const context = draft.source.network_context;
  if (!context || typeof context !== "object") return null;
  return parseGeographicBounds((context as Record<string, unknown>).network_bbox);
}

export function readScenarioFactorySession(storage: Pick<Storage, "getItem">): ScenarioFactorySession | null {
  try {
    const raw = storage.getItem(scenarioFactorySessionStorageKey);
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<ScenarioFactorySession>;
    if (!value || typeof value !== "object") return null;
    if (!(["current_osm", "osm_bbox", "planning_file"] as const).includes(value.sourceType!)) return null;
    return {
      ...(typeof value.buildId === "string" ? {buildId: value.buildId} : {}),
      ...(typeof value.draftId === "string" ? {draftId: value.draftId} : {}),
      sourceType: value.sourceType!,
      bbox: parseGeographicBounds(value.bbox),
      selectedIntersectionIds: Array.isArray(value.selectedIntersectionIds)
        ? value.selectedIntersectionIds.filter((item): item is string => typeof item === "string")
        : [],
      displayName: typeof value.displayName === "string" ? value.displayName : "雄安自定义路网场景",
      mapView: parseMapView(value.mapView),
    };
  } catch {
    return null;
  }
}

export function writeScenarioFactorySession(
  storage: Pick<Storage, "setItem">,
  value: ScenarioFactorySession,
): void {
  try {
    storage.setItem(scenarioFactorySessionStorageKey, JSON.stringify(value));
  } catch {
    // Persistence is best-effort; the backend draft remains authoritative.
  }
}

export function selectScenarioFactoryRestoreTarget(
  session: ScenarioFactorySession | null,
): ScenarioFactoryRestoreTarget {
  if (session?.draftId) {
    return {kind: "draft", draftId: session.draftId, buildId: session.buildId ?? null};
  }
  if (session?.buildId) return {kind: "build", buildId: session.buildId};
  if (session) return {kind: "session"};
  return {kind: "fallback"};
}

function parseMapView(value: unknown): ScenarioMapView | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Partial<ScenarioMapView>;
  const center = candidate.center;
  if (!center || typeof center.lat !== "number" || typeof center.lon !== "number") return null;
  if (!Number.isFinite(center.lat) || !Number.isFinite(center.lon)) return null;
  if (typeof candidate.zoom !== "number" || !Number.isFinite(candidate.zoom)) return null;
  return {center: {lat: center.lat, lon: center.lon}, zoom: candidate.zoom};
}
