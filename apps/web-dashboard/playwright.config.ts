import {defineConfig} from "@playwright/test";
import {fileURLToPath} from "node:url";

const workspaceRoot = fileURLToPath(new URL("../..", import.meta.url));
const workspaceSumo = fileURLToPath(new URL("../../.tools/sumo/", import.meta.url));

const workspacePython =
  process.platform === "win32"
    ? fileURLToPath(new URL("../../.venv/Scripts/python.exe", import.meta.url))
    : fileURLToPath(new URL("../../.venv/bin/python", import.meta.url));
const externalBaseUrl = process.env.PLAYWRIGHT_BASE_URL;

export default defineConfig({
  testDir: "./e2e",
  timeout: 240_000,
  use: {
    baseURL: externalBaseUrl ?? "http://127.0.0.1:5183",
    launchOptions: {
      channel: "chrome",
    },
    trace: "retain-on-failure",
  },
  webServer: externalBaseUrl ? undefined : [
    {
      command: `${workspacePython} -m traffic_platform.cli serve --host 127.0.0.1 --port 8003`,
      cwd: workspaceRoot,
      env: {
        SUMO_HOME: process.env.SUMO_HOME ?? workspaceSumo,
      },
      url: "http://127.0.0.1:8003/ready",
      reuseExistingServer: false,
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 5183",
      env: {
        VITE_API_TARGET: "http://127.0.0.1:8003",
      },
      url: "http://127.0.0.1:5183",
      reuseExistingServer: false,
    },
  ],
});
