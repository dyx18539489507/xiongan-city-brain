# 面向雄安新区“城市大脑”的车路云一体化协同管控与仿真平台

本仓库交付 Phase 1“可执行系统总规约与端到端垂直闭环”。它不是静态概念方案：完整 OSM 派生 SUMO 中的机动车、自行车、电动自行车和行人状态经独立 RSU、边缘端、物理 MQTT 和云端协调后，由安全内核和 TraCI 返回信号/速度控制，并产生 TimescaleDB 指标、事件、报告和 WebSocket 驾驶舱数据。

## 数据与场景边界

- `official_20_independent`：主办方 20 个独立路口数据复现集。20 份 Excel 和 20 张高精地图均纳入只读哈希清单；主办方只提供了 4 个 SUMO 案例，因此不把这套资料描述成一个连通区域路网。
- 独立路口1—4保留主办方SUMO道路长度；5—20保留OSM道路走向和原始测距证据，但统一使用250 m仿真边界，避免普通OSM分段节点造成不公平的入口储车长度。
- `xiongan_rongdong_20`：基于容东片区完整 OpenStreetMap 地理关系构建的区域工程验证场景。主控制区保留 `demo_14`、`demo_15`、`demo_17`、`demo_18`、`demo_19`、`demo_20` 六个图像配准位置估计，以 14 个相邻 OSM 路口形成 K01—K08/B01—B12 稳定控制与观测点；`demo_13` 和 `demo_16` 仍完整保留在官方独立场景中。新增参数从排除六个锚点后的主办方其余路口捐赠池，通过 Gower 距离、逆距离加权、容量缩放、Dirichlet 平滑和图拉普拉斯平滑建模。

第二套场景具有真实地理关系，但尚未经过现场流量和高精测绘标定，不能称为运营级数字孪生。
区域 OD 分为控制走廊验证路线和完整网络背景路线：前者至少连续经过 5 个观测点，后者允许使用完整 OSM，避免把全网交通强制聚焦到 20 路口。SUMO-GUI 不强制聚焦、隐藏或裁剪外围网络；K01—K08 为核心走廊，B01—B12 为背景观测点。

多主体网络是同一完整 OSM 的派生产物，不覆盖冻结底网。行人信号采用条件并行：只在路网确有横道且冲突关系可验证时并行放行；当前 20 个观测点中 11 个具备平面受控横道证据，不伪造其余路口。

官方20个独立路口均已生成三个时段。它们按主办方 Excel 逐个保留15分钟流量与
固定配时；1—4号参考主办方SUMO示例，5—20号结合主办方PNG与OSM形成工程模型：

```powershell
$env:SUMO_HOME='C:\path\to\sumo'
$env:TRAFFIC_ORGANIZER_SOURCE_ROOT='D:\path\to\赛题资料\赛题资料'
.\.venv\Scripts\traffic-platform.exe generate-official-intersections --jobs 4
.\.venv\Scripts\traffic-platform.exe audit-official-intersections --output outputs\official_20_audit
```

生成位置为 `scenarios/generated/official_20_independent/demo_1` 至 `demo_20`；
完整证据与实跑结果见 [官方20路口审计](docs/benchmark/official-20-sumo-audit.md)。
全部小汽车使用纯黄`#FFFF00`主题色和`simple shapes`，SUMO-GUI delay统一为300ms。
全部小汽车仅用于PCU数值复现，不代表主办方提供了真实车型比例。

## 架构

代码采用模块化单体仓库：`src/traffic_platform` 是可安装 Python 包，`apps` 是部署入口，`packages` 和 `algorithms` 提供逻辑模块索引。模块只通过 Pydantic 契约、算法 SDK、SUMO 适配器和消息总线交互。

完整图见 [系统总览](docs/architecture/system-overview.md)，接口见 [接口指南](docs/api/interface-guide.md)。

## 快速启动

要求 Python 3.12、Node.js 22 和 Eclipse SUMO。设置 `SUMO_HOME` 后执行：

```bash
make bootstrap
make validate
make generate-demo-scenario
make demo
```

Windows 没有 GNU Make 时，命令一一对应：

```powershell
.\deployment\scripts\task.ps1 bootstrap
.\deployment\scripts\task.ps1 validate
.\deployment\scripts\task.ps1 demo
```

本机驾驶舱：

```powershell
.\.venv\Scripts\traffic-platform.exe serve --host 127.0.0.1 --port 8000
cd apps\web-dashboard
npm run dev -- --host 127.0.0.1
```

打开 `http://127.0.0.1:5173`。页面未运行实验时显示“尚未运行”，不会使用静态随机指标。

Windows 一键启动正式 Web 3D 演示（会启动一组真实 `xiongan_rongdong_20` fixed-time 实验）：

```powershell
.\scripts\start_3d_demo.ps1
```

脚本默认使用后端 `8013`、前端 `5177`，避开当前 Docker 驾驶舱的 `8000/5173`；端口仍可用 `-BackendPort`、`-FrontendPort` 显式覆盖。

运行已有、经过配置校验的 S01—S07 工况时显式传入 `-Profile`；例如 S02 高峰：

```powershell
.\scripts\start_3d_demo.ps1 -Profile S02 -Algorithm fixed-time -Seed 52
```

网页“工况”选择器提供同一组 `BASE/S01—S07`。后端会选择对应
`xiongan_rongdong_20.<profile>.sumocfg`，并把工况代码写入实时状态、结果 JSON
和输入文件哈希清单；不会在前端伪造流量或事件。

只启动前后端、不创建实验可使用 `-SkipExperiment`；一键停止：

```powershell
.\scripts\stop_3d_demo.ps1
```

脚本只绑定回环地址，状态与日志位于 `outputs/3d/runtime/`；停止脚本只处理状态清单中且命令行属于本仓库的精确 PID。

在目标电脑前台运行 S01—S05 固定镜头性能矩阵（默认会打开独立 Chromium，
结果和截图写入 `outputs/3d/benchmarks/`）：

```powershell
.\scripts\benchmark_3d.ps1
```

`-Headless` 只用于验证基准工具，脚本会在 JSON 中标记
`headless-structural-not-gpu-acceptance`，其 SwiftShader FPS 禁止作为 MX250 结果。

长时并发稳定性采样：

```powershell
.\scripts\benchmark_3d_stability.ps1 -Profile S02 -DurationS 1800
```

脚本会记录实际 WebGL renderer、浏览器堆、实体数、页面错误和仿真终态；达到墙钟上限但未完成仿真时会明确标记，不能冒充完整长稳通过。

## Web 3D 开发状态

Web 3D 数字孪生已形成 Phase 0—14 工程闭环：联通 `xiongan_rongdong_20` 的统一场景、真实机动车/非机动车/行人、20 个 TLS、施工/事故/大型活动、真实 TTC/PET 冲突、天气昼夜、分析图层、路侧设备、自适应质量、真实实验回放和 DemoDirector 共用一套 Three.js WebGLRenderer。LIVE 使用后端 `init + delta`，REPLAY 流式读取后端录制的真实 NDJSON；车辆、信号、事件、冲突、KPI 和 20 路口汇总均来自 ExperimentRunner/TraCI。公交、卡车、配送车与 K06 车辆实际加载 Draco optimized GLB；道路基础材质实际加载经 Khronos KTX-Software 编码并校验的 ETC1S KTX2；K06 近景按需加载 Blender 原创建筑层，SUMO 道路仍是唯一几何真值；TLS 具备真实方向/人/非机灯面，近景行人使用低骨骼蒙皮。2026-08-10 当前冻结代码的 MX250 45 组合矩阵平均 15.27 FPS、中位 15.0、最差组合平均 8.1、最低 P1 1.1；最终代码 1811.2 秒采样窗长稳在峰值 379/128/51 个机/非/人实体下 0 page errors、0 sampling timeout，平均 19.31 FPS。正式 6 分钟同 seed 成对比赛脚本、高精人物资产和 25–30 FPS 目标仍未关闭。逐节证据与边界见 [70 节验收矩阵](docs/3d/full_requirement_acceptance.md)，不得只写“全部完成”。

生成静态场景：

```powershell
.\deployment\scripts\task.ps1 generate-3d-scene
```

生成物位于 `generated/scenes/`。阶段审计和数据契约见 [当前项目审计](docs/3d/current_project_audit.md)、[70 节验收矩阵](docs/3d/full_requirement_acceptance.md)、[三维架构](docs/3d/architecture.md)、[场景流水线](docs/3d/scene_pipeline.md)、[坐标系统](docs/3d/coordinate_system.md)、[实时协议](docs/3d/realtime_protocol.md)、[车辆系统](docs/3d/vehicle_system.md)、[信号灯系统](docs/3d/traffic_light_system.md)、[城市环境](docs/3d/urban_context.md)、[机非人系统](docs/3d/multimodal_system.md)、[扰动事件映射](docs/3d/event_visualization.md)、[天气与昼夜](docs/3d/environment_system.md)、[分析模式与RSU](docs/3d/analytics_mode.md)、[自适应质量](docs/3d/quality_system.md)、[真实回放](docs/3d/replay.md)、[自动演示](docs/3d/demo_script.md)、[资产流水线](docs/3d/asset_pipeline.md)、[资产许可](docs/3d/asset_licenses.md)、[性能预算](docs/3d/performance_budget.md)、[性能实测](docs/3d/performance_report.md)、[视觉验收](docs/3d/visual_acceptance.md) 与 [已知限制](docs/3d/known_limitations.md)。

## Docker Compose

开发环境默认使用 `.env.example`，仅绑定本机回环地址。Compose 实验路径显式使用真实 Mosquitto；确定性内存总线只用于延迟、丢包、乱序和离线故障仿真：

```bash
make up
make down
```

启动后，驾驶舱位于 `http://127.0.0.1:5173`，Swagger API 文档位于
`http://127.0.0.1:5173/docs`，Prometheus 位于 `http://127.0.0.1:9090`。

生产或云边部署必须复制为私有 `.env`，替换口令，并启用 `deployment/mosquitto/mosquitto.cloud.conf` 的密码和 TLS。Compose 包含 cloud、edge、vehicle、experiment、report、web、PostgreSQL、Redis、Mosquitto、Prometheus 和可选 sumo-runner。

阿里云与本地边缘的拆分拓扑分别位于
`deployment/compose/alicloud-cloud.yml` 和
`deployment/compose/local-edge.yml`，具体证书、端口与主机 SUMO-GUI
启动方式见 `docs/deployment/alicloud.md`。

## 演示、故障与基准

```bash
make demo                 # 云边协调实际闭环
make demo-gui             # SUMO-GUI
make fault-demo           # 施工/散场/事故/应急 + 云断网/自治/恢复
make benchmark-smoke      # B0/B1/B2/B3，同场景同种子
make benchmark            # B0/B1/B2/B3 × 5 个种子
make report               # 从最近一次实际结果重新生成报告
```

结果写入 `results/`，包含 `result.json`、`summary.csv`、HTML、SVG、事件和场景哈希。没有运行就没有结果；仓库不预填性能提升结论。

`fault-demo` 把正式场景的扰动时间压缩到 1%，只为了在 70 秒内展示完整机制；流量、车型、控制链路和 TraCI 动作仍来自真实运行，但压缩结果不能用于算法性能结论。

## 测试

```bash
make lint
make test
make e2e
```

测试分为 `tests/unit`、`contract`、`integration`、`e2e`、`chaos` 和 `performance`。SUMO 集成测试需要 `SUMO_HOME`；前端使用 Vitest 和 Playwright。

历史验收快照和本轮最新实跑证据分别见 `docs/phase1_acceptance_matrix.md` 与
`docs/current_state.md`。测试数字只在重新运行后更新，不沿用旧快照冒充当前代码结果。

## 下一阶段

紧扣赛题 PDF、以赛道 A 为主并融合赛道 B/C 的 Phase 2 工程执行提示词见
[`docs/prompts/phase2_engineering_prompt.md`](docs/prompts/phase2_engineering_prompt.md)。
其主线是轻量时空预测、预测驱动云边协调、ONNX 部署、长时多种子基准和
竞赛级证据包，不改变 Phase 1 的安全闭环、完整 OSM 和双场景数据边界。STGNN/MPC/MARL 目前只有严格激活接口，没有训练模型或伪造输出。

## 目录

```text
apps/           部署入口与 React 驾驶舱
packages/       公共协议模块索引
algorithms/     B0-B4 算法入口索引
src/            Python 实现
scenarios/      只读来源、配置与派生场景
specs/          OpenAPI、MQTT、JSON Schema 与验收规约
tests/          六层自动化测试
deployment/     Docker、Compose、MQTT、Prometheus、Alembic
docs/           架构、接口、算法、基准、部署、ADR、演示
```

## 常见问题

- `SUMO_HOME is required`：把它指向包含 `bin` 和 `tools` 的 SUMO 安装目录。
- Windows 中文路径出现 TraCI/校验异常：使用仅含 ASCII 的目录联接作为 `SUMO_HOME`，并先验证 `sumo --version`、`import traci` 和 `import sumolib`。
- 为什么不是直接拼接主办方 20 路口：它们是独立案例，强行连线会伪造道路关系。
- 为什么容东场景仍标记工程模型：OSM 提供地理拓扑，但新增流量、转向和配时来自数学迁移，不是现场观测。
- 为什么不是 20/20 行人横道：条件并行必须有 OSM/SUMO 横道和冲突连接证据；缺证据时不伪造道路设施。
- TimescaleDB 是否启用：已启用 2.29.1，metrics/events/vehicle_trajectories 为 hypertable；`/ready` 会返回扩展状态。
- Docker 起不来：先运行 `docker compose --env-file .env.example config`，再确认 Docker Desktop/Engine 已启动。
- 主办方数据在哪里：通过 `TRAFFIC_ORGANIZER_SOURCE_ROOT` 指向仓库外只读目录，派生清单写入 `scenarios/generated`。
