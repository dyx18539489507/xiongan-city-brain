# 轻量天气与昼夜系统

## 实现

Phase 9 新增：

- `apps/web-dashboard/src/3d/environment/LightingManager.ts`
- `apps/web-dashboard/src/3d/environment/WeatherManager.ts`
- `apps/web-dashboard/src/3d/environment/WeatherManager.test.ts`

正式渲染仍使用 WebGLRenderer，不依赖 HDRP、实时全局光照或光线追踪。界面提供晴、阴、黄昏、夜、雨、雾六种环境配置。

每种配置同步控制：

- 低分辨率程序化天空渐变；
- HemisphereLight 与唯一 DirectionalLight；
- ACES tone mapping exposure；
- Fog 的颜色与可见距离；
- 道路、路口、横道底层和地面的颜色；
- 雨天道路 roughness / metalness；
- 夜间建筑窗户 emissive；
- 夜间、雨天和雾天路灯灯头 emissive。

雨场使用固定 560 条相机局部 LineSegments，只更新已分配的 position buffer；不会为每滴雨创建 Mesh，也不会覆盖整个两公里场景。雨天不是单纯屏幕雨线：道路粗糙度由日间基线约 0.84 降至 0.36，并适度压暗路面。

## 视觉证据

- `outputs/3d/phase9/14_night.png`
- `outputs/3d/phase9/15_rain.png`
- `outputs/3d/phase9/16_fog.png`

夜景采用“比赛投影可读的月光夜景”，不是物理上全黑的夜间曝光。没有为 269 盏路灯或每辆车创建 PointLight / SpotLight，避免 MX250 的实时光源压力。

## 性能边界

阶段性雨天车辆近景窗口曾记录 28.3 FPS、43 draw calls、185,403 triangles；P1 12 FPS 混入内置浏览器截图调度暂停，不能解释为纯 GPU P1。当前已在目标 MX250 前台 Chromium 完成 S01–S05×晴/夜/雨×全域/走廊/路口 45 组合矩阵，正式数字统一见 `performance_report.md`，不再用阶段截图等待期间的 FPS 代替。

## 已知限制

- 当前没有 HDRI 资产，湿路面的低 roughness 能产生方向光高光，但不等于屏幕空间反射。
- 建筑覆盖来自现有 OSM 轮廓，窗灯仅存在于已生成窗面处；外围空白不能用虚构建筑填充后宣称真实雄安。
- 当前天气是可视化环境配置，尚未改变 SUMO 车辆跟驰参数；因此不能声称雨雾已经影响交通行为。
