# 正式实验就绪性审计

文档状态：正式实验前置审计  
审计日期：2026-08-20；算法补充审计：2026-08-23  
审计提交：`5e6e30750b499fb33837bff9f4cb18fa6e8a5e0d`（`main`，工作树存在既有未提交资源改动）  
审计对象：`D:\程序项目\面向雄安新区的城市大脑`  
证据原则：代码、配置、可执行结果和运行日志共同判定；README 和历史说明只作线索，不单独作为完成证据。

## 1. 审计结论

当前工程已具备开展正式 SUMO 仿真实验的核心条件，但历史结果尚不足以支持算法性能排名。

可以立即进入正式实验的能力包括：

- 连通的 `xiongan_rongdong_20` 容东 OSM 派生工程场景；
- 20 个受控/观测路口和 K01--K08 八路口核心走廊；
- B0 固定配时、B1 感应控制、B2 最大压力、B3 预测增强云边协调最大压力；
- SUMO--RSU/聚合--消息总线--Cloud--Edge--Safety Kernel--TraCI 闭环；
- 施工占道、事故、活动散场、应急车辆等物理扰动执行器；
- 固定延迟、抖动、丢包、重复、乱序、损坏、端点/中间件离线等软件通信模拟能力；
- `tripinfo.xml`、`summary.xml`、`statistics.xml`、逐秒聚合样本、事件和通信记录输出；
- FastAPI、WebSocket、3D 实时/回放消费链和可选持久化接口。

尚不能作为已完成能力写入正式性能排名的部分包括：

- B3 v2 已完成同种子 120 s 真实闭环验收，但尚未完成多负荷、多种子长时正式矩阵；
- `official_20_independent` 是 20 个独立官方数据路口，不是物理连通区域路网；
- 通信实验是软件模拟，不是真实 5G、C-V2X 或现场网络测试；
- RSU、车端和云端角色是软件服务，不是真实路侧设备或实车；
- `xiongan_rongdong_20` 未做现场交通流、高精地图或信号配时标定；
- Docker Engine 当前未运行，数据库、Redis 和真实 MQTT 不是本轮本机基准的默认依赖；
- 历史多算法结果主要是单种子、20 秒冒烟，不能推出改善率或显著性。

## 2. 审计范围和验证动作

本轮递归检查了仓库中的 Python、TypeScript/React、Three.js、Unity、SUMO XML/YAML、测试、结果、报告、Docker/Compose、数据库迁移和脚本。重点阅读的实现包括：

- `src/traffic_platform/experiment_service/engine.py`
- `src/traffic_platform/sumo_adapter/adapter.py`
- `src/traffic_platform/edge_service/aggregation.py`
- `src/traffic_platform/edge_service/controller.py`
- `src/traffic_platform/cloud_service/coordinator.py`
- `src/traffic_platform/safety_kernel/kernel.py`
- `src/traffic_platform/communication_emulator/channel.py`
- `src/traffic_platform/experiment_service/disturbances.py`
- `src/traffic_platform/metrics_engine/calculator.py`
- `src/traffic_platform/api/app.py`
- `src/traffic_platform/storage/database.py`
- `src/traffic_platform/storage/buffer.py`
- `src/traffic_platform/report_service/generator.py`
- `src/traffic_platform/service_workers.py`
- `apps/web-dashboard/src/` 和 `apps/unity-digital-twin/Assets/Xiongan/`

本轮重新执行的验证：

| 验证 | 结果 | 证据边界 |
|---|---:|---|
| Python unit + contract | 103/103 通过 | 模块和 API/契约正确性，不代表算法性能 |
| Web Vitest | 27 个文件、56/56 通过 | 前端逻辑正确性，不代表浏览器 FPS |
| SUMO 20 路口 performance smoke | B1、B3 各 5 秒通过 | 真实 SUMO/TraCI 闭环，仅功能冒烟 |
| SUMO | 1.27.1 | 可移植运行时二进制实测 |
| Python TraCI/sumolib | 1.27.1 | 已在项目 `.venv` 安装并通过 smoke |

## 3. 场景真实性边界

### 3.1 `official_20_independent`

该目录保留和验证 20 个官方数据派生的独立路口模型。它适合做官方参数保真、单路口结构检查和需求守恒验证，但路口之间没有物理道路连接。

正式报告必须使用以下表述：

> `official_20_independent` 用于保留和验证官方路口数据，不将其包装成连通区域交通网络。

本轮不使用该场景进行区域协同算法性能排名。

### 3.2 `xiongan_rongdong_20`

代码和生成资产共同证明该场景具备：

- 容东片区 OSM 派生的完整连通底网；
- 20 个稳定受控/观测路口；
- K01--K08 八路口连续核心走廊；
- 20 条受控点直接邻接关系；
- 机动车、公交、货车、配送车、出租/网约车、应急车和网联/非网联车；
- 自行车、电动自行车和行人；
- 信号灯、车道、OD、分时交通需求、路线替代和事件注入；
- 核心走廊路线至少连续经过 5 个受控路口。

真实性边界：14 个 OSM 路口与 6 个主办方位置锚点共同形成工程场景；交通需求、信号与部分道路参数为建模或迁移值，并非现场标定值。它应称为“OSM 派生、参数迁移的工程仿真场景”，不能称为运营级或毫米级数字孪生。

### 3.3 已生成需求档位

| 档位 | Profile | 需求倍率 | 静态机动车数 | 物理扰动 |
|---|---|---:|---:|---|
| Low | S01 | 0.75x | 737 | 无 |
| Medium | BASE 路由 | 1.00x | 983 | BASE YAML 含多个定时扰动，基准实验需显式禁用 |
| High | S04/S05 路由 | 1.20x | 1,180 | profile 自带施工或事故，不直接用于无扰动基准 |
| Oversaturated | S02 | 1.60x | 1,573 | 无 |

所有 profile 路由当前由 seed 42 生成，因此不同 SUMO seed 共享同一组 OD 和发车表。SUMO seed 仍影响车辆行为随机性。正式报告不得把这组实验描述成“每个 seed 重新抽样 OD”；公平性表述应为“同一确定性 OD/发车表下改变 SUMO 运行 seed”。

## 4. 控制算法完成度

| 编号 | 代码名 | 状态 | 真实输入与动作 | 正式排名 |
|---|---|---|---|---|
| B0 | `fixed-time` | 已实现 | 保持 SUMO 固定信号程序 | 是 |
| B1 | `actuated-control` | 已实现 | 使用本地车道队列/需求决定保持或请求下一相位 | 是 |
| B2 | `max-pressure` | 已实现 | 使用上下游队列压力并抑制下游溢出 | 是 |
| B3 | `coordinated-max-pressure` 2.0 | 已实现 | 融合本地压力、30/60/120 s 在线图时序预测、置信度门控、下游容量、限流、周期、offset 与车速引导 | 是 |

正式报告必须明确：

> 当前控制算法严格为 B0-B3 四个。预测能力并入 B3；未就绪时在 B3 内回退到当前状态协调。2026-08-20 快速矩阵早于 B3 v2，不能作为新版预测贡献的性能证明。

## 5. 云--边--端闭环审计

已验证的真实软件链路为：

```text
SUMO / Vehicle / Person
  -> TraciSumoAdapter
  -> RSU/EdgeStateAggregator
  -> MessageBus（MQTT 或确定性模拟总线）
  -> RegionalCoordinator / CloudStrategy
  -> EdgeController
  -> SafetyKernel
  -> TraCI 信号与速度动作
  -> SUMO
  -> Metrics / Events / WebSocket / Report
```

消息契约包含 `timestamp_utc`、`simulation_time`、`sequence_number`、`message_id`、`trace_id`、`vehicle_id`、`intersection_id`、相位、速度建议、策略、动作和反馈。幂等、过期与顺序检查存在于公共消息守卫和服务工作器。

降级状态机包含：

- `CLOUD_COORDINATED`
- `HOLD_LAST_VALID`
- `EDGE_AUTONOMOUS`
- `FIXED_TIME_SAFE`
- `RECOVERY_SYNC`

边缘安全内核真实返回 `ACCEPTED`、`MODIFIED`、`REJECTED`，检查最小/最大绿、合法相位、行人清空、下游溢出、应急优先、速度上限和舒适减速度。

限制：正式基准默认使用 `EmulatedMessageBus` 以保证可重复。它不是物理 MQTT 网络；真实 MQTT、TimescaleDB 和 Redis 需要 Docker/外部服务，本机 Docker Engine 当前未运行。

## 6. 已有结果的可用性分级

### 6.1 仅冒烟/功能证据

`results/benchmark-smoke-final` 为 B0--B3、seed 11、20 秒。该窗口没有足够完成行程和排队发展，只能证明四个控制器能接入闭环。

本轮 5 秒 performance smoke 同样仅作运行环境验证。

### 6.2 历史长时运行

仓库存在多份 1,800 秒 `actual_run=true` 结果。例如：

- `results/exp-5762c0f4f3b4`：B3、seed 42、物理 MQTT 历史运行；
- `results/exp-caabd10ff439`：B0、BASE、seed 42、1,800 秒、模拟总线，2026-08-20 完成；
- 多份 B3、BASE、seed 42、1,800 秒模拟总线结果。

这些结果可作为系统长时运行、结果格式和复现性审计证据，但不能作为多种子算法排名，原因包括：

- 算法和 seed 分布不完整；
- 多份结果是相同 seed/config 的演示重复；
- BASE 同时包含施工、活动、事故和应急扰动，不是纯基准；
- 部分结果来自不同代码工作树和部署方式；
- 缺少统一 warm-up 后处理和正式实验 ID/失败清单。

### 6.3 不可直接采用的旧指标

现有 `MetricsAccumulator` 中：

- `mean_waiting_time` 是活动车辆累计等待值的时间平均，不是 SUMO 完成行程标准等待时间；
- `mean_time_loss` 采样被写为 0，不能使用；
- `stop_count` 是末时刻停车车辆数，不是行程停车次数；
- 未直接输出队列 P95；
- fuel/CO2/NOx 是逐步瞬时率求和，只在 1 秒步长下等价于该窗口积分；
- 当前 runner 未实现 warm-up 剔除；
- 不带 persistence callback 时不保存实体轨迹。

正式处理必须以 `tripinfo.xml` 的 completed/unfinished、`waitingTime`、`timeLoss`、`waitingCount` 为标准行程来源，并从 raw 每步样本计算队列均值、最大值和 P95。缺失指标写 `NA`，不得用 0 代替。

## 7. 正式实验前必须新增的能力

### P0：正式矩阵门禁

1. 建立 `experiments/formal_2026/{configs,raw,processed,figures,tables,logs,scripts,metadata}`。
2. 统一 runner 生成不可变 `experiment_id`、配置快照、环境清单、哈希、状态和日志。
3. 原始 SUMO XML、逐步样本、事件、通信记录和安全结果写入 `raw/`，后处理只写 `processed/`。
4. 实现 warm-up 过滤和 `tripinfo.xml` 标准指标解析。
5. 计算平均/最大/P95 排队、完成行程、吞吐、标准等待、timeLoss、速度、燃油与排放。
6. 建立 `formal_experiment_matrix.csv` 和 `experiment_failures.csv`，失败和重跑都保留。
7. 通信 profile 必须显式写入 `ExperimentControl.channel_config`；不能只依赖 S07 metadata。
8. `cloud_offline` 必须走 `ExperimentConfig.cloud_outage_*` 或显式故障计划，不能交给物理扰动 runtime 的默认分支。
9. 先运行最小矩阵，检查有无完成行程、非零队列、控制动作和合理输出，再冻结正式时长。

### P1：可选增强

- 保存 5 秒或更低频率的核心走廊轨迹/速度切片，用于时空图；
- 单独运行安全核构造用例并记录 accept/modify/reject latency；
- 记录 API/WebSocket 性能只作为系统工程实验，不与交通算法效果混合；
- 真实 MQTT/Broker 中断实验仅在 Docker Engine 恢复且外部服务可审计时执行。

## 8. 建议的正式实验设计

最终矩阵必须由 pilot 的运行成本和数据质量决定，不能机械采用 600 + 3,600 秒。当前完整 1,800 秒历史运行实时因子约为 0.28--0.34，因此先做性能优化与 pilot。

最低可接受设计：

| 实验族 | 控制变量 | 候选矩阵 | 用途 |
|---|---|---|---|
| 算法基准 | 无扰动、N0 | B0--B3 x Low/Medium/High（或 Oversaturated）x 5 seeds | 主排名 |
| 扰动鲁棒性 | 同 seed、同事件 | B0/B2/B3 x 施工/活动散场 x 5 seeds | 恢复与峰值 |
| 通信鲁棒性 | B3、同交通需求 | N0/延迟/抖动/丢包/离线 x 5 seeds | 性能退化和 fallback |
| 安全内核 | 固定构造输入 | S1--S5 重复计时 | accept/modify/reject |
| 协同价值 | 核心走廊 | B0/B2/B3 x 5 seeds | 区域协调 |
| 系统稳定性 | 固定配置 | 1 个 1,800 秒或更长 run + 批处理完成率 | 运行稳定性 |

正式 seed 集合采用用户指定的 `[42, 123, 2026, 3407, 9001]`，所有算法共享同一集合。若资源只允许 5 seeds，不再以单次 seed 结论替代总体结论。

## 9. 环境风险和处置

- Windows 中文工作区会触发 SUMO XML 校验和路径兼容警告；adapter 已把配置和输出暂存到 ASCII 临时目录。正式元数据记录该 staging 行为。
- 可移植包包含 SUMO 1.27.1 二进制，但缺失 `traci`/`sumolib` Python 模块；本轮已在 `.venv` 安装 1.27.1。可移植包本身仍需另行修复，不能作为正式实验环境的唯一来源。
- `libsumo` wheel 在当前精简 SUMO 运行时缺少 GDAL/GEOS/OSG 等 DLL，不能稳定导入；正式 pilot 继续使用已验证的 TraCI 后端。
- 本机只有 8 GB RAM，审计期间可用内存低于 1 GB；并行度必须由 pilot 决定，默认不超过 2。
- Docker CLI 可用但 Engine 未运行；不把未启动的 TimescaleDB/Mosquitto/Redis 写为本轮实际参与组件。

## 10. 进入 runner 实施的判定

结论：**有条件就绪**。

条件是先补齐第 7 节 P0 项并通过一个具有完成行程、排队和控制动作的 pilot。只有 pilot 数据质量通过后才冻结正式矩阵。报告和图表不得在 raw 数据形成前编写数值结论。
