# 5–8 分钟现场演示脚本

1. 用 `make validate` 展示场景、OpenAPI、MQTT 和 JSON Schema 校验。
2. 打开驾驶舱，说明 K01—K08/B01—B12 是完整容东 OSM 中的控制与观测点，底网没有裁剪，也不是现场标定数字孪生。
3. 展示自行车、电动自行车和行人实际生成、行走/骑行、等待及过街；说明行人信号仅在有横道证据时采用条件并行。
4. 选择 B0 固定配时并启动，展示真实 SUMO 路口状态、机动车/骑行/行人指标和事件时间线。
5. 停止后以同一种子启动 B3 云边协调，指示 K01—K08 核心走廊、动态周期与偏移、上游限流和下游疏散权重。
6. 展示 SUMO → RSU → Edge → Cloud → Edge 的物理 MQTT 链路，再点击路口查看相位、车道聚合、溢出风险和控制模式。
7. 运行 `make fault-demo` 或在驾驶舱注入施工；时间线依次展示真实 TraCI 的封道、活动散场增量发车、应急车辆相位优先。
8. 注入 500 ms 延迟和 10% 丢包，展示通信事件与时延；通道按仿真时间队列推进，不用墙钟 `sleep`。
9. 点击“断开云端”，观察 `HOLD_LAST_VALID → EDGE_AUTONOMOUS`；清除后观察 `RECOVERY_SYNC → CLOUD_COORDINATED`。
10. 展示 TimescaleDB hypertable 中的真实 metrics/events/trajectory batches，以及行人等待、骑行排队和 TTC/PET 代理指标。
11. 运行 `make benchmark-smoke`，说明同种子只改变算法；正式结论需要 5 种子 × 1,800 s，尚未完成就不报告提升率。
12. 导出 JSON、CSV、HTML、SVG 和 manifest，最后说明主办方 20 独立路口仅用于数据复现和单路口验证。
