/** Recover/finalize a stability report from its append-safe raw samples. */

import {readFile, writeFile} from "node:fs/promises";
import path from "node:path";

function slopePerMinute(samples, valueFor) {
  const points = samples
    .map((sample) => [Number(sample.wallElapsedS) / 60, Number(valueFor(sample))])
    .filter(([, value]) => Number.isFinite(value));
  if (points.length < 2) return null;
  const meanX = points.reduce((sum, [x]) => sum + x, 0) / points.length;
  const meanY = points.reduce((sum, [, y]) => sum + y, 0) / points.length;
  const numerator = points.reduce((sum, [x, y]) => sum + (x - meanX) * (y - meanY), 0);
  const denominator = points.reduce((sum, [x]) => sum + (x - meanX) ** 2, 0);
  return denominator > 0 ? numerator / denominator : null;
}

const [reportArgument, workspaceArgument = process.cwd()] = process.argv.slice(2);
if (!reportArgument) throw new Error("usage: node finalize_stability_report.mjs REPORT.json [WORKSPACE]");
const reportPath = path.resolve(reportArgument);
const workspace = path.resolve(workspaceArgument);
const report = JSON.parse(await readFile(reportPath, "utf8"));
const samples = Array.isArray(report.samples) ? report.samples : [];
const heaps = samples.map((sample) => sample.memory?.usedJsHeapBytes).filter(Number.isFinite);
const resultPath = path.join(workspace, "results", report.experimentId, "result.json");
let result = null;
try {
  result = JSON.parse(await readFile(resultPath, "utf8"));
} catch {
  // A failed/aborted run may legitimately have no result artifact.
}
report.terminatedByWallLimit =
  (samples.at(-1)?.experimentStatus === "running" || report.terminal?.status === "running") &&
  Number(samples.at(-1)?.wallElapsedS ?? 0) >= Number(report.maxWallS ?? Infinity) - 10;
report.claimBoundary = report.terminatedByWallLimit
  ? "The browser and SUMO stayed live until the wall-clock limit; the requested simulation duration was not completed."
  : "The reported terminal status and simulation endpoint must be checked together.";
report.analysis = {
  sampleCount: samples.length,
  wallDurationS: samples.at(-1)?.wallElapsedS ?? 0,
  simulationTimeStartS: samples[0]?.simulationTimeS ?? null,
  simulationTimeEndS: samples.at(-1)?.simulationTimeS ?? null,
  requestedSimulationDurationS: report.requestedSimulationDurationS,
  jsHeapStartBytes: heaps[0] ?? null,
  jsHeapEndBytes: heaps.at(-1) ?? null,
  jsHeapMaximumBytes: heaps.length ? Math.max(...heaps) : null,
  jsHeapLinearSlopeBytesPerMinute: slopePerMinute(
    samples,
    (sample) => sample.memory?.usedJsHeapBytes,
  ),
  jsHeapLastThirdSlopeBytesPerMinute: slopePerMinute(
    samples.slice(Math.floor(samples.length * 2 / 3)),
    (sample) => sample.memory?.usedJsHeapBytes,
  ),
  maximumVehicleCount: Math.max(0, ...samples.map((sample) => sample.vehicleCount ?? 0)),
  maximumBicycleCount: Math.max(0, ...samples.map((sample) => sample.bicycleCount ?? 0)),
  maximumPedestrianCount: Math.max(0, ...samples.map((sample) => sample.pedestrianCount ?? 0)),
  pageErrorCount: Array.isArray(report.pageErrors) ? report.pageErrors.length : 0,
  actualRun: result?.actual_run === true,
  backendMemoryPeakMb: result?.metrics?.memory_mb_peak ?? null,
  backendCpuMeanPercent: result?.metrics?.cpu_percent_mean ?? null,
  simulationRealtimeFactor: result?.metrics?.simulation_realtime_factor ?? null,
};
report.recoveredAt = new Date().toISOString();
await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
process.stdout.write(`${reportPath}\n`);
