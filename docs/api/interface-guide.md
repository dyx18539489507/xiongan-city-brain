# 接口指南

## REST

正式定义见 `specs/openapi.yaml`。本机直接运行后端时文档位于
`http://127.0.0.1:8000/docs`；Docker Compose 经驾驶舱反向代理后位于
`http://127.0.0.1:5173/docs`。

- 健康与状态：`GET /health`、`/ready`、`/api/v1/system/status`、`/metrics`
- 场景：校验、生成、列表和详情
- 实验：创建、启动、暂停、继续、停止、指标、事件和报告
- 算法：发现、配置校验和激活
- 故障：注入、清除和列表
- 路口：列表、实时状态和历史

错误响应含稳定 `error_code`、`message`、`trace_id` 和 `details`；响应头回传 `x-trace-id`。

## MQTT

规范见 `specs/mqtt_topics.yaml`。状态和策略使用 QoS 1；心跳/高频车辆可按规范使用 QoS 0；策略不 retained，心跳可 retained。主题族：

```text
traffic/{environment}/edge/{edge_id}/...
traffic/{environment}/sumo/{runner_id}/observation
traffic/{environment}/rsu/{rsu_id}/state
traffic/{environment}/cloud/strategy/{target_id}
traffic/{environment}/vehicle/{vehicle_id}/...
traffic/{environment}/experiment/{experiment_id}/...
```

发布者和订阅者只读取公共契约，不导入对方内部实现。`TRAFFIC_MESSAGE_BUS=mqtt` 时实验服务使用真实 `MqttMessageBus`；故障实验显式选择 `EmulatedMessageBus`，以仿真时间实现延迟、抖动、丢包、重复和乱序。生产部署使用 MQTT 8883、密码文件和 TLS；开发 Compose 的匿名 broker 仅绑定 `127.0.0.1`。

物理链路的状态顺序为 SUMO runner 发布原始观测、RSU 校验并重发、Edge 聚合控制状态、Cloud 生成策略。每个角色维护独立且单调的 `sequence_number`；重复、过期和乱序消息在契约边界拒绝。

### 云边通信条件 N0—N8

| 条件 | 云边通道故障模型 |
|---|---|
| N0 | 理想通信：0ms延迟、无抖动、无丢包 |
| N1 | 固定100ms延迟 |
| N2 | 固定300ms延迟 |
| N3 | 固定500ms延迟 |
| N4 | 5%丢包 |
| N5 | 10%丢包 |
| N6 | 云端离线30秒 |
| N7 | 云端离线60秒 |
| N8 | 300ms基础延迟、100ms截断正态抖动、5%丢包，以及各1%的重复、乱序和损坏 |

这些条件由事件驱动优先队列按仿真时间执行，并记录全部通信事件，不使用墙钟 `sleep` 模拟。N2的300ms会实际延后云边状态和策略消息；SUMO-GUI配置中的300ms仅控制画面播放节奏，两者互不替代。

## WebSocket

`/ws/v1/realtime` 推送最近的真实运行快照：实验、场景、算法、仿真时间、路口数组、指标、云状态和降级模式。前端断线后退避重连；未收到数据时显示空态。
