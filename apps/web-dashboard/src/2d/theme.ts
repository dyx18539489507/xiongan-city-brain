/** Shared presentation tokens for DOM and Canvas. Canvas colors must live here. */
export const mapTheme = {
  background: "#eaf1ec",
  backgroundDeep: "#f7f8f3",
  land: "#f2efe5",
  block: "#e7eee4",
  blockEdge: "rgba(105, 128, 126, .18)",
  building: "rgba(218, 218, 207, .82)",
  buildingEdge: "rgba(116, 133, 134, .22)",
  vegetation: "rgba(183, 211, 177, .58)",
  water: "rgba(180, 215, 237, .72)",
  roadEdge: "rgba(167, 180, 178, .88)",
  roadSurface: "rgba(250, 251, 248, .98)",
  roadSurfaceMuted: "rgba(231, 235, 230, .88)",
  bicycleLane: "rgba(178, 222, 212, .92)",
  pedestrianLane: "rgba(226, 223, 212, .92)",
  junction: "rgba(246, 248, 244, .98)",
  laneMarking: "rgba(110, 130, 134, .48)",
  roadEdgeLine: "rgba(86, 111, 119, .38)",
  crossing: "rgba(91, 113, 118, .52)",
  text: "#14324b",
  textSecondary: "#3f6176",
  textMuted: "#78909d",
  trafficFree: "#0fa891",
  trafficSlow: "#e6a23b",
  trafficCongested: "#ef763e",
  trafficSevere: "#d94f4a",
  signalRed: "#dc4c4c",
  signalYellow: "#e9aa32",
  signalGreen: "#17a56f",
  car: "#315a70",
  bus: "#277fae",
  truck: "#c57c3a",
  bicycle: "#0d9187",
  pedestrian: "#52758a",
  algorithm: "#6f63d6",
  cloud: "#2b82c4",
  edge: "#079a92",
  warning: "#d7932f",
  danger: "#d84f49",
  selection: "#075f8f",
  shadow: "rgba(39, 67, 78, .22)",
} as const;

export function trafficColor(level: number): string {
  if (level >= 0.82) return mapTheme.trafficSevere;
  if (level >= 0.6) return mapTheme.trafficCongested;
  if (level >= 0.35) return mapTheme.trafficSlow;
  return mapTheme.trafficFree;
}
