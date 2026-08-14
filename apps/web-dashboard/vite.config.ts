import {defineConfig} from "vite";
import react from "@vitejs/plugin-react";

const apiTarget = process.env.VITE_API_TARGET ?? "http://localhost:8000";
const websocketTarget = apiTarget.replace(/^http/, "ws");

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": apiTarget,
      "/health": apiTarget,
      "/ready": apiTarget,
      "/ws": {
        target: websocketTarget,
        ws: true,
      },
    },
  },
  build: {
    sourcemap: true,
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            {name: "charts", test: /node_modules[\\/]echarts|node_modules[\\/]zrender/},
            {name: "react", test: /node_modules[\\/]react|node_modules[\\/]scheduler/},
            {name: "three", test: /node_modules[\\/]three/},
          ],
        },
      },
    },
  },
});
