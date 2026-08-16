export type LaneTrafficKind = "unknown" | "empty" | "free" | "slow" | "congested" | "severe";

export type LaneTrafficInput = {
  vehicleCount: number;
  queueVehicleCount: number;
  queueLengthM: number;
  occupancy: number;
  meanSpeedMS: number;
  speedLimitMS: number;
  laneLengthM?: number;
};

export type LaneTrafficState = {
  kind: LaneTrafficKind;
  pressure: number;
};

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value));
}

function kindForPressure(pressure: number): Exclude<LaneTrafficKind, "unknown" | "empty"> {
  if (pressure >= .82) return "severe";
  if (pressure >= .6) return "congested";
  if (pressure >= .35) return "slow";
  return "free";
}

/**
 * Derives display semantics only from a real lane sample. A SUMO lane with no
 * vehicles reports a mean speed of zero; that is an empty lane, not congestion.
 */
export function classifyLaneTraffic(input: LaneTrafficInput | null | undefined): LaneTrafficState {
  if (!input) return {kind: "unknown", pressure: 0};
  const values = [
    input.vehicleCount,
    input.queueVehicleCount,
    input.queueLengthM,
    input.occupancy,
    input.meanSpeedMS,
    input.speedLimitMS,
  ];
  if (values.some((value) => !Number.isFinite(value))) return {kind: "unknown", pressure: 0};

  const vehicleCount = Math.max(0, input.vehicleCount);
  const queueVehicleCount = Math.max(0, input.queueVehicleCount);
  const queueLengthM = Math.max(0, input.queueLengthM);
  const occupancy = clamp01(input.occupancy);
  // SUMO's vehicle count is the presence truth for the motor-traffic layer.
  // Ignore a stale aggregate occupancy/queue length when both live counts are
  // zero; otherwise an empty lane can remain orange/red for one or more ticks.
  if (vehicleCount === 0 && queueVehicleCount === 0) {
    return {kind: "empty", pressure: 0};
  }

  const speedLimit = Math.max(1, input.speedLimitMS);
  const speedDeficit = clamp01(1 - Math.max(0, input.meanSpeedMS) / speedLimit);
  // A single slow vehicle is not a traffic jam. Speed becomes strong evidence
  // only when SUMO also reports meaningful volume, queueing or occupancy.
  const volumeEvidence = Math.max(
    occupancy,
    clamp01(vehicleCount / 8),
    clamp01(queueVehicleCount / 6),
  );
  const speedPressure = speedDeficit * volumeEvidence;
  const queueReferenceM = Math.max(30, Math.min(120, input.laneLengthM ?? 120));
  const queuePressure = Math.max(
    clamp01(queueLengthM / queueReferenceM),
    clamp01(queueVehicleCount / 8),
  );
  const pressure = Math.max(occupancy, speedPressure, queuePressure);
  return {kind: kindForPressure(pressure), pressure};
}
