/** Run one long, real SUMO + WebGL stability session and retain raw evidence. */

import {mkdir, writeFile} from "node:fs/promises";
import path from "node:path";
import {chromium} from "../../apps/web-dashboard/node_modules/playwright/index.mjs";

function argumentsFrom(argv) {
  const result = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index]?.replace(/^--/, "");
    if (key) result[key] = argv[index + 1];
  }
  return result;
}

async function jsonResponse(response) {
  if (!response.ok()) throw new Error(`${response.status()} ${await response.text()}`);
  return response.json();
}

function linearSlopePerMinute(samples, key) {
  const points = samples
    .map((sample) => [sample.wallElapsedS / 60, Number(sample[key])])
    .filter(([, value]) => Number.isFinite(value));
  if (points.length < 2) return null;
  const meanX = points.reduce((sum, [x]) => sum + x, 0) / points.length;
  const meanY = points.reduce((sum, [, y]) => sum + y, 0) / points.length;
  const numerator = points.reduce((sum, [x, y]) => sum + (x - meanX) * (y - meanY), 0);
  const denominator = points.reduce((sum, [x]) => sum + (x - meanX) ** 2, 0);
  return denominator > 0 ? numerator / denominator : null;
}

const args = argumentsFrom(process.argv.slice(2));
const frontend = args.frontend ?? "http://127.0.0.1:5177";
const durationS = Number(args.duration ?? 1800);
const sampleIntervalS = Number(args.interval ?? 20);
const maxWallS = Number(args["max-wall"] ?? 1200);
const profile = args.profile ?? "S02";
const seed = Number(args.seed ?? 91);
const algorithm = args.algorithm ?? "fixed-time";
const headless = (args.headless ?? "false").toLowerCase() === "true";
const output = path.resolve(args.output ?? "outputs/3d/benchmarks/stability-latest.json");
const report = {
  schemaVersion: "1.0",
  startedAt: new Date().toISOString(),
  frontend,
  requestedSimulationDurationS: durationS,
  sampleIntervalS,
  maxWallS,
  profile,
  seed,
  algorithm,
  mode: headless ? "headless-not-gpu-acceptance" : "headed-gpu-candidate",
  renderer: null,
  experimentId: null,
  pageErrors: [],
  samplingErrors: [],
  samples: [],
  terminal: null,
  replaySummary: null,
  analysis: null,
  terminatedByWallLimit: false,
};

await mkdir(path.dirname(output), {recursive: true});
const browser = await chromium.launch({
  headless,
  args: [
    "--disable-background-timer-throttling",
    "--disable-renderer-backgrounding",
    "--disable-backgrounding-occluded-windows",
  ],
});
let activeExperimentId = null;
try {
  const context = await browser.newContext({viewport: {width: 1280, height: 720}});
  const page = await context.newPage();
  page.on("pageerror", (error) => report.pageErrors.push(error.stack ?? error.message));
  await page.goto(frontend, {waitUntil: "domcontentloaded", timeout: 120_000});
  await page.locator(".scene-asset-state.ready").waitFor({timeout: 120_000});
  report.renderer = await page.evaluate(() => {
    const canvas = document.querySelector(".scene-canvas-shell canvas");
    const gl = canvas?.getContext("webgl2") ?? canvas?.getContext("webgl");
    const debug = gl?.getExtension("WEBGL_debug_renderer_info");
    return {
      vendor: debug ? gl.getParameter(debug.UNMASKED_VENDOR_WEBGL) : null,
      renderer: debug ? gl.getParameter(debug.UNMASKED_RENDERER_WEBGL) : null,
    };
  });
  const created = await jsonResponse(
    await context.request.post(`${frontend}/api/v1/experiments`, {
      data: {
        scenario_id: "xiongan_rongdong_20",
        profile,
        algorithm,
        seed,
        duration_s: durationS,
        gui: false,
      },
    }),
  );
  activeExperimentId = created.id;
  report.experimentId = activeExperimentId;
  await jsonResponse(
    await context.request.post(`${frontend}/api/v1/experiments/${activeExperimentId}/start`),
  );
  const wallStart = Date.now();
  let consecutiveSamplingTimeouts = 0;
  let maximumConsecutiveSamplingTimeouts = 0;
  while ((Date.now() - wallStart) / 1000 < maxWallS) {
    const terminal = await jsonResponse(
      await context.request.get(`${frontend}/api/v1/experiments/${activeExperimentId}`),
    );
    let sample;
    try {
      sample = await page.locator(".scene-telemetry").evaluate(
        (element) => {
          const raw = element.getAttribute("data-performance");
          const performanceSnapshot = raw ? JSON.parse(raw) : {};
          const memory = performance.memory
            ? {
                usedJsHeapBytes: performance.memory.usedJSHeapSize,
                totalJsHeapBytes: performance.memory.totalJSHeapSize,
              }
            : null;
          return {...performanceSnapshot, memory};
        },
        undefined,
        {timeout: 10_000},
      );
      consecutiveSamplingTimeouts = 0;
    } catch (error) {
      if (!(error instanceof Error) || error.name !== "TimeoutError") throw error;
      consecutiveSamplingTimeouts += 1;
      maximumConsecutiveSamplingTimeouts = Math.max(
        maximumConsecutiveSamplingTimeouts,
        consecutiveSamplingTimeouts,
      );
      report.samplingErrors.push({
        capturedAt: new Date().toISOString(),
        wallElapsedS: Math.round((Date.now() - wallStart) / 100) / 10,
        consecutive: consecutiveSamplingTimeouts,
        message: error.message,
      });
      await writeFile(output, `${JSON.stringify(report, null, 2)}\n`, "utf8");
      if (consecutiveSamplingTimeouts >= 3) {
        throw new Error("scene telemetry was unavailable for at least 30 consecutive seconds");
      }
      continue;
    }
    report.samples.push({
      capturedAt: new Date().toISOString(),
      wallElapsedS: Math.round((Date.now() - wallStart) / 100) / 10,
      experimentStatus: terminal.status,
      ...sample,
    });
    await writeFile(output, `${JSON.stringify(report, null, 2)}\n`, "utf8");
    if (["completed", "failed", "stopped"].includes(terminal.status)) {
      report.terminal = terminal;
      activeExperimentId = null;
      break;
    }
    await page.waitForTimeout(sampleIntervalS * 1000);
  }
  if (activeExperimentId) {
    report.terminatedByWallLimit = true;
    await context.request.post(`${frontend}/api/v1/experiments/${activeExperimentId}/stop`);
    for (let attempt = 0; attempt < 20; attempt += 1) {
      report.terminal = await jsonResponse(
        await context.request.get(`${frontend}/api/v1/experiments/${activeExperimentId}`),
      );
      if (["completed", "failed", "stopped"].includes(report.terminal.status)) break;
      await page.waitForTimeout(250);
    }
    activeExperimentId = null;
  }
  const replayList = await jsonResponse(await context.request.get(`${frontend}/api/v1/replays`));
  const replayItems = Array.isArray(replayList)
    ? replayList
    : Array.isArray(replayList.items)
      ? replayList.items
      : [];
  report.replaySummary =
    replayItems.find((item) => item.experimentId === report.experimentId) ?? null;
  const heapSamples = report.samples
    .map((sample) => sample.memory?.usedJsHeapBytes)
    .filter(Number.isFinite);
  report.analysis = {
    sampleCount: report.samples.length,
    wallDurationS: report.samples.at(-1)?.wallElapsedS ?? 0,
    simulationTimeStartS: report.samples[0]?.simulationTimeS ?? null,
    simulationTimeEndS: report.samples.at(-1)?.simulationTimeS ?? null,
    jsHeapStartBytes: heapSamples[0] ?? null,
    jsHeapEndBytes: heapSamples.at(-1) ?? null,
    jsHeapMaximumBytes: heapSamples.length ? Math.max(...heapSamples) : null,
    jsHeapLinearSlopeBytesPerMinute: linearSlopePerMinute(
      report.samples.map((sample) => ({
        ...sample,
        usedJsHeapBytes: sample.memory?.usedJsHeapBytes,
      })),
      "usedJsHeapBytes",
    ),
    maximumVehicleCount: Math.max(...report.samples.map((sample) => sample.vehicleCount ?? 0)),
    maximumBicycleCount: Math.max(...report.samples.map((sample) => sample.bicycleCount ?? 0)),
    maximumPedestrianCount: Math.max(...report.samples.map((sample) => sample.pedestrianCount ?? 0)),
    samplingTimeoutCount: report.samplingErrors.length,
    maximumConsecutiveSamplingTimeouts,
  };
  report.completedAt = new Date().toISOString();
  await writeFile(output, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  process.stdout.write(`${output}\n`);
} finally {
  if (activeExperimentId) {
    try {
      const context = browser.contexts()[0];
      await context?.request.post(`${frontend}/api/v1/experiments/${activeExperimentId}/stop`);
    } catch {
      // The caller is responsible for scoped server cleanup.
    }
  }
  await browser.close();
}
