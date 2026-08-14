# 扰动事件三维映射

## 真实事件链

`EventVisualizationManager` 只消费后端事件，不在前端随机制造交通：

- `ROADWORK_LANE_CLOSED/REOPENED`：按真实 SUMO lane ID 生成/回收锥桶与障碍；
- `INCIDENT_STOP_SCHEDULED`：只记录 SUMO 已接受下游停车计划，不显示“已停车”标记；
- `INCIDENT_VEHICLE_STOPPED`：只有 `vehicle.isStopped()` 为真后才显示事故标记；
- `INCIDENT_CLEARED`：实际停下后解除；`INCIDENT_STOP_CANCELLED`：计划到期但尚未停车；`ALREADY_RELEASED`：实体已离开；三者均清理状态；
- `EVENT_DISPERSAL_STARTED/ENDED`：只对 activity 语义目标显示低遮挡 zone 边界；普通 flow surge 不冒充活动区；
- `EVENT_DISPERSAL_VEHICLE_INJECTED`：车辆仍通过 SUMO route/type 注入，前端只显示随后的真实实体帧。

实现：

- `src/traffic_platform/experiment_service/disturbances.py`
- `src/traffic_platform/sumo_adapter/adapter.py`
- `apps/web-dashboard/src/3d/events/EventVisualizationManager.ts`
- `apps/web-dashboard/src/components/IntersectionScene.tsx`

## 事故候选约束

SUMO 把 bicycle 也放在 vehicle domain，因此事故候选必须同时满足：

1. 当前 vClass 不是 bicycle/moped/pedestrian；
2. 当前 `roadID` 本身属于 `preferred_route_edges`，不能仅因下一 route edge 在核心区就选中内部连接道；
3. SUMO 接受安全下游 `setStop`；
4. 实际停止后才发布 STOPPED。

真实验收 `exp-d39eab8f13b5`：

- scheduled：T+34 s；stopped：T+45 s；
- 车辆：`od00_00004`，vClass=`delivery`；
- stopped 帧速度：0.007 m/s，status=`waiting`；
- 坐标 `(3077.487, 7261.167)` 在 scene bounds 内；
- lane `916884512#1_1` 在 scene.json 中存在；
- `INCIDENT_CLEARED` 1 次；
- 固定镜头：`outputs/3d/final/09_event.png`。

本轮保留了两类失败证据：第一次事故选到自行车，第二次选到核心 route 上游的内部连接道并被 TraCI 拒绝。两者促成上述约束，未删除或降级测试。

## 大型活动

真实实验 `exp-cb2caa1204ad` 的 `north_activity`：活动开始 1 次、注入 90 辆、结束 1 次。活动边界为 scene zone 的工程映射，采用薄 Torus/实例池，避免用大面积透明圆盘遮挡交通；不声称活动场地是现场精确边界。

## 池与恢复

锥桶 320、障碍 32、事故标记 32、活动 zone 8 的固定容量实例池；已处理事件 ID 只保留 256 条。初始化快照带 `activeEvents`，重连和回放 seek 后可恢复正在进行的事件。实验 ID 改变时完整 reset。
