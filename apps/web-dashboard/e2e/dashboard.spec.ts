import {expect, test} from "@playwright/test";
import path from "node:path";

test("renders the map-first SUMO 2D cockpit and switches views", async ({page}) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.stack ?? error.message));
  await page.goto("/?view=2d");
  const baselineMap = page.getByRole("region", {name: "基准算法实时地图"});
  const candidateMap = page.getByRole("region", {name: "候选算法实时地图与改善差值"});
  await expect(baselineMap).toBeVisible({timeout: 180_000});
  await expect(candidateMap).toBeVisible({timeout: 180_000});
  await expect(page.locator(".scene-loading")).toHaveCount(0, {timeout: 180_000});
  expect(pageErrors).toEqual([]);
  await expect(page.getByRole("heading", {name: "雄安城市交通数字孪生"})).toBeVisible();
  await expect(page.getByLabel("当前仿真运行身份")).toContainText("双 SUMO / TraCI");
  await expect(page.getByLabel("当前仿真运行身份")).toContainText("待启动");
  await expect(page.getByLabel("SUMO 实时二维交通数字孪生地图")).toHaveCount(2);
  await expect(baselineMap).toContainText("固定配时控制");
  await expect(candidateMap).toContainText("候选");
  await expect(page.getByText("同条件实时对照")).toHaveCount(0);
  await expect(page.getByText("正在为双算法加载同一份 SUMO 路网")).toHaveCount(0);
  await expect(page.getByText(/仅表示本次同条件运行的实时趋势/)).toHaveCount(0);
  await expect(page.getByLabel("改善差值图例")).toContainText("右图进口道与路口相对左图");
  await expect(page.locator(".source-switcher")).toHaveCount(0);
  await expect(page.getByRole("button", {name: /2D/})).toHaveClass(/active/);
  const profile = page.getByLabel("仿真工况");
  await expect(profile.first().getByRole("option")).toHaveCount(8);
  await profile.first().selectOption("S04");
  await expect(profile.first()).toHaveValue("S04");
  await expect(
    page.getByRole("option", {name: "主办方20个独立路口复现集"}),
  ).toHaveCount(0);
  await page.getByRole("button", {name: /3D/}).click();
  await expect(page.locator(".twin-cockpit.view-3d")).toBeVisible();
  await page.getByRole("button", {name: /2D/}).click();
  await expect(baselineMap).toBeVisible();
  await expect(candidateMap).toBeVisible();
});

test("loads the WebGL digital twin and applies real scene controls", async ({page}) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.stack ?? error.message));

  await page.goto("/?view=3d&perf=1");
  const scene = page.getByRole("region", {
    name: "雄安交通 Unity 三维数字孪生",
  });
  const ready = scene.getByRole("status").filter({hasText: "SUMO STATIC READY"});
  await expect(ready).toContainText(
    "SUMO STATIC READY",
    {timeout: 180_000},
  );
  await expect(scene.getByText("20 / 20", {exact: true})).toBeVisible();
  await expect(ready).toContainText("CAMERA TRAFFIC", {timeout: 30_000});
  await expect(scene.getByRole("button", {name: "夜间"})).toHaveCount(0);
  const unityCanvas = page.frameLocator("iframe[title='雄安交通 Unity 三维场景']").locator("#unity-canvas");
  await expect(unityCanvas).toBeVisible();
  const canvasSize = await unityCanvas.evaluate((canvas: HTMLCanvasElement) => ({
    width: canvas.width,
    height: canvas.height,
  }));
  expect(canvasSize.width).toBeGreaterThan(100);
  expect(canvasSize.height).toBeGreaterThan(100);
  await page.waitForTimeout(1200);

  await page.screenshot({
    path: path.resolve(process.cwd(), "../../outputs/3d/final/12_unity_webgl_twin.png"),
    fullPage: false,
  });

  await scene.getByRole("button", {name: "全域"}).click();
  await expect(ready).toContainText("CAMERA OVERVIEW");

  expect(pageErrors).toEqual([]);
});

test("renders direct Unity performance diagnostics", async ({page}) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.stack ?? error.message));
  await page.goto("/unity/index.html?perf=1");
  await expect(page.locator("#loading")).toHaveAttribute("data-hidden", "true", {
    timeout: 180_000,
  });
  await page.waitForTimeout(15_000);
  const canvas = page.locator("#unity-canvas");
  await expect(canvas).toBeVisible();
  const size = await canvas.evaluate((element: HTMLCanvasElement) => ({
    width: element.width,
    height: element.height,
  }));
  expect(size.width).toBeGreaterThan(100);
  expect(size.height).toBeGreaterThan(100);
  await page.screenshot({
    path: path.resolve(process.cwd(), "../../outputs/3d/final/13_unity_performance.png"),
  });
  expect(pageErrors).toEqual([]);
});

test("streams live SUMO truth into the Unity canvas", async ({page}) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.stack ?? error.message));
  await page.goto("/?view=3d&perf=1");
  const scene = page.getByRole("region", {name: "雄安交通 Unity 三维数字孪生"});
  const ready = scene.getByRole("status").filter({hasText: "SUMO STATIC READY"});
  await expect(ready).toContainText("SUMO STATIC READY", {timeout: 180_000});
  await page.getByRole("button", {name: "启动仿真"}).click();
  await expect(scene.locator(".unity-readout")).toContainText(/[1-9]\d* 车辆/, {
    timeout: 120_000,
  });
  await expect(page.locator(".header-clock strong")).not.toHaveText("00:00:00", {
    timeout: 60_000,
  });
  await page.waitForTimeout(15_000);
  const unityCanvas = page.frameLocator("iframe[title='雄安交通 Unity 三维场景']").locator("#unity-canvas");
  const renderer = await unityCanvas.evaluate((canvas: HTMLCanvasElement) => {
    const gl = canvas.getContext("webgl2") ?? canvas.getContext("webgl");
    const debug = gl?.getExtension("WEBGL_debug_renderer_info");
    return debug && gl ? gl.getParameter(debug.UNMASKED_RENDERER_WEBGL) : "unavailable";
  });
  console.log(`Unity WebGL renderer: ${renderer}`);
  await unityCanvas.screenshot({
    path: path.resolve(process.cwd(), "../../outputs/3d/final/14_unity_sumo_live.png"),
  });
  await page.getByRole("button", {name: "停止仿真"}).click();
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
