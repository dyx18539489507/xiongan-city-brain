/** Probe a recorded high-load frame with the real WebGL renderer. */

import {writeFile} from "node:fs/promises";
import path from "node:path";
import {chromium} from "../../apps/web-dashboard/node_modules/playwright/index.mjs";

const [baseUrl, experimentId, simulationTime, outputPath] = process.argv.slice(2);
if (!baseUrl || !experimentId || !simulationTime || !outputPath) {
  throw new Error(
    "usage: node probe_replay_performance.mjs BASE_URL EXPERIMENT_ID TIME_S OUTPUT.json",
  );
}

const browser = await chromium.launch({
  headless: false,
  args: [
    "--disable-background-timer-throttling",
    "--disable-renderer-backgrounding",
    "--disable-backgrounding-occluded-windows",
  ],
});
const report = {
  capturedAt: new Date().toISOString(),
  baseUrl,
  experimentId,
  simulationTimeS: Number(simulationTime),
  renderer: null,
  pageErrors: [],
  samples: [],
};
try {
  const page = await browser.newPage({viewport: {width: 1280, height: 720}});
  page.on("pageerror", (error) => report.pageErrors.push(error.stack ?? error.message));
  await page.goto(baseUrl, {waitUntil: "domcontentloaded", timeout: 120_000});
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
  const replaySelect = page.locator(".replay-deck > label select").first();
  await replaySelect.selectOption(experimentId);
  await page.getByRole("button", {name: "载入", exact: true}).click();
  await page.locator(".replay-mode.replay").waitFor({timeout: 120_000});
  const slider = page.getByLabel("回放时间");
  await slider.evaluate((element, value) => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    setter?.call(element, value);
    element.dispatchEvent(new Event("input", {bubbles: true}));
    element.dispatchEvent(new Event("change", {bubbles: true}));
  }, simulationTime);
  await page.waitForFunction(
    (target) => {
      const payload = document.querySelector(".scene-telemetry")?.getAttribute("data-performance");
      return payload && Number(JSON.parse(payload).simulationTimeS ?? 0) >= Number(target);
    },
    simulationTime,
    {timeout: 120_000},
  );
  await page.getByLabel("三维视角").getByRole("button", {name: "全域", exact: true}).click();
  await page.waitForTimeout(5_000);
  for (let index = 0; index < 10; index += 1) {
    const raw = await page.locator(".scene-telemetry").getAttribute("data-performance", {
      timeout: 60_000,
    });
    report.samples.push(raw ? JSON.parse(raw) : null);
    await page.waitForTimeout(1_000);
  }
} finally {
  await browser.close();
  await writeFile(path.resolve(outputPath), `${JSON.stringify(report, null, 2)}\n`, "utf8");
}

const samples = report.samples.filter(Boolean);
const average = (key) =>
  samples.length ? samples.reduce((sum, sample) => sum + Number(sample[key] ?? 0), 0) / samples.length : null;
process.stdout.write(`${JSON.stringify({
  outputPath: path.resolve(outputPath),
  renderer: report.renderer,
  pageErrors: report.pageErrors.length,
  samples: samples.length,
  averageFps: average("averageFps"),
  averageDrawCalls: average("drawCalls"),
  maximumDrawCalls: samples.length ? Math.max(...samples.map((sample) => sample.drawCalls)) : null,
  vehicleCount: samples.at(-1)?.vehicleCount ?? null,
  quality: samples.at(-1)?.quality ?? null,
}, null, 2)}\n`);
