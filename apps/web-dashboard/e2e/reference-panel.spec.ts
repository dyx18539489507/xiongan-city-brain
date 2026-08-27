import {expect, test} from "@playwright/test";
import path from "node:path";

test.use({viewport: {width: 1366, height: 768}});

test("renders the reference-style 3D operations palette", async ({page}) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.stack ?? error.message));

  await page.goto("/?view=3d");
  const panel = page.locator(".reference-control-panel");
  await expect(panel).toBeVisible();
  await expect(page.getByRole("button", {name: "信号控制", exact: true})).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByLabel("信号控制运行工况")).toBeVisible();
  await expect(page.getByRole("img", {name: "当前路口信号相位图"})).toBeVisible();
  await expect(page.getByRole("img", {name: "进口道排队柱状图"})).toBeVisible();
  await expect(page.getByRole("img", {name: "区域排队与速度趋势图"})).toBeVisible();

  const panelGeometry = await page.evaluate(() => {
    const scroll = document.querySelector<HTMLElement>(".reference-panel-scroll");
    const panelElement = document.querySelector<HTMLElement>(".reference-control-panel");
    const cameras = document.querySelector<HTMLElement>(".unity-camera-rail");
    if (!scroll || !panelElement || !cameras) return null;
    const left = panelElement.getBoundingClientRect();
    const right = cameras.getBoundingClientRect();
    return {
      overflow: scroll.scrollHeight - scroll.clientHeight,
      overlap: left.right > right.left,
      horizontalOverflow: document.documentElement.scrollWidth - innerWidth,
    };
  });
  expect(panelGeometry).toEqual({overflow: 0, overlap: false, horizontalOverflow: 0});

  for (const name of ["仿真场景", "运行态势", "扰动事件", "场景图层", "信号控制"]) {
    await page.getByRole("button", {name, exact: true}).click();
    await expect(page.getByRole("button", {name, exact: true})).toHaveAttribute("aria-pressed", "true");
  }
  for (const name of ["相位状态", "检测数据", "运行控制"]) {
    await page.getByRole("button", {name, exact: true}).click();
    await expect(page.getByRole("button", {name, exact: true})).toHaveAttribute("aria-pressed", "true");
  }
  for (const name of [/路口监控/, /全域鸟瞰/, /主视角/]) {
    const camera = page.getByRole("button", {name});
    await camera.click();
    await expect(camera).toHaveAttribute("aria-pressed", "true");
  }

  await expect(page.locator(".unity-loader")).toHaveCount(0, {timeout: 240_000});
  const canvas = page.frameLocator("iframe[title='雄安交通 Unity 三维场景']").locator("#unity-canvas");
  await expect(canvas).toBeVisible();
  await page.waitForTimeout(2_000);
  await page.screenshot({
    path: path.resolve(process.cwd(), "../../outputs/qa/reference-panel-final/3d-reference-v2-1366x768.png"),
    fullPage: false,
  });
  expect(pageErrors).toEqual([]);
});
