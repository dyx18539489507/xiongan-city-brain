/** Shared presentation tokens for DOM and Canvas. Canvas colors must live here. */
export const mapTheme = {
  background: "#081114",
  backgroundDeep: "#050a0d",
  land: "#0b171a",
  block: "#102024",
  blockEdge: "rgba(126, 153, 157, .10)",
  building: "rgba(41, 60, 65, .72)",
  buildingEdge: "rgba(138, 160, 164, .13)",
  vegetation: "rgba(24, 67, 55, .42)",
  water: "rgba(17, 54, 72, .45)",
  roadEdge: "rgba(3, 8, 10, .96)",
  roadSurface: "rgba(48, 61, 66, .94)",
  roadSurfaceMuted: "rgba(38, 50, 55, .64)",
  bicycleLane: "rgba(35, 83, 78, .72)",
  pedestrianLane: "rgba(64, 73, 76, .62)",
  junction: "rgba(52, 64, 68, .94)",
  laneMarking: "rgba(204, 215, 211, .42)",
  roadEdgeLine: "rgba(219, 229, 225, .28)",
  crossing: "rgba(223, 230, 225, .54)",
  text: "#dce7e5",
  textSecondary: "#93a6a5",
  textMuted: "#647879",
  trafficFree: "#42bd8b",
  trafficSlow: "#e6bc62",
  trafficCongested: "#e78545",
  trafficSevere: "#e4564b",
  signalRed: "#eb5c55",
  signalYellow: "#f1c75b",
  signalGreen: "#44c989",
  car: "#d4dde0",
  bus: "#4e9fcc",
  truck: "#d59d54",
  bicycle: "#65c7b9",
  pedestrian: "#cedbd7",
  algorithm: "#8f7cf0",
  cloud: "#5a9fe4",
  edge: "#45c7ba",
  warning: "#e6b861",
  danger: "#e65d52",
  selection: "#eef7f5",
  shadow: "rgba(0, 0, 0, .5)",
} as const;

export function trafficColor(level: number): string {
  if (level >= 0.82) return mapTheme.trafficSevere;
  if (level >= 0.6) return mapTheme.trafficCongested;
  if (level >= 0.35) return mapTheme.trafficSlow;
  return mapTheme.trafficFree;
}
