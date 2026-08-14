# Web 3D 实体实时协议

## 真值边界

动态状态来自现有 ExperimentRunner/TraCI：机动车和自行车来自 vehicle domain，行人来自 person domain，20 个 TLS 来自路口聚合快照，事件和 SafetyMonitor 冲突观测来自同一仿真 tick。前端不随机造车、不随机换灯、不预置假冲突、不改变 SUMO 的 1 s 实验步长。

端点：

```text
GET /api/v1/scenes/xiongan_rongdong_20/3d
WS  /ws/v1/digital-twin
```

静态约 11.8 MB scene 通过 URL/hash/bytes/counts 引用，不经 WebSocket 重发。

## init + delta

协议版本 `1.0`、UTF-8 JSON、camelCase。连接/实验切换先发 init：

```json
{
  "type": "init",
  "protocolVersion": "1.0",
  "sequence": 31,
  "status": "running",
  "experimentId": "exp-id",
  "scenarioId": "xiongan_rongdong_20",
  "simulationTimeS": 30.0,
  "tickHz": 1.0,
  "scene": {"url": "/api/v1/scenes/xiongan_rongdong_20/3d", "sha256": "..."},
  "entities": {"vehicles": [], "bicycles": [], "pedestrians": []},
  "trafficLights": [],
  "activeEvents": [],
  "conflicts": [],
  "metrics": {},
  "intersectionMetrics": []
}
```

后续只发变化：

```json
{
  "type": "delta",
  "protocolVersion": "1.0",
  "sequence": 32,
  "experimentId": "exp-id",
  "simulationTimeS": 31.0,
  "spawn": {"vehicles": [], "bicycles": [], "pedestrians": []},
  "update": {"vehicles": [], "bicycles": [], "pedestrians": []},
  "remove": {"vehicles": [], "bicycles": [], "pedestrians": []},
  "trafficLights": [],
  "events": [],
  "conflicts": [],
  "metrics": {},
  "intersectionMetrics": []
}
```

`activeEvents` 解决连接建立前已开始的施工/事故/活动恢复；`conflicts` 是当前 tick 的完整观测集合，下一帧会整体替换而不是永久累积。旧 replay 可缺省这两个字段。sequence 缺口、非法版本或实验 ID 冲突触发 resync/重连，不把新实验 delta 叠到旧状态。

## 实体字段

车辆：`id/type/vehicleClass/x/y/angle/speed/acceleration/laneId/edgeId/routeId/signals/color/brake/status`。行人还含 crossing/waitingArea。TLS 含 phaseIndex、完整 link state、phaseDurationS、remainingS。冲突含稳定观测 ID、参与者 ID、类型、位置、最小距离、相对速度、TTC、PET 与严重度；均来自 SafetyMonitor 当前观测，非前端推断。`cloud_online` 与 `mqtt_online` 来自运行指标；未配置真实 MQTT 时不能解释为物理 V2X 在线。

## 频率与插值

当前真实 tick 通常为 1 Hz，WebSocket 在真值变化时推送；Three.js 以 rAF、目标 30 FPS 做位置插值和 quaternion 姿态插值。原建议约 10 Hz 真值推送尚未实现；没有为改善画面擅改 SUMO 实验步长。

## JSON/二进制决定

MX250 45 组合报告的瓶颈仍主要是渲染/主线程长帧，协议没有显示为首要 CPU 瓶颈；因此保留 JSON，没有为炫技引入 MessagePack。若以后实体量或推送频率明显增加，应先独立 benchmark 编码、网络字节和 parse time 再切换。

## 测试与恢复

Python 测试覆盖 encoder、事件 active init、API/WebSocket 契约；Vitest 覆盖解析、sequence、重连状态和 replay 共用 reducer；Playwright 验证真实页面加载和连接。场景、旧实体 Map、事件池和 WebSocket 在实验切换/卸载时显式清理。
