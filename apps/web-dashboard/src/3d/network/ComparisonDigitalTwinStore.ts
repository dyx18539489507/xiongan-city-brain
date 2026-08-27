import {
  applyDigitalTwinMessage,
  DigitalTwinProtocolError,
  DigitalTwinSequenceGapError,
  emptyDigitalTwinState,
  parseDigitalTwinMessage,
} from "./DigitalTwinStore";
import type {
  LiveComparisonSummary,
  PairedDigitalTwinMessage,
  PairedDigitalTwinState,
} from "./comparisonDigitalTwinTypes";

const emptyComparison: LiveComparisonSummary = {
  valid: true,
  reason: "等待创建实时对照",
  verdict: "warming_up",
  window_s: 60,
  warmup_remaining_s: 60,
  paired_sample_count: 0,
  network: {},
  intersections: [],
};

export const emptyPairedDigitalTwinState: PairedDigitalTwinState = {
  initialized: false,
  sequence: -1,
  status: "idle",
  pairId: null,
  simulationTimeS: 0,
  fairnessFingerprint: "",
  fairnessManifest: {},
  baselineAlgorithm: "fixed-time",
  candidateAlgorithm: "coordinated-max-pressure",
  baseline: emptyDigitalTwinState,
  candidate: emptyDigitalTwinState,
  comparison: emptyComparison,
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requireFiniteNumber(record: Record<string, unknown>, key: string): number {
  const value = record[key];
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new DigitalTwinProtocolError(`${key} must be a finite number`);
  }
  return value;
}

function parseEnvelope(value: unknown, role: "baseline" | "candidate") {
  if (!isRecord(value) || value.role !== role || typeof value.algorithm !== "string"
    || typeof value.experimentId !== "string") {
    throw new DigitalTwinProtocolError(`${role} comparison stream is invalid`);
  }
  return {
    role,
    algorithm: value.algorithm,
    experimentId: value.experimentId,
    message: parseDigitalTwinMessage(value.message),
  };
}

export function parsePairedDigitalTwinMessage(value: unknown): PairedDigitalTwinMessage {
  if (!isRecord(value)) {
    throw new DigitalTwinProtocolError("paired digital-twin message must be an object");
  }
  if (value.protocolVersion !== "1.0") {
    throw new DigitalTwinProtocolError("unsupported paired protocol version");
  }
  if (value.type !== "comparison-init" && value.type !== "comparison-delta") {
    throw new DigitalTwinProtocolError("unknown paired digital-twin message type");
  }
  const sequence = requireFiniteNumber(value, "sequence");
  const simulationTimeS = requireFiniteNumber(value, "simulationTimeS");
  if (!Number.isInteger(sequence) || sequence < 0 || typeof value.status !== "string"
    || typeof value.pairId !== "string" || typeof value.fairnessFingerprint !== "string"
    || !isRecord(value.fairnessManifest) || !isRecord(value.comparison)) {
    throw new DigitalTwinProtocolError("paired digital-twin metadata is invalid");
  }
  const baseline = parseEnvelope(value.baseline, "baseline");
  const candidate = parseEnvelope(value.candidate, "candidate");
  if ((baseline.message.experimentId !== null
      && baseline.message.experimentId !== baseline.experimentId)
    || (candidate.message.experimentId !== null
      && candidate.message.experimentId !== candidate.experimentId)) {
    throw new DigitalTwinProtocolError("paired stream experiment identity is inconsistent");
  }
  if (Math.abs(baseline.message.simulationTimeS - candidate.message.simulationTimeS) > 1e-6
    || Math.abs(simulationTimeS - baseline.message.simulationTimeS) > 1e-6) {
    throw new DigitalTwinProtocolError("paired streams do not share one simulation time");
  }
  return {
    type: value.type,
    protocolVersion: "1.0",
    sequence,
    status: value.status,
    pairId: value.pairId,
    simulationTimeS,
    fairnessFingerprint: value.fairnessFingerprint,
    fairnessManifest: value.fairnessManifest,
    baseline,
    candidate,
    comparison: value.comparison as LiveComparisonSummary,
  };
}

export function applyPairedDigitalTwinMessage(
  previous: PairedDigitalTwinState,
  message: PairedDigitalTwinMessage,
): PairedDigitalTwinState {
  if (message.type === "comparison-delta") {
    if (!previous.initialized) {
      throw new DigitalTwinProtocolError("paired delta received before initialization");
    }
    if (message.sequence <= previous.sequence) return previous;
    if (message.sequence !== previous.sequence + 1) {
      throw new DigitalTwinSequenceGapError(previous.sequence + 1, message.sequence);
    }
  }
  const baseline = applyDigitalTwinMessage(previous.baseline, message.baseline.message);
  const candidate = applyDigitalTwinMessage(previous.candidate, message.candidate.message);
  return {
    initialized: Boolean(message.pairId) && baseline.initialized && candidate.initialized,
    sequence: message.sequence,
    status: message.status,
    pairId: message.pairId || null,
    simulationTimeS: message.simulationTimeS,
    fairnessFingerprint: message.fairnessFingerprint,
    fairnessManifest: message.fairnessManifest,
    baselineAlgorithm: message.baseline.algorithm,
    candidateAlgorithm: message.candidate.algorithm,
    baseline,
    candidate,
    comparison: message.comparison,
  };
}
