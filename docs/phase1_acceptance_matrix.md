# Phase 1 逐条验收矩阵

验收快照日期：2026-08-06

状态定义：

- **通过**：已有实现，并由自动测试或实际运行证据验证；
- **通过（边界）**：按 Phase 1 条款完成工程接口，但明确不扩张为现场标定、真实云主机部署或 AI 训练结论；
- **按规约预留**：条款本身只要求正式占位接口，本阶段不得伪造结果。

## 1. 项目背景与总体目标

| 条款 | 状态 | 证据 |
|---|---|---|
| 预测—协调—自治云边车闭环 | 通过 | `src/traffic_platform/{cloud_service,edge_service,vehicle_agent}`；新场景本机闭环`smoke-coordinated-max-pressure-bce923a2` |
| SUMO 数字靶场，支持通信异常和算法插拔 | 通过 | `sumo_adapter`、`communication_emulator`、`algorithm_sdk` |
| 不少于 20 个路口 | 通过 | `generate-demo-scenario --verify-only`：20 路口、20条直接邻接边、连通 |
| 完整端到端链路而非孤立模块 | 通过 | 真实 MQTT 实验产生 140/551 条远程边缘动作和独立报告 |

## 2. 工作方式与仓库检查

| 条款 | 状态 | 证据 |
|---|---|---|
| 先检查 OSM、SUMO、Excel、前后端、Docker | 通过 | `docs/current_state.md` |
| 不删除主办方资产，增量建设 | 通过 | 原始资料留在仓库外；只读哈希清单位于 `scenarios/generated/official_20_independent/manifest.json` |
| 缺少官方连通网时建立明确标注的工程场景 | 通过 | `official_20_independent` 与 `xiongan_rongdong_20` 分离 |
| 真实 OSM 可替换，不改算法主体 | 通过 | 场景引擎输出统一 `controlled_intersections.json` 和 `NetworkTopology` |
| 关键决策记录 ADR | 通过 | `docs/adr/0001`—`0011`，含完整 OSM、多主体条件并行、独立 RSU、TimescaleDB |

## 3. 技术栈

| 条款 | 状态 | 证据 |
|---|---|---|
| Python 3.12、FastAPI、Pydantic v2、SQLAlchemy 2、Alembic、asyncio、科学计算栈 | 通过 | `pyproject.toml`、`deployment/alembic` |
| SUMO/TraCI、libsumo 入口、GUI/无界面 | 通过 | `TraciSumoAdapter(backend="traci"|"libsumo")`；`make demo-gui` |
| MQTT/REST/WebSocket | 通过 | Mosquitto 实跑、OpenAPI、`/ws/v1/realtime` |
| TimescaleDB、Redis、批量写入和采样 | 通过 | TimescaleDB 2.29.1；三个 hypertable；`storage/database.py`、`storage/buffer.py`、迁移 0001—0003 |
| React/TypeScript/Vite/ECharts | 通过 | 前端生产构建、Vitest、Playwright |
| Docker/Compose/Make/Ruff/Mypy/Pytest/Vitest/Playwright/CI | 通过 | 默认 Dockerfile 全新构建；78 后端测试；GitHub Actions |
| Prometheus、健康检查、JSON 日志、trace_id | 通过 | `traffic-platform=1`、`/ready` 心跳、统一消息信封 |
| TimescaleDB | 通过 | 本机 Compose 实际启用 2.29.1，3 hypertable、6 个压缩/保留策略；迁移前备份已校验 |

## 4. 总体架构与模块边界

| 条款 | 状态 | 证据 |
|---|---|---|
| apps 服务角色加 Web | 通过 | cloud、rsu、edge、vehicle、experiment、report、sumo-runner 与 web-dashboard 均可独立运行 |
| packages 九公共模块 | 通过 | `packages/contracts` 至 `packages/common` |
| algorithms B0—B4 | 通过 | 五个算法目录及运行时注册表 |
| 模块只经契约/接口交互 | 通过 | Pydantic 消息、MessageBus、SDK、SUMO adapter；依赖规则在 `system_architecture.yaml` |

## 5. 双场景与场景规范

| 条款 | 状态 | 证据 |
|---|---|---|
| 官方 20 独立路口保留并完成SUMO复现 | 通过 | 20 Excel、20 PNG、4个主办方SUMO示例；派生20路口×3时段，60/60实跑和需求守恒，审计见`outputs/official_20_audit` |
| 完整 OSM 中的 20 个稳定控制/观测点 | 通过 | K01—K08/B01—B12 属于同一连通区域；底网不裁剪，背景 OD 可使用完整 OSM |
| 8 路口核心走廊、集中源、下游瓶颈、绕行、可关闭车道、潮汐流 | 通过 | 场景 YAML、连续受控拓扑、三组分时 OD 和扰动目录 |
| S01—S07 | 通过 | 7 个确定性配置与生成 route/sumocfg |
| 六类车辆、五档网联渗透率 | 通过 | vType 和 `scenario_spec.yaml` |
| YAML 包含时间、步长、种子、OD、车型、倍率、信号、扰动、通信、算法、采样 | 通过 | `ScenarioConfig` 严格校验 |
| 同配置同种子可复现 | 通过 | 场景/manifest 哈希和需求生成测试 |
| 车辆跨多个路口连续行驶 | 通过 | 走廊验证 OD 至少经过 5 个观测点；背景 OD 使用完整网络，不人为强制全部车辆聚焦 20 路口 |

## 6. 云、边、车职责

| 条款 | 状态 | 证据 |
|---|---|---|
| 云端区域状态、拓扑、风险、绿信比/周期/偏移/限流/疏散/速度目标 | 通过 | `cloud_service/coordinator.py` |
| 独立 RSU 感知校验和路侧汇总 | 通过 | `rsu-service`；Compose 实验中 RSU→Edge→Cloud 序列连续且乱序拒绝为 0 |
| 下游饱和时抑制上游，云只下发目标 | 通过 | 协调器测试；ADR 0003 |
| 边缘采集、算法、安全校验、执行、反馈、自治、固定配时回退 | 通过 | `EdgeController`、`ServiceWorker`、降级状态机 |
| 安全 > 本地硬条件 > 云目标 > 本地优化 | 通过 | safety-kernel 与控制器组合顺序 |
| 车端遥测、网联速度引导、非网联默认、应急优先、执行差异 | 通过 | `vehicle_agent`、S06、SUMO 命令证据 |
| 云端不能绕过边缘直接切灯 | 通过 | MQTT 方向为 CloudStrategy→EdgeControlAction→SUMO；安全核在边缘 |

## 7. 统一数据契约

| 条款 | 状态 | 证据 |
|---|---|---|
| 14 个公共信封字段、SI 单位 | 通过 | `TrafficMessage`、`data_dictionary.yaml` |
| Vehicle/Bicycle/Pedestrian/Lane/Intersection/Regional/Strategy/Action/Feedback/Communication/Fault/Conflict | 通过 | 严格 Pydantic + 19 个 JSON Schema |
| 类型严格、版本、示例、校验、序列化 | 通过 | `extra=forbid`、strict、Schema 验证测试 |
| 过期拒绝、重复幂等、乱序保护 | 通过 | `ensure_not_expired`、`IdempotencyGuard`、契约测试 |

## 8. REST、WebSocket 与 MQTT

| 条款 | 状态 | 证据 |
|---|---|---|
| 指定的健康、场景、实验、算法、故障、路口 API | 通过 | `specs/openapi.yaml` 与实现一致性测试 |
| `/ws/v1/realtime` | 通过 | 驾驶舱 Playwright 使用实际后端 |
| 指定状态/策略/反馈/车辆/实验主题 | 通过 | `mqtt_topics.yaml` |
| 每主题发布者、订阅者、模型、QoS、retained、TTL、频率、失败策略 | 通过 | MQTT 主题规约完整 |
| MQTT TLS、账号、证书路径 | 通过 | `MQTT_TLS_*` 实际进入 paho 客户端；云端 Mosquitto TLS 配置 |

## 9. 算法 SDK 与基线

| 条款 | 状态 | 证据 |
|---|---|---|
| initialize/reset/observe/decide/feedback/health/close | 通过 | `TrafficControlAlgorithm` Protocol |
| 注册、发现、配置、版本、切换、超时、隔离、耗时、日志、解释 | 通过 | registry、`IsolatedAlgorithmRunner`、API |
| B0 固定配时 | 通过 | 新场景实跑`smoke-fixed-time-dc2b6e68` |
| B1 感应控制 | 通过 | 算法单测和四算法基准 |
| B2 最大压力和下游饱和保护 | 通过 | 压力计算测试和基准 |
| B3 云边协调、策略超时自治 | 通过 | `exp-b3df9bd353f1` |
| B4 无模型明确失败 | 按规约预留 | 返回 `MODEL_NOT_AVAILABLE`，不生成随机预测 |
| STGNN/MPC/MARL 正式接入门禁 | 按规约预留 | artifact 哈希、签名、训练/验证门禁；当前无训练模型 |

## 10. 安全控制内核

| 条款 | 状态 | 证据 |
|---|---|---|
| 最小/最大绿、黄灯、全红、冲突、行人、过期、实验/版本、溢出、异常、应急 | 通过 | `SafetyKernel` 与单元测试 |
| 速度上限、动力学和急减速 | 通过 | 车辆安全测试 |
| accepted/modified/rejected 及原始/修改原因 | 通过 | `SafetyResult`、事件时间线、拒绝计数 |

## 11. 通信模拟与真实故障

| 条款 | 状态 | 证据 |
|---|---|---|
| 非 `sleep` 的事件队列 | 通过 | `SimulatedChannel` 使用仿真时间优先队列 |
| 固定/随机延迟、截断抖动、丢包、重复、乱序、带宽、超时、离线、恢复、损坏 | 通过 | 通信模型和 unit/chaos 测试 |
| N0—N8 | 通过 | `communication_model.yaml` |
| 所有通信事件记录 | 通过 | `CommunicationEvent` 与实验结果 |
| 真实 Broker 中断自动恢复 | 通过 | `exp-c049f7bf9c37`，物理重启后 completed |

## 12. 故障降级状态机

| 条款 | 状态 | 证据 |
|---|---|---|
| CLOUD_COORDINATED/HOLD_LAST_VALID/EDGE_AUTONOMOUS/FIXED_TIME_SAFE/RECOVERY_SYNC | 通过 | 五种枚举和六段转换流程 |
| 过期、重复、乱序、重放、重启、暂停、时间回退、实验不匹配、恢复突变 | 通过 | 状态机/幂等/恢复测试 |
| 云断网后自治，恢复后平滑同步 | 通过 | 实跑在 21/36/40/45 秒出现四次关键转换 |
| 故障按实验隔离 | 通过 | `experiment_ids` 作用域，防止新实验时间回零时重放旧故障 |

## 13. SUMO 适配器

| 条款 | 状态 | 证据 |
|---|---|---|
| 生命周期、状态、信号、速度、车道、事件、订阅方法 | 通过 | `TraciSumoAdapter` 公共接口 |
| GUI/无界面、TraCI/libsumo | 通过 | `demo-gui` 和 backend 选择 |
| ID 映射集中，算法无硬编码车道 | 通过 | `TopologyMapper`/场景选择文件 |
| 多实验唯一端口、超时、异常、退出释放 | 通过 | free-port、label、lifecycle 测试 |

## 14. 场景生成与扰动

| 条款 | 状态 | 证据 |
|---|---|---|
| 校验、netconvert、OD、车型、信号、扰动、manifest、哈希 | 通过 | 场景实际全量重建 |
| 600/900/1200/1500 类型扰动 | 通过 | 场景 YAML、disturbance runtime |
| 扰动事件记录 | 通过 | 综合故障演示事件和报告 |

## 15. 实验、指标与报告

| 条款 | 状态 | 证据 |
|---|---|---|
| 公平协议只改变算法，种子 `[11,23,37,41,59]` | 通过 | `benchmark_protocol.yaml` |
| 交通效率、传播、环境、工程、鲁棒性指标 | 通过 | metrics engine；不可观测项明确 `not_available` |
| JSON/CSV/HTML/图表/manifest/参数/版本/哈希/时间戳 | 通过 | 报告生成器与 acceptance 结果 |
| 不编造提升 | 通过 | 短窗口无完成行程时不作算法优劣结论 |
| 5 种子 × 4 算法 × 1,800 s 正式矩阵 | 尚未完成 | 协议和 Student-t 95% CI 已实现；截至本快照只有单种子短时冒烟 |

## 16. 数据采集与性能

| 条款 | 状态 | 证据 |
|---|---|---|
| 分级采样，非逐车同步写库 | 通过 | 场景 sampling 配置和 trajectory 迁移 |
| 机动车/骑行/行人轨迹分主体批量持久化 | 通过 | `participant_kind` 批次；TimescaleDB trajectory hypertable；Compose 实验写入 12 批 |
| 内存缓冲、批量、背压、优先级丢弃、保留、结束刷新、DB 降级 | 通过 | `BufferedBatchWriter` 和混沌测试 |
| CPU/内存/实时因子/决策/写入延迟 | 通过 | performance smoke 和实际结果 |

## 17. 实时驾驶舱

| 条款 | 状态 | 证据 |
|---|---|---|
| 顶部状态、20 路口、相位、车道详情、扰动、传播 | 通过 | React 页面和实际截图 |
| 8 个实时指标与多组曲线 | 通过 | ECharts 真实 WebSocket 数据 |
| 生命周期、算法、施工、延迟、丢包、断网、清除、报告控制 | 通过 | 控制区调用真实 REST |
| 事件时间线 | 通过 | 策略、动作、安全、故障、降级、恢复、扰动 |
| 无静态随机假数据 | 通过 | Playwright 捕获实际 API/WS；无随机演示指标 |

## 18. Docker、部署与安全

| 条款 | 状态 | 证据 |
|---|---|---|
| 指定 Compose 服务及独立 RSU | 通过 | 根 `docker-compose.yml`，实际物理 MQTT + Timescale + RSU 运行 |
| 单机拓扑 | 通过 | 全部容器健康、API 仅绑定回环 |
| 阿里云 + 本地边缘拓扑 | 通过（边界） | 两份独立 Compose 均 `config --quiet` 通过；未实际部署阿里云 |
| 环境变量、无硬编码云 IP/AccessKey/密码 | 通过 | `.env.example`；秘密不提交 |
| 防火墙、卷、健康、重启、优雅关闭、备份 | 通过 | `docs/deployment/alicloud.md` |
| 公网 MQTT 认证与 TLS | 通过 | `mosquitto.cloud.conf`、paho TLS 客户端 |

## 19. Makefile 与启动命令

`bootstrap`、`validate`、`generate-demo-scenario`、`up`、`down`、`demo`、
`demo-gui`、`benchmark`、`benchmark-smoke`、`fault-demo`、`report`、`test`、
`lint`、`e2e` 均有真实命令。验收已直接执行其底层等价命令；默认 Dockerfile
也已从零构建成功。另在 Linux/SUMO 容器内字面执行 `make demo`，得到
`smoke-coordinated-max-pressure-b37773e0`，`actual_run=true` 且五类报告产物齐全。

## 20. 测试

| 类别 | 状态 | 结果 |
|---|---|---|
| unit | 通过 | 模型、算法、协调、安全、状态机、通信、指标、场景、存储 |
| contract | 通过 | OpenAPI、MQTT Schema、版本、过期、幂等、错误码 |
| integration | 通过 | SUMO/TraCI、MQTT、扰动、实时故障 |
| e2e | 通过 | 完整垂直闭环 |
| chaos | 通过 | 100/500ms、10% 丢包、云断开、DB 不可用、故障生命周期 |
| performance | 通过 | 20 路口性能冒烟 |
| 全集合 | 通过 | 100 collected；默认环境 92 passed，真实 SUMO/Mosquitto 补跑 8 passed，合计无未验证跳过项 |
| 前端 | 通过 | 最新多主体界面 Vitest 1、生产构建、Playwright 1 |

## 21. 文档

README、五类 Mermaid 架构图、数据字典、接口指南、B0—B3、基准协议、
阿里云部署、5—8 分钟演示脚本和十一份 ADR 均存在并与当前实现一致。

## 22. 最终 Phase 1 验收结论

Phase 1 的机器规约、双场景、完整 OSM 中的 20 个稳定观测点、真实 RSU—云—边—车闭环、安全控制、故障降级、B0—B3、Timescale、报告和驾驶舱已有实跑证据。本轮多主体扩展后的全测试与长时正式矩阵仍在收尾，未完成项不计为通过。

以下内容不被错误计为“未完成”：

- B4 按本阶段要求是正式占位接口；
- TimescaleDB 已实际启用；Grafana 仍为可选且不替代本项目驾驶舱；
- 阿里云真实主机上线和现场交通标定属于外部环境/Phase 2，不伪造为已验证；
- 用户明确排除现场交通标定，本阶段不会实施；
- 算法性能提升必须在长时多种子实验后再下结论。
