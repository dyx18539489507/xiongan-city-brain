# Web 2D 仿真指挥中心

## 入口

- 默认二维态势：`http://127.0.0.1:5173/?view=2d`
- 现有 Unity 三维孪生：`http://127.0.0.1:5173/?view=3d`
- 页面顶部的 `2D / 3D` 开关只切换表现层；两种视图消费同一个数字孪生状态，不会启动第二套仿真。

## 数据链路

二维页面不生成交通需求、主体位置或信号状态：

1. `ExperimentRunner` 通过 TraCI 驱动 SUMO，并采集机动车、非机动车、行人、TLS、冲突、事件与指标。
2. `/ws/v1/digital-twin` 发送 `init + delta` 实体状态；`/ws/v1/realtime` 发送路口、车道和全局指标。
3. `/api/v1/scenes/{scenario_id}/3d` 提供由 `net.xml` 生成的静态道路、车道、路口、横道、建筑和核心走廊几何。该端点名称为兼容既有 3D 契约保留，2D 与 3D 共用同一场景文档。
4. `TrafficCanvasRenderer` 将仿真 tick 与浏览器帧解耦，并在两个真实 SUMO tick 之间做视觉插值；插值只平滑位置和角度，不改变仿真真值。

## 前端分层

- `src/2d/world/TrafficWorldState.ts`：把静态场景、数字孪生增量和实时指标适配为统一 `WorldState`，Renderer 不接触 WebSocket。
- `src/2d/camera/MapCamera.ts`：缩放、平移、视口裁剪、全域/走廊/路口镜头过渡。
- `src/2d/motion/EntityInterpolator.ts`：在相邻 SUMO 帧之间插值位置和朝向，保留真实轨迹点。
- `src/2d/layers/*`：城市空间、道路/标线、交通状态、排队、主体、信号、算法、事件、RSU、标签和交互选中层。
- `src/2d/TrafficCanvasRenderer.ts`：离屏静态缓存、图层编排、动态批绘、LOD、拾取和视口裁剪。
- `src/2d/useStaticScene.ts`：大场景流式下载、进度和错误状态。
- `src/components/Traffic2DScene.tsx`：`requestAnimationFrame`、ResizeObserver、平移缩放和地图工具。
- `src/components/SimulationCommandCenter.tsx`：2D/3D 表现层切换与 Map-First 驾驶舱编排。
- `src/components/twin/*`：场景/算法/事件/图层控制、运行态势、对象详情、趋势和事件确认抽屉。
- `src/components/TrendChart.tsx`：展开分析中的真实采样趋势；算法对比只读取 `actual_run=true` 的结果文件。

静态路网、建筑和背景网格缓存到离屏 Canvas；每帧只重绘车道运行状态、主体、信号灯、事件及选中态。实体以 Map 维护，WebSocket 增量不会触发全量场景解析。

## 运行

设置 `SUMO_HOME`，在仓库根目录执行：

```powershell
.\.venv\Scripts\traffic-platform.exe serve --host 127.0.0.1 --port 8000
```

另开终端：

```powershell
cd apps\web-dashboard
$env:VITE_API_TARGET='http://127.0.0.1:8000'
npm run dev -- --host 127.0.0.1 --port 5173
```

也可使用现有一键脚本。脚本名为历史兼容名称，但同一页面默认进入 2D：

```powershell
.\scripts\start_3d_demo.ps1 -BackendPort 8013 -FrontendPort 5177 -NoBrowser
```

打开 `http://127.0.0.1:5177/?view=2d`。如只启动服务而不创建新实验，加 `-SkipExperiment`；页面仍可载入已有真实 SUMO 回放。停止服务使用：

```powershell
.\scripts\stop_3d_demo.ps1
```

## 控制语义

- `运行 / 暂停 / 继续 / 停止 / 重置` 调用现有实验生命周期 API。
- 运行倍速调用 `/api/v1/experiments/{id}/rate`。`MAX` 保持历史最大吞吐行为；`0.5x–8x` 只按墙钟节流 SUMO，不改变仿真步长或状态。
- 回放倍速由回放管理器控制真实 NDJSON 帧播放，不修改已记录结果。
- 事件按钮调用既有故障注入 API；画面只有在后端事件流给出可定位 lane/vehicle 时才显示标记，不生成前端假事件。

## 3D 扩展

`SimulationCommandCenter` 已把表现层隔离为 `Traffic2DScene` 与 `UnityScene`。后续升级 3D 只需保持静态场景和 `DigitalTwinStream` 契约，不需要修改 SUMO、TraCI、实验调度或二维渲染器。

## 视觉验收图

最终 1920×1080 截图位于 `outputs/2d/map-first-acceptance/`：区域总览、核心走廊、K08 路口近景与真实事故回放各一张。
