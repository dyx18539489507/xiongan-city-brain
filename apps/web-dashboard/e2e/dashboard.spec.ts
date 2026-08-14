import {expect, test} from "@playwright/test";
import path from "node:path";

test("renders the actual twenty-intersection operating surface", async ({page}) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.stack ?? error.message));
  await page.goto("/");
  await page.waitForTimeout(1500);
  expect(pageErrors).toEqual([]);
  await expect(page.getByText("雄安交通协同控制台")).toBeVisible();
  await expect(page.getByText("容东 20 路口协同拓扑")).toBeVisible();
  await expect(page.locator(".intersection-node")).toHaveCount(20);
  await expect(page.getByText("实验与故障控制")).toBeVisible();
  const profile = page.getByLabel("仿真工况");
  await expect(profile.getByRole("option")).toHaveCount(8);
  await profile.selectOption("S04");
  await expect(profile).toHaveValue("S04");
  await expect(
    page.getByRole("option", {name: "主办方20个独立路口复现集（资料复现集）"}),
  ).toHaveAttribute("disabled", "");
});

test("loads the WebGL digital twin and applies real scene controls", async ({page}) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.stack ?? error.message));

  await page.goto("/");
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
