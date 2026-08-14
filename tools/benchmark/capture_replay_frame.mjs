import {mkdir} from "node:fs/promises";
import path from "node:path";
import {chromium} from "../../apps/web-dashboard/node_modules/playwright/index.mjs";

const [baseUrl, experimentId, simulationTime, viewLabel, outputPath] = process.argv.slice(2);
if (!baseUrl || !experimentId || !simulationTime || !viewLabel || !outputPath) {
  throw new Error(
    "usage: node capture_replay_frame.mjs BASE_URL EXPERIMENT_ID TIME_S VIEW_LABEL OUTPUT.png",
  );
}

await mkdir(path.dirname(path.resolve(outputPath)), {recursive: true});
const browser = await chromium.launch({headless: true});
try {
  const page = await browser.newPage({viewport: {width: 1280, height: 720}});
  await page.goto(baseUrl, {waitUntil: "networkidle", timeout: 120_000});
  await page.locator(".scene-asset-state.ready").waitFor({timeout: 120_000});
  const replaySelect = page.locator(".replay-deck > label select").first();
  await replaySelect.selectOption(experimentId);
  await page.getByRole("button", {name: "载入", exact: true}).click();
  await page.locator(".replay-mode.replay").waitFor({timeout: 120_000});
  const slider = page.getByLabel("回放时间");
  await slider.evaluate((element, value) => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )?.set;
    setter?.call(element, value);
    element.dispatchEvent(new Event("input", {bubbles: true}));
    element.dispatchEvent(new Event("change", {bubbles: true}));
  }, simulationTime);
  await page.waitForFunction(
    (target) => {
      const element = document.querySelector(".scene-telemetry");
      const payload = element?.getAttribute("data-performance");
      if (!payload) return false;
      return Number(JSON.parse(payload).simulationTimeS ?? 0) >= Number(target);
    },
    simulationTime,
    {timeout: 60_000},
  );
  await page.getByLabel("三维视角").getByRole("button", {name: viewLabel, exact: true}).click();
  await page.waitForTimeout(2_500);
  await page.screenshot({path: outputPath});
  const telemetry = await page.locator(".scene-telemetry").getAttribute("data-performance");
  process.stdout.write(`${JSON.stringify({outputPath, experimentId, simulationTime, viewLabel, telemetry})}\n`);
} finally {
  await browser.close();
}
