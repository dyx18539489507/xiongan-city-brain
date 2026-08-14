/** Merge independently captured profile runs after validating matrix integrity. */

import {readFile, writeFile} from "node:fs/promises";
import path from "node:path";

const [outputArgument, ...sourceArguments] = process.argv.slice(2);
if (!outputArgument || sourceArguments.length < 1) {
  throw new Error("usage: node merge_3d_matrix.mjs OUTPUT.json SOURCE.json [...]");
}

const sources = await Promise.all(
  sourceArguments.map(async (source) => ({
    path: path.resolve(source),
    report: JSON.parse(await readFile(path.resolve(source), "utf8")),
  })),
);
const expectedProfiles = ["S01", "S02", "S03", "S04", "S05"];
const expectedConditions = ["clear", "night", "rain"];
const expectedViews = ["overview", "corridor", "junction"];
const renderer = sources[0]?.report.browser?.webglRenderer;
if (!renderer || !renderer.includes("NVIDIA GeForce MX250")) {
  throw new Error(`first report is not an MX250 report: ${renderer ?? "missing"}`);
}

const runByProfile = new Map();
for (const source of sources) {
  if (source.report.browser?.webglRenderer !== renderer) {
    throw new Error(`renderer mismatch in ${source.path}`);
  }
  if (source.report.pageErrors?.length) {
    throw new Error(`page errors present in ${source.path}`);
  }
  for (const run of source.report.runs ?? []) {
    if (!run.measurements?.length) continue;
    if (runByProfile.has(run.profile)) throw new Error(`duplicate profile ${run.profile}`);
    const screenshotDirectory = `${path.basename(source.path, ".json")}-screenshots`;
    runByProfile.set(run.profile, {
      ...run,
      measurements: run.measurements.map((measurement) => ({
        ...measurement,
        screenshot: `outputs/3d/benchmarks/${screenshotDirectory}/${path.basename(
          measurement.screenshot ?? `${run.profile}_${measurement.condition}_${measurement.view}.png`,
        )}`,
      })),
    });
  }
}

const runs = expectedProfiles.map((profile) => {
  const run = runByProfile.get(profile);
  if (!run) throw new Error(`missing profile ${profile}`);
  const keys = new Set(run.measurements.map((item) => `${item.condition}/${item.view}`));
  for (const condition of expectedConditions) {
    for (const view of expectedViews) {
      if (!keys.has(`${condition}/${view}`)) throw new Error(`missing ${profile}/${condition}/${view}`);
    }
  }
  if (run.measurements.length !== 9) {
    throw new Error(`${profile} has ${run.measurements.length} measurements instead of 9`);
  }
  return run;
});

const measurements = runs.flatMap((run) =>
  run.measurements.map((measurement) => ({profile: run.profile, ...measurement})),
);
const values = (key) => measurements.map((item) => Number(item[key]));
const average = (items) => items.reduce((sum, value) => sum + value, 0) / items.length;
const sortedFps = values("averageFps").sort((a, b) => a - b);
const summary = {
  combinations: measurements.length,
  allConcurrentWithSumo: measurements.every((item) => item.concurrentWithSumo === true),
  averageFps: average(values("averageFps")),
  medianFps: sortedFps[Math.floor(sortedFps.length / 2)],
  minimumAverageFps: Math.min(...values("averageFps")),
  maximumAverageFps: Math.max(...values("averageFps")),
  minimumP1Fps: Math.min(...values("minimumP1Fps")),
  maximumFrameTimeMs: Math.max(...values("maximumFrameTimeMs")),
  maximumDrawCalls: Math.max(...values("maximumDrawCalls")),
  maximumTriangles: Math.max(...values("maximumTriangles")),
  maximumUsedJsHeapBytes: Math.max(...values("maximumUsedJsHeapBytes")),
  qualityLevels: [...new Set(measurements.flatMap((item) => item.qualityLevels))],
};
const output = {
  schemaVersion: "1.0-merged",
  createdAt: new Date().toISOString(),
  claimBoundary: "Validated merge of profile runs captured with identical MX250/browser conditions.",
  sourceReports: sources.map((source) =>
    path.relative(process.cwd(), source.path).replaceAll("\\", "/"),
  ),
  browser: sources[0].report.browser,
  profiles: expectedProfiles,
  conditions: expectedConditions,
  views: expectedViews,
  pageErrors: [],
  runs,
  summary,
};
const outputPath = path.resolve(outputArgument);
await writeFile(outputPath, `${JSON.stringify(output, null, 2)}\n`, "utf8");
process.stdout.write(`${JSON.stringify({outputPath, summary}, null, 2)}\n`);
