import {defineConfig} from "vite";
import react from "@vitejs/plugin-react";
import type {Connect} from "vite";

const apiTarget = process.env.VITE_API_TARGET ?? "http://localhost:8000";
const websocketTarget = apiTarget.replace(/^http/, "ws");

function unityCompressionHeaders(): Connect.NextHandleFunction {
  return (request, response, next) => {
    const pathname = request.url?.split("?", 1)[0] ?? "";
    if (pathname.endsWith(".br")) {
      response.setHeader("Content-Encoding", "br");
      response.setHeader("Cache-Control", "public, max-age=86400");
      response.setHeader("Content-Type", pathname.endsWith(".wasm.br")
        ? "application/wasm"
        : pathname.endsWith(".js.br") ? "text/javascript" : "application/octet-stream");
    }
    next();
  };
}

const unityWebGlPlugin = {
  name: "unity-webgl-compression",
  configureServer(server: {middlewares: {use: (handler: Connect.NextHandleFunction) => void}}) {
    server.middlewares.use(unityCompressionHeaders());
  },
  configurePreviewServer(server: {middlewares: {use: (handler: Connect.NextHandleFunction) => void}}) {
    server.middlewares.use(unityCompressionHeaders());
  },
};

export default defineConfig({
  plugins: [react(), unityWebGlPlugin],
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
    emptyOutDir: true,
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
