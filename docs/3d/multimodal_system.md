# 非机动车与行人系统（Phase 7）

## 数据链路

`BicycleManager` 和 `PedestrianManager` 只消费数字孪生 WebSocket 中的真实实体 Map。它们不随机生成参与者：

- 自行车/电动车使用 `digitalTwin.state.bicycles`；
- 行人使用 `digitalTwin.state.pedestrians`；
- 坐标、方向、速度、车道、道路和等待状态均来自 SUMO；
- 新实体从对象池取得显示对象，离开时隐藏并回池；
- 当前通常 1 Hz 的逻辑状态通过 `VehicleInterpolator` 在目标 30 FPS 渲染中平滑插值，不为画面修改 SUMO 步长。

完成态验收快照共有 11 个非机动车实体和 5 个行人实体，其中当前 3D 裁剪边界内分别为 3 和 4。边界外实体保留在实时状态中，不伪造到场景内部。

## 视觉行为

非机动车：

- 双轮滚动；
- 骑行者腿部随轮相位运动；
- 转弯时低成本车身倾斜；
- 近景完整程序模型、远景单网格 LOD；
- 自行车继续位于 SUMO 对应非机动车道，不按小汽车路径重算。

行人：

- 25 m 内使用共享蒙皮几何和每肢两骨骼 `SkinnedMesh`，SUMO 速度驱动摆臂、屈肘、摆腿和屈膝；
- 等待状态停止摆动；
- 多种共享衣着材质；
- 25–65 m 使用低面胶囊，65 m 外进入单个动态 `InstancedMesh` 批次；
- 人行道/过街路径和等待区域仍由 SUMO 决定。

代码与测试：

- `apps/web-dashboard/src/3d/bicycles/BicycleManager.ts`
- `apps/web-dashboard/src/3d/pedestrians/PedestrianManager.ts`
- `apps/web-dashboard/src/3d/bicycles/MultimodalManagers.test.ts`
- `apps/web-dashboard/src/3d/pedestrians/PedestrianManager.test.ts`

固定画面：

- `outputs/3d/phase7/11_bicycle_live_closeup.png`
- `outputs/3d/phase7/12_pedestrian_live_closeup.png`

## 当前限制

当前人物与自行车是项目内原创低面程序资产；近景行人已经是低骨骼蒙皮动画，但不是扫描人物或高精 Blender 人物 GLB，也没有完整动画混合和年龄/服装资产库。远景采用 InstancedMesh 而非 Billboard。点击检查器和真实同步已接入；美术覆盖仍可继续提升，但不再把“无骨骼人物”列为未实现。
