import {expect, test} from "@playwright/test";
import path from "node:path";

test("renders the map-first SUMO 2D cockpit and switches views", async ({page}) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.stack ?? error.message));
  await page.goto("/?view=2d");
  const canvas = page.getByLabel("SUMO 实时二维交通数字孪生地图");
  await expect(canvas).toBeVisible({timeout: 180_000});
  await expect(page.locator(".scene-loading")).toHaveCount(0, {timeout: 180_000});
  expect(pageErrors).toEqual([]);
  await expect(page.getByRole("heading", {name: "雄安城市交通数字孪生"})).toBeVisible();
  await expect(page.getByText("SUMO / TraCI LIVE")).toBeVisible();
  await expect(page.getByText(/20\s*信号机/)).toBeVisible();
  await expect(page.getByRole("button", {name: /2D/})).toHaveClass(/active/);
  const profile = page.getByLabel("仿真工况");
  await expect(profile.first().getByRole("option")).toHaveCount(8);
  await profile.first().selectOption("S04");
  await expect(profile.first()).toHaveValue("S04");
  await expect(
    page.getByRole("option", {name: "主办方20个独立路口复现集"}),
  ).toHaveAttribute("disabled", "");
  await page.getByRole("button", {name: /3D/}).click();
  await expect(page.locator(".twin-cockpit.view-3d")).toBeVisible();
  await page.getByRole("button", {name: /2D/}).click();
  await expect(canvas).toBeVisible();
});

test("loads the WebGL digital twin and applies real scene controls", async ({page}) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.stack ?? error.message));

  await page.goto("/");
  await page.getByRole("button", {name: /3D/}).click();
  const scene = page.getByRole("region", {
    name: "雄安交通 Unity 三维数字孪生",
  });
  const ready = scene.getByRole("status").filter({hasText: "SUMO STATIC READY"});
  await expect(ready).toContainText(
    "SUMO STATIC READY",
    {timeout: 180_000},
  );
  await expect(scene.getByText("20 / 20", {exact: true})).toBeVisible();
  await expect(ready).toContainText("CAMERA MONITOR");
  await page.waitForTimeout(1200);

  await page.screenshot({
    path: path.resolve(process.cwd(), "../../outputs/3d/final/12_unity_webgl_twin.png"),
    fullPage: false,
  });

  await scene.getByRole("button", {name: "夜间"}).click();
  await expect(ready).toContainText("WEATHER NIGHT");

  await scene.getByRole("button", {name: "全域"}).click();
  await expect(ready).toContainText("CAMERA OVERVIEW");

  expect(pageErrors).toEqual([]);
});

test("renders distinct project-authored vehicle GLBs for visual QA", async ({page}) => {
  await page.goto("/");
  const result = await page.evaluate(async () => {
    const module = await import("/src/3d/vehicles/vehicleAssetQa.ts");
    return module.mountVehicleAssetQa();
  });
  expect(result.models).toBe(3);
  expect(result.triangles).toBeGreaterThan(1_500);
  expect(result.calls).toBeGreaterThanOrEqual(20);
  await expect(page.getByRole("region", {name: "车辆资产视觉验收"})).toBeVisible();
  const chartRuntimeLoaded = await page.evaluate(async () => {
    const host = document.createElement("div");
    Object.assign(host.style, {
      position: "fixed",
      left: "-10000px",
      width: "320px",
      height: "180px",
    });
    document.body.append(host);
    const {initTrendChart} = await import("/src/components/echartsRuntime.ts");
    const chart = initTrendChart(host);
    chart.setOption({
      xAxis: {type: "category", data: ["0", "1"]},
      yAxis: {type: "value"},
      series: [{type: "line", data: [1, 2]}],
    });
    const rendered = host.querySelector("canvas") !== null;
    chart.dispose();
    host.remove();
    return rendered;
  });
  expect(chartRuntimeLoaded).toBe(true);
  await page.screenshot({
    path: path.resolve(process.cwd(), "../../outputs/3d/final/11_vehicle_variants.png"),
  });
});
