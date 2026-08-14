# 系统总览

## 组件图

```mermaid
flowchart LR
  V["车辆代理\n状态与速度执行"] -->|VehicleState MQTT| E["边缘服务\n自治/安全内核"]
  S["完整 OSM 派生 SUMO / TraCI\n机动车+骑行+行人"] -->|Raw RegionalState| U["独立 RSU Service\n感知校验与路侧汇总"]
  U -->|RSU RegionalState MQTT| E
  E -->|Edge RegionalState MQTT| C["云服务\n风险预测与区域目标"]
  C -->|CloudStrategy MQTT| E
  E -->|ExecutionFeedback MQTT| X["实验服务\n控制与追踪"]
  X --> M["指标引擎"]
  M --> R["报告服务\nJSON/CSV/HTML/SVG"]
  X -->|WebSocket| W["React 驾驶舱"]
  X --> P[("TimescaleDB\nmetrics/events/trajectories")]
  X --> D[("Redis")]
  B["通信模拟器\n延迟/丢包/乱序"] -.包裹消息总线.-> E
  A["算法 SDK\nB0-B3 + 高级模型门禁"] --> E
```

云端只输出区域目标；任何信号动作都必须由边缘端结合本地状态并通过安全内核后执行。

## 数据流

```mermaid
flowchart TD
  A["SUMO 机动车/骑行/行人/车道/信号状态"] --> B["RSU 1 Hz 校验与路侧汇总"]
  B --> C["边缘统一契约 + trace_id"]
  C --> D["仿真时间通信通道"]
  D --> E["云端拥堵传播判断"]
  E --> F["动态周期/相位偏移/绿信比/限流/疏散/速度目标"]
  F --> G["边缘最大压力 + 云目标"]
  G --> H{"安全内核"}
  H -->|accepted/modified| I["TraCI 信号与车速控制"]
  H -->|rejected| J["拒绝原因与安全事件"]
  I --> K["执行反馈与效果观测"]
  J --> K
  K --> L["多主体指标、TTC/PET、Timescale、WebSocket、报告"]
```

## 部署图

```mermaid
flowchart LR
  subgraph Cloud["阿里云 VPC"]
    API["Experiment/API"]
    CS["Cloud Service"]
    DB[("TimescaleDB")]
    RD[("Redis")]
    MQ["Mosquitto TLS"]
    WEB["Web Dashboard"]
    PM["Prometheus"]
  end
  subgraph Edge["本地边缘主机"]
    RSU["RSU Service"]
    ES["Edge Service"]
    VA["Vehicle Agent"]
    SUMO["SUMO / SUMO-GUI"]
  end
  RSU <--> |"MQTT 8883 / TLS"| MQ
  ES <--> |"MQTT 8883 / TLS"| MQ
  VA <--> ES
  ES <--> SUMO
  API --> DB
  API --> RD
  WEB --> API
  PM --> API
  CS <--> MQ
```

## 运行时序

```mermaid
sequenceDiagram
  participant S as SUMO
  participant R as RSU
  participant E as Edge
  participant K as Safety Kernel
  participant C as Cloud
  participant V as Vehicle Agent
  participant X as Experiment/Web
  S->>R: motor/bicycle/pedestrian/lane/TLS state
  R->>E: validated RegionalState
  E->>C: RegionalState
  C-->>E: CloudStrategy (version + TTL)
  E->>E: local algorithm decision
  E->>K: requested action
  K-->>E: accepted / modified / rejected
  E->>S: safe TraCI command
  E->>V: speed guidance
  V->>S: bounded target speed
  E->>X: ExecutionFeedback + metrics
  X-->>X: JSON/CSV/HTML/SVG + WebSocket
```

## 场景边界

K01—K08 与 B01—B12 是完整容东 OSM 网络中的稳定控制/观测标识，不是物理裁剪边界。车辆可使用全网边和区域 OD；仅一部分测试路线被配置为连续穿越核心走廊。多主体网络是从完整 OSM 派生的可重建文件，冻结的机动车底网保持不变。

行人信号使用“条件并行”：只有在路网确有横道且受控连接冲突可验证时，行人与兼容机动车流并行放行；否则保持既有安全相位或使用安全清空相位，不为凑数量虚构横道。

## 故障降级状态机

```mermaid
stateDiagram-v2
  [*] --> RECOVERY_SYNC
  RECOVERY_SYNC --> CLOUD_COORDINATED: 版本同步且稳定窗口完成
  CLOUD_COORDINATED --> HOLD_LAST_VALID: 云消息短时超时
  HOLD_LAST_VALID --> EDGE_AUTONOMOUS: 超过自治阈值或策略过期
  EDGE_AUTONOMOUS --> RECOVERY_SYNC: 云恢复
  CLOUD_COORDINATED --> FIXED_TIME_SAFE: 本地算法/数据/安全内核异常
  HOLD_LAST_VALID --> FIXED_TIME_SAFE: 本地异常
  EDGE_AUTONOMOUS --> FIXED_TIME_SAFE: 本地异常
  FIXED_TIME_SAFE --> EDGE_AUTONOMOUS: 本地恢复但云仍离线
  FIXED_TIME_SAFE --> RECOVERY_SYNC: 本地与云均恢复
```
