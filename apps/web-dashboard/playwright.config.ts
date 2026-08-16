import {defineConfig} from "@playwright/test";

const workspacePython =
  process.platform === "win32" ? ".\\.venv\\Scripts\\python.exe" : "./.venv/bin/python";
const externalBaseUrl = process.env.PLAYWRIGHT_BASE_URL;

export default defineConfig({
  testDir: "./e2e",
  timeout: 240_000,
  use: {
    baseURL: externalBaseUrl ?? "http://127.0.0.1:5183",
    trace: "retain-on-failure",
  },
  webServer: externalBaseUrl ? undefined : [
    {
      command: `${workspacePython} -m traffic_platform.cli serve --host 127.0.0.1 --port 8003`,
      cwd: "../..",
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
