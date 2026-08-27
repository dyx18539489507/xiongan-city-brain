import type {
  DigitalTwinConnection,
  DigitalTwinMessage,
  DigitalTwinState,
} from "./digitalTwinTypes";

export type ComparisonVerdict =
  | "warming_up"
  | "improved"
  | "mixed"
  | "stable"
  | "worse"
  | "invalid";

export type MetricComparison = {
  baseline: number;
  candidate: number;
  delta: number;
  benefit: number;
  benefit_percent: number | null;
  unit: string;
  higher_better: boolean;
  trend: "improved" | "stable" | "worse";
};

export type ApproachComparison = {
  lane_id: string;
  direction: string;
  movement: string;
  verdict: "improved" | "stable" | "worse";
  label: string;
  baseline: Record<string, number>;
  candidate: Record<string, number>;
  delta: Record<string, number>;
};

export type IntersectionComparison = {
  intersection_id: string;
  verdict: "improved" | "stable" | "worse";
  label: string;
  baseline: Record<string, number>;
  candidate: Record<string, number>;
  delta: Record<string, number>;
  approaches: ApproachComparison[];
};

export type LiveComparisonSummary = {
  valid: boolean;
  reason: string | null;
  verdict: ComparisonVerdict;
  window_s: number;
  warmup_remaining_s?: number;
  paired_sample_count: number;
  simulation_time_s?: number;
  network: Record<string, MetricComparison>;
  intersections: IntersectionComparison[];
  counts?: {
    improved_intersections: number;
    stable_intersections: number;
    worse_intersections: number;
  };
};

export type ComparisonStreamEnvelope = {
  role: "baseline" | "candidate";
  algorithm: string;
  experimentId: string;
  message: DigitalTwinMessage;
};

export type PairedDigitalTwinMessage = {
  type: "comparison-init" | "comparison-delta";
  protocolVersion: "1.0";
  sequence: number;
  status: string;
  pairId: string;
  simulationTimeS: number;
  fairnessFingerprint: string;
  fairnessManifest: Record<string, unknown>;
  baseline: ComparisonStreamEnvelope;
  candidate: ComparisonStreamEnvelope;
  comparison: LiveComparisonSummary;
};

export type PairedDigitalTwinState = {
  initialized: boolean;
  sequence: number;
  status: string;
  pairId: string | null;
  simulationTimeS: number;
  fairnessFingerprint: string;
  fairnessManifest: Readonly<Record<string, unknown>>;
  baselineAlgorithm: string;
  candidateAlgorithm: string;
  baseline: DigitalTwinState;
  candidate: DigitalTwinState;
  comparison: LiveComparisonSummary;
};

export type PairedDigitalTwinStream = {
  connection: DigitalTwinConnection;
  state: PairedDigitalTwinState;
  issue: string | null;
  reset?: () => void;
};
