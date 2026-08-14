/** Measure static scene download and initialization milestones in a browser. */

import {chromium} from "../../apps/web-dashboard/node_modules/playwright/index.mjs";

const [baseUrl = "http://127.0.0.1:5177"] = process.argv.slice(2);
const browser = await chromium.launch({headless: true});
const startedAt = Date.now();
const report = {baseUrl, responses: [], statuses: [], pageErrors: []};
try {
  const page = await browser.newPage({viewport: {width: 1280, height: 720}});
  page.on("pageerror", (error) => report.pageErrors.push(error.stack ?? error.message));
  page.on("response", (response) => {
    if (response.url().includes("/api/v1/scenes/") || response.url().includes("/api/v1/replays")) {
      report.responses.push({
        elapsedMs: Date.now() - startedAt,
        status: response.status(),
        url: response.url(),
      });
    }
  });
  await page.goto(baseUrl, {waitUntil: "domcontentloaded", timeout: 120_000});
  let previous = "";
  while (Date.now() - startedAt < 180_000) {
    const status = await page.locator(".scene-asset-state").textContent({timeout: 30_000});
    if (status !== previous) {
      report.statuses.push({elapsedMs: Date.now() - startedAt, status});
      previous = status ?? "";
    }
    if (await page.locator(".scene-asset-state.ready").count()) break;
    await page.waitForTimeout(100);
  }
  report.ready = (await page.locator(".scene-asset-state.ready").count()) > 0;
  report.elapsedMs = Date.now() - startedAt;
} finally {
  await browser.close();
}
process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
