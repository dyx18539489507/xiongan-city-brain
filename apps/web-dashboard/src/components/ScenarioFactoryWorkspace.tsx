import * as L from "leaflet";
import {useEffect, useMemo, useRef, useState} from "react";
import {
  createOsmScenarioDraft,
  createPlanningScenarioDraft,
  createScenarioBuild,
  describeRequestError,
  loadScenarioBuild,
  loadScenarioBuilds,
  loadScenarioDraft,
  openScenarioFolder,
  scenarioDraftArtifactUrl,
  validateScenarioBuild,
  type ScenarioBuildRecord,
  type ScenarioBuildRequest,
  type ScenarioDraft,
  type ScenarioDraftIntersection,
  type ScenarioDraftRoad,
} from "../api";
import {gcj02ToWgs84, wgs84ToGcj02} from "../chinaCoordinates";
import {createRetryingChineseMapLayer} from "../mapTileLayer";
import {selectRestorableScenarioBuild} from "../scenarioBuildPersistence";
import {
  draftNetworkBounds,
  draftSelectionBounds,
  readScenarioFactorySession,
  selectScenarioFactoryRestoreTarget,
  writeScenarioFactorySession,
  type GeographicBounds,
  type ScenarioMapView,
} from "../scenarioFactoryPersistence";
import type {IntersectionNode, TopologyEdge} from "../types";

type SourceType = "osm_bbox" | "planning_file" | "current_osm";
type Bbox = GeographicBounds;
const draftPollLimit = 720;
const buildPollLimit = 800;
const lastSuccessfulBuildStorageKey = "xiongan.scenario-factory.last-successful-build";

function formatElapsed(seconds: number): string {
  const minutes = Math.floor(seconds / 60).toString().padStart(2, "0");
  const remainder = Math.floor(seconds % 60).toString().padStart(2, "0");
  return `${minutes}:${remainder}`;
}

type Props = {
  nodes: IntersectionNode[];
  topologyEdges: TopologyEdge[];
  onBuilt: (scenarioId: string) => Promise<void>;
  onEnter2D: (scenarioId: string) => Promise<void>;
  onEnter3D: (scenarioId: string) => Promise<void>;
};

function safeScenarioId(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 64);
}

function createScenarioId(): string {
  const date = new Date().toISOString().replace(/\D/g, "").slice(0, 14);
  const suffix = Math.random().toString(36).slice(2, 8);
  return safeScenarioId(`xiongan-${date}-${suffix}`);
}

function createScenarioSeed(): number {
  return Math.floor(Math.random() * 2_147_483_648);
}

function toggleSet(current: Set<string>, identifier: string): Set<string> {
  const next = new Set(current);
  if (next.has(identifier)) next.delete(identifier);
  else next.add(identifier);
  return next;
}

function formatCoordinate(value: number): string {
  return Number.isFinite(value) ? value.toFixed(6) : "—";
}

function toMapLatLng(lon: number, lat: number): L.LatLngTuple {
  const point = wgs84ToGcj02(lon, lat);
  return [point.lat, point.lon];
}

function OsmSelectionMap({draft, selected, selectionBounds, restoredView, onToggle, onBounds, onViewChange, contextNodes, contextEdges}: {
  draft: ScenarioDraft | null;
  selected: Set<string>;
  selectionBounds: Bbox | null;
  restoredView: ScenarioMapView | null;
  onToggle: (identifier: string) => void;
  onBounds: (bbox: Bbox) => void;
  onViewChange: (view: ScenarioMapView) => void;
  contextNodes: IntersectionNode[];
  contextEdges: TopologyEdge[];
}) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const sourceLayersRef = useRef<L.LayerGroup | null>(null);
  const contextLayersRef = useRef<L.LayerGroup | null>(null);
  const selectionLayerRef = useRef<L.Rectangle | null>(null);
  const [drawing, setDrawing] = useState(false);
  const [tileStatus, setTileStatus] = useState("正在加载地图中...");
  const [baseMapReady, setBaseMapReady] = useState(false);
  const [baseMapFailed, setBaseMapFailed] = useState(false);

  useEffect(() => {
    if (!hostRef.current || mapRef.current) return;
    const map = L.map(hostRef.current, {
      attributionControl: true,
      preferCanvas: true,
      zoomControl: false,
    }).setView(toMapLatLng(115.916, 39.058), 16);
    map.attributionControl.setPosition("bottomleft");
    map.attributionControl.setPrefix(false);
    L.control.zoom({
      position: "bottomright",
      zoomInTitle: "放大",
      zoomOutTitle: "缩小",
    }).addTo(map);
    let tileErrorCount = 0;
    let tileSuccessCount = 0;
    let initialLoadResolved = false;
    let reportedRetry = 0;
    const tileLayer = createRetryingChineseMapLayer((attempt) => {
      if (attempt <= reportedRetry || initialLoadResolved) return;
      reportedRetry = attempt;
      setTileStatus("正在加载地图中...");
    }, {
      attribution: "&copy; 高德地图、智图",
    })
      .on("loading", () => {
        tileErrorCount = 0;
        tileSuccessCount = 0;
        reportedRetry = 0;
        if (!initialLoadResolved) {
          setBaseMapFailed(false);
          setTileStatus("正在加载地图中...");
        }
      })
      .on("tileload", () => {tileSuccessCount += 1;})
      .on("load", () => {
        if (!initialLoadResolved && tileSuccessCount > 0) {
          initialLoadResolved = true;
          setBaseMapReady(true);
        }
        if (tileSuccessCount === 0) {
          setBaseMapFailed(true);
          setTileStatus("在线地图加载失败");
        } else {
          setBaseMapFailed(false);
          setTileStatus(tileErrorCount === 0 ? "在线中文地图" : "部分地图加载失败，请检查网络");
        }
      })
      .on("tileerror", () => {
        tileErrorCount += 1;
      })
      .addTo(map);
    contextLayersRef.current = L.layerGroup().addTo(map);
    sourceLayersRef.current = L.layerGroup().addTo(map);
    mapRef.current = map;
    const publishView = () => {
      const center = map.getCenter();
      onViewChange({center: {lat: center.lat, lon: center.lng}, zoom: map.getZoom()});
    };
    map.on("moveend zoomend", publishView);

    let resizeFrame = 0;
    let settleFrame = 0;
    const refreshMapSize = () => {
      window.cancelAnimationFrame(resizeFrame);
      window.cancelAnimationFrame(settleFrame);
      resizeFrame = window.requestAnimationFrame(() => {
        settleFrame = window.requestAnimationFrame(() => map.invalidateSize({pan: false, debounceMoveend: true}));
      });
    };
    const resizeObserver = new ResizeObserver(refreshMapSize);
    resizeObserver.observe(hostRef.current);
    const handleVisibility = () => {if (document.visibilityState === "visible") refreshMapSize();};
    document.addEventListener("visibilitychange", handleVisibility);
    refreshMapSize();
    return () => {
      resizeObserver.disconnect();
      document.removeEventListener("visibilitychange", handleVisibility);
      map.off("moveend zoomend", publishView);
      window.cancelAnimationFrame(resizeFrame);
      window.cancelAnimationFrame(settleFrame);
      map.remove();
      mapRef.current = null;
      sourceLayersRef.current = null;
      contextLayersRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (restoredView) {
      const current = map.getCenter();
      if (Math.abs(current.lat - restoredView.center.lat) > 0.000001
        || Math.abs(current.lng - restoredView.center.lon) > 0.000001
        || map.getZoom() !== restoredView.zoom) {
        map.setView([restoredView.center.lat, restoredView.center.lon], restoredView.zoom, {animate: false});
      }
      return;
    }
    if (selectionBounds) {
      map.fitBounds(L.latLngBounds(
        toMapLatLng(selectionBounds.west, selectionBounds.south),
        toMapLatLng(selectionBounds.east, selectionBounds.north),
      ), {animate: false, maxZoom: 18, padding: [48, 48]});
    }
  }, [restoredView, selectionBounds]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    selectionLayerRef.current?.remove();
    selectionLayerRef.current = null;
    if (!selectionBounds) return;
    selectionLayerRef.current = L.rectangle(L.latLngBounds(
      toMapLatLng(selectionBounds.west, selectionBounds.south),
      toMapLatLng(selectionBounds.east, selectionBounds.north),
    ), {color: "#00a496", weight: 2, fillOpacity: .08}).addTo(map);
  }, [selectionBounds]);

  useEffect(() => {
    const layers = contextLayersRef.current;
    if (!layers) return;
    layers.clearLayers();
    if (!baseMapReady) return;
    const byId = new Map(contextNodes.map((node) => [node.intersection_id, node]));
    for (const edge of contextEdges) {
      const source = byId.get(edge.source);
      const target = byId.get(edge.target);
      if (!source || !target) continue;
      L.polyline([toMapLatLng(source.lon, source.lat), toMapLatLng(target.lon, target.lat)], {
        color: "#4f7775",
        weight: 3,
        opacity: .55,
        interactive: false,
      }).addTo(layers);
    }
    for (const node of contextNodes) {
      L.circleMarker(toMapLatLng(node.lon, node.lat), {
        radius: 2.5,
        color: "#73918e",
        weight: 1,
        fillColor: "#19383a",
        fillOpacity: .75,
        interactive: false,
      }).addTo(layers);
    }
  }, [baseMapReady, contextEdges, contextNodes]);

  useEffect(() => {
    const map = mapRef.current;
    const layers = sourceLayersRef.current;
    if (!map || !layers) return;
    layers.clearLayers();
    if (!baseMapReady || !draft || draft.status !== "ready" || draft.coordinate_mode !== "geographic") return;
    const networkBounds = draftNetworkBounds(draft);
    if (networkBounds) {
      L.rectangle(L.latLngBounds(
        toMapLatLng(networkBounds.west, networkBounds.south),
        toMapLatLng(networkBounds.east, networkBounds.north),
      ), {color: "#607d8b", dashArray: "7 6", weight: 1.5, fill: false, interactive: false})
        .bindTooltip("道路连通扩展范围", {direction: "top"})
        .addTo(layers);
    }
    for (const building of draft.preview.buildings) {
      const coordinates = building.coordinates.map((point) => toMapLatLng(point[0], point[1]));
      L.polygon(coordinates, {stroke: false, fillColor: "#39504f", fillOpacity: .32, interactive: false}).addTo(layers);
    }
    for (const road of draft.preview.roads) {
      const coordinates = road.coordinates.map((point) => toMapLatLng(point[0], point[1]));
      L.polyline(coordinates, {color: "#89a2a0", weight: Math.min(7, 1.4 + (road.lane_count ?? 1)), opacity: .6, interactive: false}).addTo(layers);
    }
    for (const intersection of draft.preview.intersections) {
      if (intersection.lat == null || intersection.lon == null) continue;
      const active = selected.has(intersection.intersection_id);
      const marker = L.circleMarker(toMapLatLng(intersection.lon, intersection.lat), {
        radius: active ? 7 : 4.5,
        color: active ? "#d8fff9" : "#587675",
        weight: active ? 2 : 1,
        fillColor: active ? "#4fd1c5" : "#132a2e",
        fillOpacity: 1,
      });
      marker.bindTooltip(`${intersection.display_id} · ${intersection.signalized ? "已有信号" : "生成时设置信号"}`, {direction: "top"});
      marker.on("click", () => onToggle(intersection.intersection_id));
      marker.addTo(layers);
    }
  }, [baseMapReady, draft, onToggle, selected]);

  const useBounds = (bounds: L.LatLngBounds) => {
    const southwest = gcj02ToWgs84(bounds.getWest(), bounds.getSouth());
    const northeast = gcj02ToWgs84(bounds.getEast(), bounds.getNorth());
    const bbox = {
      west: Math.min(southwest.lon, northeast.lon),
      south: Math.min(southwest.lat, northeast.lat),
      east: Math.max(southwest.lon, northeast.lon),
      north: Math.max(southwest.lat, northeast.lat),
    };
    onBounds(bbox);
    selectionLayerRef.current?.remove();
    selectionLayerRef.current = L.rectangle(bounds, {color: "#53cfc3", weight: 2, fillOpacity: .08}).addTo(mapRef.current!);
  };

  const beginRectangle = () => {
    const map = mapRef.current;
    if (!map || drawing) return;
    setDrawing(true);
    map.dragging.disable();
    map.getContainer().style.cursor = "crosshair";
    let start: L.LatLng | null = null;
    const move = (event: L.LeafletMouseEvent) => {
      if (!start) return;
      const bounds = L.latLngBounds(start, event.latlng);
      if (selectionLayerRef.current) selectionLayerRef.current.setBounds(bounds);
      else selectionLayerRef.current = L.rectangle(bounds, {color: "#53cfc3", weight: 2, fillOpacity: .08}).addTo(map);
    };
    const finish = (event: L.LeafletMouseEvent) => {
      if (start) useBounds(L.latLngBounds(start, event.latlng));
      map.off("mousemove", move);
      map.off("mouseup", finish);
      map.dragging.enable();
      map.getContainer().style.cursor = "";
      setDrawing(false);
    };
    map.once("mousedown", (event: L.LeafletMouseEvent) => {
      start = event.latlng;
      map.on("mousemove", move);
      map.on("mouseup", finish);
    });
  };

  return <div className="source-map-shell">
    <div className="source-map-toolbar">
      <button className={drawing ? "active" : ""} onClick={beginRectangle}>{drawing ? "拖动框选中…" : "在地图上框选"}</button>
      <button onClick={() => mapRef.current && useBounds(mapRef.current.getBounds())}>使用当前视野</button>
    </div>
    <div className="source-leaflet-map" ref={hostRef} />
    {!baseMapReady && <div className={`source-map-loading ${baseMapFailed ? "failed" : ""}`} role="status" aria-live="polite">
      {!baseMapFailed && <i className="factory-spinner" aria-hidden="true" />}
      <b>{baseMapFailed ? "地图暂时无法加载" : tileStatus}</b>
      {baseMapFailed && <button onClick={() => {
        setBaseMapFailed(false);
        setTileStatus("正在加载地图中...");
        mapRef.current?.eachLayer((layer) => {if (layer instanceof L.TileLayer) layer.redraw();});
      }}>重新加载</button>}
    </div>}
  </div>;
}

function PlanningCanvas({draft, selected, roads, intersections, onToggle}: {
  draft: ScenarioDraft;
  selected: Set<string>;
  roads: ScenarioDraftRoad[];
  intersections: ScenarioDraftIntersection[];
  onToggle: (identifier: string) => void;
}) {
  const fallback = {min_x: 0, min_y: 0, max_x: 1000, max_y: 620};
  const bounds = draft.preview.bounds ?? fallback;
  const width = Math.max(bounds.max_x - bounds.min_x, 1);
  const height = Math.max(bounds.max_y - bounds.min_y, 1);
  const toCanvas = (point: number[]) => [30 + ((point[0] - bounds.min_x) / width) * 940, 590 - ((point[1] - bounds.min_y) / height) * 560];
  const previewImage = draft.artifacts.preview ? scenarioDraftArtifactUrl(draft.id, "preview") : null;
  return <div className="planning-canvas-shell">
    <div className="source-map-toolbar planning-tools">
      <span>道路与候选路口已自动生成，点击圆点可调整受控路口</span>
    </div>
    <svg className="planning-canvas tool-select" viewBox="0 0 1000 620">
      <defs><pattern id="planning-grid" width="25" height="25" patternUnits="userSpaceOnUse"><path d="M 25 0 L 0 0 0 25" fill="none" stroke="rgba(105,145,143,.12)" /></pattern></defs>
      <rect width="1000" height="620" fill="#edf3ef" />
      {previewImage && <image href={previewImage} x="0" y="0" width="1000" height="620" preserveAspectRatio="xMidYMid meet" opacity=".5" />}
      <rect width="1000" height="620" fill="url(#planning-grid)" />
      {draft.preview.buildings.map((building) => <polygon key={building.id} className="planning-building" points={building.coordinates.map((point) => toCanvas(point).join(",")).join(" ")} />)}
      {roads.map((road) => <polyline key={road.id} className={road.id.startsWith("manual") ? "planning-road manual" : "planning-road"} points={road.coordinates.map((point) => toCanvas(point).join(",")).join(" ")} />)}
      {intersections.map((intersection) => {
        const point = toCanvas([intersection.x, intersection.y]);
        const active = selected.has(intersection.intersection_id);
        return <g key={intersection.intersection_id} className={`planning-node ${active ? "selected" : ""}`} onClick={(event) => {event.stopPropagation(); onToggle(intersection.intersection_id);}}>
          <circle cx={point[0]} cy={point[1]} r={active ? 10 : 7} />
          <text x={point[0]} y={point[1] - 15}>{intersection.display_id}</text>
        </g>;
      })}
    </svg>
  </div>;
}

function ExistingNetworkCanvas({nodes, topologyEdges, selected, onToggle}: {
  nodes: IntersectionNode[];
  topologyEdges: TopologyEdge[];
  selected: Set<string>;
  onToggle: (identifier: string) => void;
}) {
  const bounds = useMemo(() => {
    const xs = nodes.map((node) => node.lon);
    const ys = nodes.map((node) => node.lat);
    return {minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys)};
  }, [nodes]);
  const positions = useMemo(() => new Map(nodes.map((node) => {
    const width = Math.max(bounds.maxX - bounds.minX, .000001);
    const height = Math.max(bounds.maxY - bounds.minY, .000001);
    return [node.intersection_id, {x: 70 + ((node.lon - bounds.minX) / width) * 860, y: 550 - ((node.lat - bounds.minY) / height) * 480}];
  })), [bounds, nodes]);
  return <svg className="planning-canvas existing-network" viewBox="0 0 1000 620">
    <defs><pattern id="existing-grid" width="25" height="25" patternUnits="userSpaceOnUse"><path d="M 25 0 L 0 0 0 25" fill="none" stroke="rgba(105,145,143,.12)" /></pattern></defs>
    <rect width="1000" height="620" fill="#edf3ef" /><rect width="1000" height="620" fill="url(#existing-grid)" />
    {topologyEdges.map((edge) => {const from = positions.get(edge.source); const to = positions.get(edge.target); return from && to ? <line className="existing-road" key={`${edge.source}-${edge.target}`} x1={from.x} y1={from.y} x2={to.x} y2={to.y} /> : null;})}
    {nodes.map((node) => {const point = positions.get(node.intersection_id); if (!point) return null; const active = selected.has(node.intersection_id); return <g className={`planning-node ${active ? "selected" : ""}`} key={node.intersection_id} onClick={() => onToggle(node.intersection_id)}><circle cx={point.x} cy={point.y} r={active ? 10 : 7} /><text x={point.x} y={point.y - 15}>{node.display_id}</text></g>;})}
  </svg>;
}

export function ScenarioFactoryWorkspace({nodes, topologyEdges, onBuilt, onEnter2D, onEnter3D}: Props) {
  const [initialSession] = useState(() => readScenarioFactorySession(window.sessionStorage));
  const [sourceType, setSourceType] = useState<SourceType>(() => initialSession?.sourceType ?? "osm_bbox");
  const [bbox, setBbox] = useState<Bbox | null>(() => initialSession?.bbox ?? null);
  const [draft, setDraft] = useState<ScenarioDraft | null>(null);
  const [selected, setSelected] = useState<Set<string>>(() => new Set(initialSession?.selectedIntersectionIds ?? []));
  const [planningRoads, setPlanningRoads] = useState<ScenarioDraftRoad[]>([]);
  const [planningIntersections, setPlanningIntersections] = useState<ScenarioDraftIntersection[]>([]);
  const [scenarioId] = useState(createScenarioId);
  const [displayName, setDisplayName] = useState(() => initialSession?.displayName ?? "雄安自定义路网场景");
  const [scenarioSeed] = useState(createScenarioSeed);
  const [build, setBuild] = useState<ScenarioBuildRecord | null>(null);
  const [sourceBusy, setSourceBusy] = useState(false);
  const [buildBusy, setBuildBusy] = useState(false);
  const [sourceElapsedS, setSourceElapsedS] = useState(0);
  const [buildElapsedS, setBuildElapsedS] = useState(0);
  const [sourceIssue, setSourceIssue] = useState<string | null>(null);
  const [buildIssue, setBuildIssue] = useState<string | null>(null);
  const [handoffAction, setHandoffAction] = useState<"2d" | "3d" | "folder" | null>(null);
  const [mapView, setMapView] = useState<ScenarioMapView | null>(() => initialSession?.mapView ?? null);
  const [restoreFinished, setRestoreFinished] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    const restoreDraftPreview = (
      restoredDraft: ScenarioDraft,
      restoredSelection: string[],
      restoredBounds: Bbox | null,
    ) => {
      setDraft(restoredDraft);
      setPlanningRoads(restoredDraft.preview.roads);
      setPlanningIntersections(restoredDraft.preview.intersections);
      setBbox(restoredBounds ?? draftSelectionBounds(restoredDraft));
      setSelected(new Set(restoredSelection));
    };
    const restoreBuild = async (restored: ScenarioBuildRecord): Promise<boolean> => {
      if (restored.status !== "completed" || !restored.result) return false;
      setBuild(restored);
      setSourceType(restored.request.source_type);
      setDisplayName(restored.request.display_name);
      setSelected(new Set(restored.request.selected_intersection_ids));
      window.sessionStorage.setItem(lastSuccessfulBuildStorageKey, restored.id);
      if (restored.request.draft_id) {
        const restoredDraft = await loadScenarioDraft(restored.request.draft_id);
        if (cancelled) return true;
        restoreDraftPreview(
          restoredDraft,
          restored.request.selected_intersection_ids,
          draftSelectionBounds(restoredDraft),
        );
      }
      return true;
    };
    const restoreWorkspace = async () => {
      try {
        const target = selectScenarioFactoryRestoreTarget(initialSession);
        if (target.kind === "draft") {
          const restoredDraft = await loadScenarioDraft(target.draftId);
          if (cancelled) return;
          restoreDraftPreview(
            restoredDraft,
            initialSession?.selectedIntersectionIds ?? [],
            initialSession?.bbox ?? null,
          );
          if (target.buildId) {
            try {
              const restoredBuild = await loadScenarioBuild(target.buildId);
              if (
                !cancelled
                && restoredBuild.status === "completed"
                && restoredBuild.result
                && restoredBuild.request.draft_id === target.draftId
              ) {
                setBuild(restoredBuild);
                window.sessionStorage.setItem(lastSuccessfulBuildStorageKey, restoredBuild.id);
              }
            } catch {
              // The parsed draft remains usable even if its former build was removed.
            }
          }
          return;
        }
        if (target.kind === "session") return;
        if (target.kind === "build") {
          try {
            const restoredBuild = await loadScenarioBuild(target.buildId);
            if (cancelled || await restoreBuild(restoredBuild)) return;
          } catch {
            // Fall through to the most recent completed backend build.
          }
        }
        const response = await loadScenarioBuilds();
        const preferredId = window.sessionStorage.getItem(lastSuccessfulBuildStorageKey);
        const restored = selectRestorableScenarioBuild(response.items, preferredId);
        if (cancelled || !restored) return;
        await restoreBuild(restored);
      } catch {
        // Session restoration is best-effort; source editing remains available.
      } finally {
        if (!cancelled) setRestoreFinished(true);
      }
    };
    void restoreWorkspace();
    return () => {cancelled = true;};
  }, []);

  useEffect(() => {
    if (!restoreFinished) return;
    writeScenarioFactorySession(window.sessionStorage, {
      ...(build?.id ? {buildId: build.id} : {}),
      ...(draft?.id ? {draftId: draft.id} : {}),
      sourceType,
      bbox,
      selectedIntersectionIds: Array.from(selected),
      displayName,
      mapView,
    });
  }, [bbox, build?.id, displayName, draft?.id, mapView, restoreFinished, selected, sourceType]);

  useEffect(() => {
    if (sourceType !== "current_osm" || selected.size || !nodes.length) return;
    setSelected(new Set(nodes.filter((node) => node.role === "core_corridor").slice(0, 4).map((node) => node.intersection_id)));
  }, [nodes, selected.size, sourceType]);

  const adoptDraft = (record: ScenarioDraft) => {
    setDraft(record);
    const intersectionIds = record.source_type === "osm_bbox" && record.status === "ready"
      ? record.preview.intersections.map((intersection) => intersection.intersection_id)
      : record.selected_intersection_ids;
    setSelected(new Set(intersectionIds));
    setPlanningRoads(record.preview.roads);
    setPlanningIntersections(record.preview.intersections);
  };

  const waitForDraft = async (draftId: string) => {
    for (let attempt = 0; attempt < draftPollLimit; attempt += 1) {
      const record = await loadScenarioDraft(draftId);
      adoptDraft(record);
      if (record.status === "ready") return record;
      if (record.status === "failed") throw new Error(record.error ?? "来源解析失败");
      await new Promise((resolve) => window.setTimeout(resolve, 1000));
    }
    throw new Error("来源解析超时，请检查后台构建日志");
  };

  const createOsmDraft = async () => {
    if (!bbox) {setSourceIssue("请先在地图上框选范围，或使用当前视野范围"); return;}
    setSourceBusy(true); setSourceIssue(null); setBuildIssue(null); setBuild(null); setDraft(null); setSelected(new Set());
    try {
      const created = await createOsmScenarioDraft(bbox);
      await waitForDraft(created.id);
    } catch (reason) {
      setSourceIssue(describeRequestError(reason));
    } finally {setSourceBusy(false);}
  };

  const uploadPlanning = async (file: File) => {
    setSourceBusy(true); setSourceIssue(null); setBuildIssue(null); setBuild(null); setDraft(null); setSelected(new Set());
    try {
      const created = await createPlanningScenarioDraft(file);
      await waitForDraft(created.id);
    } catch (reason) {
      setSourceIssue(describeRequestError(reason));
    } finally {setSourceBusy(false);}
  };

  const switchSource = (next: SourceType) => {
    setSourceType(next); setSourceIssue(null); setBuildIssue(null); setBuild(null);
    if (next === "current_osm") setSelected(new Set(nodes.filter((node) => node.role === "core_corridor").slice(0, 4).map((node) => node.intersection_id)));
    else if (draft?.source_type === next) adoptDraft(draft);
    else setSelected(new Set());
  };

  const toggle = (identifier: string) => setSelected((current) => toggleSet(current, identifier));

  const request: ScenarioBuildRequest = {
    scenario_id: safeScenarioId(scenarioId),
    display_name: displayName.trim(),
    source_type: sourceType,
    ...(sourceType !== "current_osm" && draft ? {draft_id: draft.id} : {}),
    selected_intersection_ids: Array.from(selected),
    seed: scenarioSeed,
  };

  const runBuild = async () => {
    setBuildBusy(true); setBuildIssue(null); setBuild(null);
    try {
      if (sourceType !== "current_osm" && (!draft || draft.source_type !== sourceType)) throw new Error("请先完成当前来源解析");
      const checked = await validateScenarioBuild(request);
      if (!checked.valid) {
        setBuildIssue(checked.errors.length ? checked.errors.join("；") : `场景校验未通过：${checked.rule}`);
        return;
      }
      const created = await createScenarioBuild(request);
      let record: ScenarioBuildRecord | null = null;
      for (let attempt = 0; attempt < buildPollLimit; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 900));
        record = await loadScenarioBuild(created.id);
        setBuild(record);
        if (record.status !== "queued" && record.status !== "running") break;
      }
      if (!record || record.status === "queued" || record.status === "running") throw new Error("场景生成等待超时，后台任务可能仍在继续，请稍后重新进入页面查看");
      if (record.status === "completed") {
        window.sessionStorage.setItem(lastSuccessfulBuildStorageKey, record.id);
        await onBuilt(record.request.scenario_id);
      }
      else setBuildIssue(record.error ?? "场景构建失败");
    } catch (reason) {
      setBuildIssue(describeRequestError(reason));
    } finally {setBuildBusy(false);}
  };

  useEffect(() => {
    if (!sourceBusy) return;
    const startedAt = Date.now();
    setSourceElapsedS(0);
    const timer = window.setInterval(() => setSourceElapsedS(Math.floor((Date.now() - startedAt) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [sourceBusy]);

  useEffect(() => {
    if (!buildBusy) return;
    const startedAt = Date.now();
    setBuildElapsedS(0);
    const timer = window.setInterval(() => setBuildElapsedS(Math.floor((Date.now() - startedAt) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [buildBusy]);

  const runHandoff = async (action: "2d" | "3d" | "folder", operation: () => Promise<unknown>) => {
    setHandoffAction(action);
    setBuildIssue(null);
    try {
      await operation();
    } catch (reason) {
      setBuildIssue(describeRequestError(reason));
    } finally {
      setHandoffAction(null);
    }
  };

  const ready = sourceType === "current_osm" || (draft?.source_type === sourceType && draft.status === "ready");
  return <section className="workspace-page scenario-workspace" aria-label="场景生成工作区">
    <nav className="factory-source-tabs" aria-label="路网来源">
      <button className={sourceType === "osm_bbox" ? "active" : ""} disabled={sourceBusy || buildBusy} onClick={() => switchSource("osm_bbox")}><b>OSM 地图框选</b><span>真实地理范围 · 推荐</span></button>
      <button className={sourceType === "planning_file" ? "active" : ""} disabled={sourceBusy || buildBusy} onClick={() => switchSource("planning_file")}><b>上传规划资料</b><span>DXF / GIS / PDF / 图片</span></button>
    </nav>
    <div className="scenario-factory-layout source-first">
      <aside className="factory-form">
        <div className="factory-section-title"><span>1</span><div><b>来源与范围</b></div></div>
        {sourceType === "osm_bbox" && <>
          <div className="bbox-ledger"><span>西</span><b>{bbox ? formatCoordinate(bbox.west) : "待框选"}</b><span>东</span><b>{bbox ? formatCoordinate(bbox.east) : "待框选"}</b><span>南</span><b>{bbox ? formatCoordinate(bbox.south) : "待框选"}</b><span>北</span><b>{bbox ? formatCoordinate(bbox.north) : "待框选"}</b></div>
          <button className="workspace-primary source-action" disabled={!bbox || sourceBusy} onClick={createOsmDraft}>{sourceBusy ? "正在解析中" : "解析框选范围"}</button>
        </>}
        {sourceType === "planning_file" && <>
          <input ref={fileRef} hidden type="file" accept=".dxf,.geojson,.json,.gpkg,.zip,.pdf,.png,.jpg,.jpeg,.webp" onChange={(event) => {const file = event.target.files?.[0]; if (file) void uploadPlanning(file);}} />
          <button className="planning-upload" disabled={sourceBusy} onClick={() => fileRef.current?.click()}><span>+</span><b>{sourceBusy ? "正在解析中" : "选择规划资料"}</b><small>最大 50 MB · 原文件不会被覆盖</small></button>
          <p className="factory-source-note">结构化资料、PDF 和图片均自动生成路网；图片无需坐标、比例尺或人工补绘。</p>
        </>}
        {sourceType === "current_osm" && <p className="factory-source-note existing-source-note">使用已验证的容东 OSM/SUMO 网络，只改变受控路口集合，不复制一套交通状态。</p>}
        {sourceBusy && !draft && <div className="draft-status processing" role="status" aria-live="polite">
          <i className="factory-spinner" aria-hidden="true" /><span>正在解析中 · {formatElapsed(sourceElapsedS)}</span>
        </div>}
        {draft && draft.source_type === sourceType && (draft.status === "failed"
          ? <div className="draft-status failed"><span>解析失败</span>{draft.error && <small className="error">{describeRequestError(draft.error)}</small>}</div>
          : <div className={`draft-status ${draft.status === "ready" ? "completed" : "processing"}`} role="status" aria-live="polite">
            {draft.status === "ready" ? <i className="draft-status-check" aria-hidden="true">✓</i> : <i className="factory-spinner" aria-hidden="true" />}
            <span>{draft.status === "ready" ? "解析完成" : `正在解析中 · ${formatElapsed(sourceElapsedS)}`}</span>
          </div>)}
        {sourceIssue && <p className="factory-issue source-issue" role="alert">{sourceIssue}</p>}
        <div className="factory-section-title config-title"><span>2</span><div><b>场景信息</b></div></div>
        <label><span>场景名称</span><input value={displayName} onChange={(event) => setDisplayName(event.target.value)} /></label>
      </aside>
      <article className="factory-map-panel">
        {sourceType === "osm_bbox" && <OsmSelectionMap draft={draft?.source_type === "osm_bbox" ? draft : null} selected={selected} selectionBounds={bbox} restoredView={mapView} onToggle={toggle} onBounds={setBbox} onViewChange={setMapView} contextNodes={nodes} contextEdges={topologyEdges} />}
        {sourceType === "planning_file" && draft?.source_type === "planning_file" && draft.status === "ready" ? <PlanningCanvas draft={draft} selected={selected} roads={planningRoads} intersections={planningIntersections} onToggle={toggle} /> : sourceType === "planning_file" ? <div className="factory-empty-canvas"><b>上传后在这里预览</b><span>识别出的道路、候选路口与原始图纸会叠加显示</span></div> : null}
        {sourceType === "current_osm" && <ExistingNetworkCanvas nodes={nodes} topologyEdges={topologyEdges} selected={selected} onToggle={toggle} />}
      </article>
      <aside className="factory-inspector">
        <div className="factory-section-title"><span>3</span><div><b>生成场景</b></div></div>
        <div className={`factory-publish-state ${selected.size > 0 ? "ready" : ""}`}>
          <i />
          <div>{selected.size > 0 ? <b>{`地图中已选择 ${selected.size} 个受控路口`}</b> : <><b>等待选择路口</b><span>请直接在地图中点击路口</span></>}</div>
        </div>
        {buildIssue && <p className="factory-issue" role="alert">{buildIssue}</p>}
        {buildBusy && !build && <div className="factory-generation-loading" role="status"><i className="factory-spinner" aria-hidden="true" /><span>正在校验并创建生成任务 · {formatElapsed(buildElapsedS)}</span></div>}
        {build && <div className="factory-progress"><div><i style={{width: `${build.progress}%`}} /></div><b>{buildBusy && <i className="factory-spinner" aria-hidden="true" />}<span>{build.progress}% · {build.message}{buildBusy ? ` · ${formatElapsed(buildElapsedS)}` : ""}</span></b><ol>{build.logs.slice(-6).map((item, index) => <li key={`${item.time}-${index}`}>{item.message}</li>)}</ol>{build.result && <nav className="factory-success-actions"><button aria-busy={handoffAction === "2d"} className="workspace-primary" disabled={handoffAction !== null} onClick={() => void runHandoff("2d", () => onEnter2D(build.result!.scenario_id))}>{handoffAction === "2d" ? "正在进入 2D…" : "进入 2D 仿真"}</button><button aria-busy={handoffAction === "3d"} disabled={handoffAction !== null} onClick={() => void runHandoff("3d", () => onEnter3D(build.result!.scenario_id))}>{handoffAction === "3d" ? "正在进入 Unity 3D…" : "进入 Unity 3D 仿真"}</button><button aria-busy={handoffAction === "folder"} disabled={handoffAction !== null} onClick={() => void runHandoff("folder", () => openScenarioFolder(build.result!.scenario_id))}>{handoffAction === "folder" ? "正在打开…" : "打开所在文件夹"}</button></nav>}</div>}
        {!build?.result && <div className="factory-publish-actions">
          <button aria-busy={buildBusy} className="workspace-primary factory-build" disabled={buildBusy || sourceBusy || !ready || selected.size === 0 || !request.scenario_id || request.display_name.length < 2} onClick={runBuild}>{buildBusy ? `正在生成并验证 · ${formatElapsed(buildElapsedS)}` : "开始生成"}</button>
        </div>}
      </aside>
    </div>
  </section>;
}
