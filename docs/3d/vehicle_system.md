# Web 3D 车辆系统

## 当前状态

Phase 4—14 已完成机动车主链路：真实 SUMO 车辆实体经过统一坐标服务进入 Three.js，采用分车型对象池、相邻 tick 插值、三级距离 LOD，并将远景车辆合批为 InstancedMesh。轿车使用仓库 Blender 源资产；公交、卡车和配送车使用可导入 Blender 的原创轻量 PBR/Draco GLB。典型镜头、三套新增资产、高峰矩阵和 30 分钟长稳均已验收；独立 SUV/应急车等资产覆盖仍可继续提升。

## 数据链

```text
TraCI VehicleSnapshot
  -> DigitalTwinDelta spawn/update/remove
  -> DigitalTwinStore current vehicle Map
  -> VehicleManager.applySnapshot()
  -> VehicleInterpolator
  -> VehiclePool shared GLB instances
  -> Three.js scene
```

`VehicleManager` 只消费协议车辆 Map，不创建随机车辆。车辆离开 SUMO 或离开当前正式渲染范围后会隐藏并回收到池中；重新出现时复用对象。池超过软上限才释放实例独享材质，基础几何和静态材质继续共享。

## 坐标和姿态

- `x/y` 统一通过 `CoordinateService.sumoToWorld()`；
- SUMO 航向通过 `sumoAngleToThree()`；
- Blender 车辆车头沿本地 `+X`，配置中的 `baseYawRad = π/2` 把 0° 对齐 SUMO 北向；
- 相邻姿态使用 quaternion slerp，测试覆盖 359°→1° 最短旋转；
- 只保留当前和目标变换，不累计无限轨迹；
- 车辆高度使用模型配置 `groundOffsetM`，没有模块私有坐标魔法数。

## 视觉行为

当前已实现：

- 真实 SUMO 颜色映射到车身 PBR 材质；
- 速度驱动车轮角速度；
- 相邻航向变化推导有限前轮转角；
- 减速度驱动刹车灯；
- SUMO signals bit 0/1 驱动右/左转向灯；
- signals 前灯位驱动车头自发光；
- emergency vClass 或应急信号位驱动红蓝交替灯；
- 原 GLB 合并轮胎被隐藏，运行时补充低成本独立轮组，以支持旋转和前轮转向。
- LOD0 使用完整 GLB 与动态部件，LOD1 为双网格车身，LOD2 为单网格轮廓；默认 90 m/260 m 阈值来自映射配置而非代码散落常量。

这里的车轮和灯光只改变网格/自发光材质，没有为每辆车创建 `PointLight` 或 `SpotLight`。

## 资产与车型映射

配置文件：`apps/web-dashboard/public/assets/3d/vehicle_model_mapping.json`。

加载器支持一个映射表中存在多个模型和多个独立对象池。当前映射包含 `urban-car`、`delivery-van`、`urban-bus` 和 `urban-truck`；模型配置分别保存真实工程尺寸、轮轴位置和轮径，LOD1/LOD2 也按车型尺寸构造，不再把大型车简单拉伸成轿车。passenger、connected、taxi、ride-hailing 和 emergency 仍共享基础轿车车身并保留 SUMO 颜色；应急警灯网格只在真实 emergency 状态下显示。

后续加入 SUV 和独立应急车 GLB 时，只需增加 `models` 并修改 `typeMappings`，无需改 SUMO 或车辆管理器。

## 加载失败降级

如果车型映射或 GLB 加载失败，系统记录 warning 并使用显式低模占位车辆，保持真实 SUMO ID、位置、姿态和生命周期。降级模型不会被表述成高质量资产；场景和 WebSocket 不会因单个 GLB 损坏而整体崩溃。

## 当前验证

- 前端完整 Vitest：22 个文件、35 项通过；
- TypeScript + Vite 生产构建：通过；
- 项目资产单测直接解析 5 个 GLB 的 header、mesh/accessor 和 manifest；公交 660 triangles，卡车/配送车各 720 triangles；
- 插值单测：位置中点和 359°→1° quaternion 最短路通过；
- Playwright 3 项通过，其中资产项实际加载三套新增 GLB 并输出 `outputs/3d/final/11_vehicle_variants.png`；
- S02、seed 52、60 s 真实实验 `exp-9b4aec752c6c` 完成，61 个真实回放帧中观察到 `bus`、`truck` 和 `delivery_vehicle`，结果与回放分别位于 `results/exp-9b4aec752c6c/result.json` 和 `digital_twin.replay.ndjson`；
- 最终冻结代码 MX250 45 组合矩阵平均 15.27 FPS，最高 23.4、最低 8.1；详见 `performance_report.md`，不能表述为稳定 25–30 FPS。

## 未完成项

- 独立 SUV、应急车和更多轿车外观；现有新增车型是轻量工程资产，不是电影级模型；
- 更精细的屏幕尺寸遮挡近似；当前统一 LODManager 以距离/视锥/核心优先级为主；
- 浏览器无可靠显存 API，显存只能按纹理/geometry 估算；
- 长稳仍有实体增长背景下的正 Heap 斜率，30 分钟内无崩溃不等于已证明零泄漏。
