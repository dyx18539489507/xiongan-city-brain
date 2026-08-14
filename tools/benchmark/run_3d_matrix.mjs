/** Collect structured WebGL measurements from the real dashboard and API. */

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

function average(values) {
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
}

function round(value, digits = 1) {
  const scale = 10 ** digits;
  return Math.round(value * scale) / scale;
}

async function jsonResponse(response) {
  if (!response.ok()) {
    throw new Error(`${response.status()} ${await response.text()}`);
  }
  return response.json();
}

async function experimentStatus(request, baseUrl, experimentId) {
  return jsonResponse(await request.get(`${baseUrl}/api/v1/experiments/${experimentId}`));
}

async function waitForTerminal(request, baseUrl, experimentId, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const record = await experimentStatus(request, baseUrl, experimentId);
    if (["completed", "stopped", "failed"].includes(record.status)) return record;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  return experimentStatus(request, baseUrl, experimentId);
}

async function readPerformance(page) {
  return page.locator(".scene-telemetry").evaluate((element) => {
    const raw = element.getAttribute("data-performance");
    if (!raw) throw new Error("structured performance snapshot is unavailable");
    const snapshot = JSON.parse(raw);
    const memory = performance.memory
      ? {
          usedJsHeapSize: performance.memory.usedJSHeapSize,
          totalJsHeapSize: performance.memory.totalJSHeapSize,
          jsHeapSizeLimit: performance.memory.jsHeapSizeLimit,
        }
      : null;
    return {...snapshot, memory};
  });
}

function aggregate(samples) {
  const numeric = (key) => samples.map((sample) => Number(sample[key] ?? 0));
  const heaps = samples.map((sample) => sample.memory?.usedJsHeapSize).filter(Number.isFinite);
  return {
    samples: samples.length,
    averageFps: round(average(numeric("averageFps"))),
    minimumP1Fps: round(Math.min(...numeric("p1Fps"))),
    averageFrameTimeMs: round(average(numeric("averageFrameTimeMs"))),
    maximumFrameTimeMs: round(Math.max(...numeric("maxFrameTimeMs"))),
    maximumDrawCalls: Math.max(...numeric("drawCalls")),
    maximumTriangles: Math.max(...numeric("triangles")),
    maximumGeometries: Math.max(...numeric("geometries")),
    maximumTextures: Math.max(...numeric("textures")),
    maximumUsedJsHeapBytes: heaps.length ? Math.max(...heaps) : null,
    qualityLevels: [...new Set(samples.map((sample) => sample.quality?.level))],
    renderScales: [...new Set(samples.map((sample) => sample.quality?.renderScale))],
    simulationTimeStartS: samples[0]?.simulationTimeS ?? null,
    simulationTimeEndS: samples.at(-1)?.simulationTimeS ?? null,
    maximumVehicleCount: Math.max(...numeric("vehicleCount")),
    maximumBicycleCount: Math.max(...numeric("bicycleCount")),
    maximumPedestrianCount: Math.max(...numeric("pedestrianCount")),
  };
}

const args = argumentsFrom(process.argv.slice(2));
const baseUrl = args.frontend ?? "http://127.0.0.1:5185";
const profiles = (args.profiles ?? "S01,S02,S03,S04,S05").split(",").filter(Boolean);
const conditions = (args.conditions ?? "clear,night,rain").split(",").filter(Boolean);
const views = (args.views ?? "overview,corridor,junction").split(",").filter(Boolean);
const durationS = Number(args.duration ?? 900);
const warmupS = Number(args.warmup ?? 5);
const sampleS = Number(args.sample ?? 10);
const algorithm = args.algorithm ?? "fixed-time";
const seed = Number(args.seed ?? 52);
const headless = (args.headless ?? "false").toLowerCase() === "true";
const outputPath = path.resolve(args.output ?? "outputs/3d/benchmarks/latest.json");
const screenshotRoot = outputPath.replace(/\.json$/i, "-screenshots");
const viewLabels = {overview: "全域", corridor: "走廊", junction: "选中路口"};
const conditionLabels = {clear: "晴", night: "夜", rain: "雨"};
const pageErrors = [];
const report = {
  schemaVersion: "1.0",
  startedAt: new Date().toISOString(),
  mode: headless ? "headless-structural-not-gpu-acceptance" : "headed-gpu-candidate",
  claimBoundary: headless
    ? "Headless measurements validate the harness only and must not be reported as MX250 FPS."
    : "Headed measurements are a candidate; verify the WebGL renderer and system GPU telemetry before MX250 acceptance.",
  baseUrl,
  viewport: {width: 1280, height: 720},
  durationS,
  warmupS,
  sampleS,
  algorithm,
  seed,
  profiles,
  conditions,
  views,
  browser: null,
  pageErrors,
  runs: [],
};

await mkdir(path.dirname(outputPath), {recursive: true});
await mkdir(screenshotRoot, {recursive: true});
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
  const context = await browser.newContext({viewport: report.viewport, deviceScaleFactor: 1});
  const page = await context.newPage();
  page.on("pageerror", (error) => pageErrors.push(error.stack ?? error.message));
  await page.goto(baseUrl, {waitUntil: "domcontentloaded"});
  await page.getByRole("region", {name: "雄安窄路密网 20 路口数字孪生"})
    .getByRole("status")
    .waitFor({state: "visible", timeout: 60_000});
  await page.getByText("20 / 20", {exact: true}).waitFor({state: "visible", timeout: 60_000});
  report.browser = await page.evaluate(() => {
    const canvas = document.querySelector(".scene-canvas-shell canvas");
    const gl = canvas?.getContext("webgl2") ?? canvas?.getContext("webgl");
    const debug = gl?.getExtension("WEBGL_debug_renderer_info");
    return {
      userAgent: navigator.userAgent,
      devicePixelRatio: window.devicePixelRatio,
      webglVendor: debug ? gl.getParameter(debug.UNMASKED_VENDOR_WEBGL) : null,
      webglRenderer: debug ? gl.getParameter(debug.UNMASKED_RENDERER_WEBGL) : null,
    };
  });

  for (const profile of profiles) {
    await page.getByLabel("仿真工况").selectOption(profile);
    const created = await jsonResponse(
      await context.request.post(`${baseUrl}/api/v1/experiments`, {
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
    await jsonResponse(
      await context.request.post(`${baseUrl}/api/v1/experiments/${activeExperimentId}/start`),
    );
    await page.waitForFunction(
      ({experimentId}) => {
        const raw = document.querySelector(".scene-telemetry")?.getAttribute("data-performance");
        if (!raw) return false;
        const snapshot = JSON.parse(raw);
        return (
          snapshot.experimentId === experimentId &&
          snapshot.entityConnection === "online" &&
          Number(snapshot.simulationTimeS) >= 1
        );
      },
      {experimentId: activeExperimentId},
      {timeout: 90_000},
    );
    const profileRun = {profile, experimentId: activeExperimentId, measurements: []};
    report.runs.push(profileRun);

    for (const condition of conditions) {
      const conditionLabel = conditionLabels[condition];
      if (!conditionLabel) throw new Error(`unsupported condition: ${condition}`);
      await page.getByRole("button", {name: `环境-${conditionLabel}`}).click();
      for (const view of views) {
        const viewLabel = viewLabels[view];
        if (!viewLabel) throw new Error(`unsupported view: ${view}`);
        await page.getByRole("button", {name: viewLabel, exact: true}).click();
        await page.waitForTimeout(warmupS * 1000);
        await page.waitForFunction(
          ({condition, view}) => {
            const raw = document
              .querySelector(".scene-telemetry")
              ?.getAttribute("data-performance");
            if (!raw) return false;
            const snapshot = JSON.parse(raw);
            return (
              snapshot.view === view &&
              snapshot.weatherMode === condition &&
              Number(snapshot.sampleCount ?? 0) >= 20
            );
          },
          {condition, view},
          {timeout: 60_000},
        );
        const before = await experimentStatus(context.request, baseUrl, activeExperimentId);
        const samples = [];
        for (let second = 0; second < sampleS; second += 1) {
          samples.push(await readPerformance(page));
          await page.waitForTimeout(1000);
        }
        const after = await experimentStatus(context.request, baseUrl, activeExperimentId);
        const screenshot = path.join(screenshotRoot, `${profile}_${condition}_${view}.png`);
        await page.screenshot({path: screenshot});
        profileRun.measurements.push({
          condition,
          view,
          experimentStatusBefore: before.status,
          experimentStatusAfter: after.status,
          concurrentWithSumo: before.status === "running" && after.status === "running",
          screenshot,
          ...aggregate(samples),
        });
      }
    }
    const current = await experimentStatus(context.request, baseUrl, activeExperimentId);
    if (["running", "paused"].includes(current.status)) {
      await context.request.post(`${baseUrl}/api/v1/experiments/${activeExperimentId}/stop`);
    }
    profileRun.terminal = await waitForTerminal(
      context.request,
      baseUrl,
      activeExperimentId,
    );
    activeExperimentId = null;
    await writeFile(outputPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  }
  report.completedAt = new Date().toISOString();
  await writeFile(outputPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  console.log(outputPath);
} finally {
  if (activeExperimentId) {
    try {
      const context = browser.contexts()[0];
      await context?.request.post(`${baseUrl}/api/v1/experiments/${activeExperimentId}/stop`);
    } catch {
      // The PowerShell wrapper still performs scoped process cleanup.
    }
  }
  await browser.close();
}
