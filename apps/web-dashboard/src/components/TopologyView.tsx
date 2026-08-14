import {useMemo} from "react";
import type {
  IntersectionNode,
  IntersectionRealtime,
  TopologyEdge,
} from "../types";

type Props = {
  nodes: IntersectionNode[];
  edges: TopologyEdge[];
  realtime: IntersectionRealtime[];
  selectedId: string | null;
  activeDisturbances: string[];
  congestedIntersections: string[];
  spillbackEdges: string[];
  onSelect: (id: string) => void;
};

type Point = {x: number; y: number};

export function congestionColor(level: number | null): string {
  if (level === null) return "#54717f";
  if (level >= 0.85) return "#ff8b5c";
  if (level >= 0.6) return "#e7ba63";
  return "#35d5b3";
}

function disturbanceLabel(value: string): string {
  const normalized = value.toLowerCase();
  if (normalized.includes("roadwork") || normalized.includes("construction")) {
    return "施工";
  }
  if (normalized.includes("incident") || normalized.includes("accident")) {
    return "事故";
  }
  if (normalized.includes("event")) return "散场";
  if (normalized.includes("emergency")) return "应急";
  return value;
}

export function TopologyView({
  nodes,
  edges,
  realtime,
  selectedId,
  activeDisturbances,
  congestedIntersections,
  spillbackEdges,
  onSelect,
}: Props) {
  const stateById = useMemo(
    () => new Map(realtime.map((item) => [item.intersection_id, item])),
    [realtime],
  );
  const congested = useMemo(
    () => new Set(
      Array.isArray(congestedIntersections) ? congestedIntersections : [],
    ),
    [congestedIntersections],
  );
  const points = useMemo(() => {
    if (!nodes.length) return new Map<string, Point>();
    const lons = nodes.map((item) => item.lon);
    const lats = nodes.map((item) => item.lat);
    const minLon = Math.min(...lons);
    const maxLon = Math.max(...lons);
    const minLat = Math.min(...lats);
    const maxLat = Math.max(...lats);
    const result = new Map<string, Point>();
    for (const node of nodes) {
      result.set(node.intersection_id, {
        x: 65 + ((node.lon - minLon) / Math.max(maxLon - minLon, 0.00001)) * 870,
        y: 70 + ((maxLat - node.lat) / Math.max(maxLat - minLat, 0.00001)) * 430,
      });
    }
    return result;
  }, [nodes]);

  return (
    <section className="topology-workspace" aria-labelledby="topology-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">REAL GEOGRAPHY / ENGINEERING MODEL</p>
          <h2 id="topology-title">容东 20 路口协同拓扑</h2>
        </div>
        <div className="legend" aria-label="拥堵图例">
          <span>
            <i className="legend-dot low" />
            畅通
          </span>
          <span>
            <i className="legend-dot medium" />
            趋饱和
          </span>
          <span>
            <i className="legend-dot high" />
            溢出风险
          </span>
          <span>
            <i className="legend-line" />
            传播路径
          </span>
        </div>
      </div>
      <div className="topology-canvas">
        <svg
          viewBox="0 0 1000 560"
          role="img"
          aria-label="基于真实经纬度投影的二十路口控制拓扑"
        >
          <defs>
            <filter id="nodeGlow" x="-100%" y="-100%" width="300%" height="300%">
              <feGaussianBlur stdDeviation="5" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>
          <g className="topology-grid">
            {Array.from({length: 9}, (_, index) => (
              <line
                key={`v-${index}`}
                x1={80 + index * 105}
                y1="45"
                x2={80 + index * 105}
                y2="520"
              />
            ))}
            {Array.from({length: 5}, (_, index) => (
              <line
                key={`h-${index}`}
                x1="45"
                y1={85 + index * 100}
                x2="960"
                y2={85 + index * 100}
              />
            ))}
          </g>
          <g className="network-edges">
            {edges.map((edge) => {
              const source = points.get(edge.source);
              const target = points.get(edge.target);
              if (!source || !target) return null;
              const isCore =
                nodes.find((node) => node.intersection_id === edge.source)
                  ?.role === "core_corridor" &&
                nodes.find((node) => node.intersection_id === edge.target)
                  ?.role === "core_corridor";
              const isPropagation =
                congested.has(edge.source) && congested.has(edge.target);
              return (
                <line
                  key={`${edge.source}-${edge.target}`}
                  x1={source.x}
                  y1={source.y}
                  x2={target.x}
                  y2={target.y}
                  className={`${isCore ? "core-edge" : ""} ${
                    isPropagation ? "propagation-edge" : ""
                  }`}
                />
              );
            })}
          </g>
          <g className="network-nodes">
            {nodes.map((node) => {
              const point = points.get(node.intersection_id);
              if (!point) return null;
              const live = stateById.get(node.intersection_id);
              const color = congestionColor(live?.congestion_level ?? null);
              const selected = selectedId === node.intersection_id;
              const incident =
                live?.incident_state &&
                !["none", "normal", "clear"].includes(
                  live.incident_state.toLowerCase(),
                );
              return (
                <g
                  key={node.intersection_id}
                  className={`intersection-node ${selected ? "selected" : ""}`}
                  transform={`translate(${point.x} ${point.y})`}
                  role="button"
                  tabIndex={0}
                  aria-label={`${node.display_name}，排队 ${
                    live?.queue_vehicles ?? "尚未运行"
                  }`}
                  onClick={() => onSelect(node.intersection_id)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      onSelect(node.intersection_id);
                    }
                  }}
                >
                  {node.role === "core_corridor" && (
                    <circle className="core-pulse" r="19" stroke={color} />
                  )}
                  <circle
                    className="node-hit"
                    r={selected ? 12 : 9}
                    fill={color}
                    filter={live ? "url(#nodeGlow)" : undefined}
                  />
                  <text className="node-index" y="27">
                    {node.display_id}
                  </text>
                  {live && (
                    <text className="phase-label" y="-18">
                      {live.phase_id}
                    </text>
                  )}
                  {incident && (
                    <text className="event-badge" x="14" y="-11">
                      事故
                    </text>
                  )}
                  {live?.emergency_priority_phase_id && (
                    <text className="event-badge emergency" x="14" y="2">
                      应急
                    </text>
                  )}
                </g>
              );
            })}
          </g>
        </svg>
        {!realtime.length && (
          <div className="canvas-empty">
            等待实验启动后接收真实路口状态
          </div>
        )}
        {activeDisturbances.length > 0 && (
          <div className="disturbance-rail" aria-label="当前场景扰动">
            <span>ACTIVE</span>
            {activeDisturbances.map((item) => (
              <strong key={item}>{disturbanceLabel(item)}</strong>
            ))}
          </div>
        )}
        {spillbackEdges.length > 0 && (
          <div className="spillback-readout">
            溢出边 {spillbackEdges.length}
          </div>
        )}
        <div className="map-caption">
          位置：EPSG:4326 投影 · 连线：SUMO 路网最短路生成图
        </div>
      </div>
    </section>
  );
}
