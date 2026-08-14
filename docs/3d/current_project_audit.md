# Web 3D 数字孪生 Phase 0 当前工程审计

- 审计日期：2026-08-07
- 工作区：`D:\程序项目\面向雄安新区的城市大脑`
- 审计阶段：Phase 0，仅审计与只读验证
- 主场景：`xiongan_rongdong_20`
- 证据边界：本文件冻结描述 2026-08-07 Phase 0 修改前基线；后续实现不回写为当时已存在，当前完成态以 `full_requirement_acceptance.md` 为准

> 2026-08-09 复验附记：Phase 0 发现的统一 scene、CoordinateService、实时实体协议、对象池/LOD/实例化、Draco、实际 ETC1S KTX2、K06 按需 Blender 建筑、MX250 矩阵和 30 分钟长稳缺口现已逐项实施或实测。下文“缺失/尚无”保留为审计时事实，不能再当作当前状态；仍未关闭的是稳定 25–30 FPS、现场/BIM/RF 标定、完整 3600 s 仿真和正式成对比赛脚本。

## 1. 结论先行

当前项目已经具备可靠的 SUMO 多主体底座、20 路口注册表、TraCI/libsumo 适配器、云边车控制链、指标/事件链、FastAPI 管理面和 React 驾驶舱。联通场景不是理想化棋盘：20 个控制点位于同一完整容东 OSM 派生网络，核心走廊 K01—K08 连续，控制点包络约为 `1.230 km × 2.146 km`。

当前项目还不具备“20 路口真实同步 Web 3D 数字孪生”。现有 Three.js 内容是 K06 单路口视觉样板：道路中心线和车辆路线在前端/Blender 脚本中人工定义，24 辆车由前端样板逻辑移动，三维信号灯按 12 秒周期交替，并未消费 SUMO 实体状态或真实 TLS link state。页面已经把它标为 preview，这一诚实边界必须保留到真实同步替换完成。

因此 Phase 0 判定为：

- SUMO/控制/指标工程底座：可复用；
- 20 路口静态几何数据源：可用，且通过本轮只读 ID 与坐标校验；
- 3D 实体级实时协议：缺失，是 Phase 1/Phase 3 的首要阻断项；
- 统一场景中间格式和坐标服务：缺失；
- 当前 K06 资产：可保留为视觉和资产预算参考，不能作为道路逻辑真值；
- 当前机器能否达到 720p 25—30 FPS：尚无 WebGL 实测数据，禁止提前声称达到。

## 2. 审计方法和未执行事项

本轮执行了：

1. 扫描仓库结构、docs、specs、场景、结果、测试、部署和前后端源码；
2. 解析 `rongdong.multimodal.net.xml`、全部主场景 route/additional/sumocfg 和 20 路口注册表；
3. 使用 SUMO 1.27.1 的 `sumolib` 只读加载网络，校验 junction/TLS/edge/type/坐标；
4. 阅读 TraCI、聚合、控制、扰动、指标、持久化、REST、WebSocket 和 Three.js 数据路径；
5. 运行当前代码静态检查、单元测试和前端构建。

本轮没有：

- 重建或覆盖任何 SUMO 网络、路由或主办方资料；
- 启动新的 SUMO 实验或生成新的结果；
- 把历史运行数据冒充本轮性能测试；
- 修改 `official_20_independent`；
- 测量浏览器 FPS、GPU 或显存；
- 实施 Phase 1 场景 JSON。

注意：`generate-demo-scenario --verify-only` 仍会重写 `scenario_manifest.json`，因此本轮没有用它充当只读验证命令。

## 3. 仓库与版本状态

### 3.1 Git 状态

仓库存在 `.git`，但没有可解析的 `HEAD`，当前全部工程文件均为 untracked。结果是：

- 无法用 Git 区分本轮改动与既有文件；
- 无法引用提交号作为场景、代码或实验的来源；
- 无法可靠回滚到已知验收基线。

这是竞赛证据链和后续性能回归的工程风险。进入大规模开发前应建立首次基线提交，但不能在未经用户授权时替用户提交。

### 3.2 主要目录职责

| 目录 | 当前用途 | 3D 阶段处理 |
|---|---|---|
| `src/traffic_platform` | Python 主实现，83 个 Mypy 检查源文件 | 复用并新增 scene/realtime/replay 边界 |
| `apps/web-dashboard` | React 19 + TypeScript + Vite + ECharts + Three.js | 保持 React，不重写框架 |
| `scenarios/configs` | 主场景、官方场景和 S01—S07 配置 | 保持只读语义，3D 不改变实验步长 |
| `scenarios/generated/xiongan_rongdong_20` | 联通场景网络、需求、清单 | 作为 3D 静态真值输入 |
| `scenarios/generated/official_20_independent` | 主办方 20 个独立路口派生复现集 | 继续只读，不进入联通 3D 生成链 |
| `specs` | OpenAPI、MQTT、JSON Schema、验收规约 | 增量增加 3D 协议规约，不破坏现有协议 |
| `results` | 真实实验结果和报告 | 现有结果可审计，但不是完整 Replay 轨迹包 |
| `assets/3d/k06` | K06 Blender 主文件、原创纹理和来源说明 | 保留为 hero 资产参考 |
| `tools/visualization` | K06 Blender 生成脚本 | 后续与自动场景生成、资产优化流水线分开 |

## 4. 当前开发机与运行时

2026-08-07 本轮只读探测结果：

| 项目 | 当前值 | 结论 |
|---|---|---|
| CPU | Intel Core i7-8565U，4 核 8 线程 | 以 CPU 解析、批处理和低 Draw Call 为约束 |
| 物理内存 | 8,428,179,456 bytes，约 7.85 GiB | 必须按场景加载和回收 |
| 本轮探测空闲内存 | 约 1.04 GiB | 开发期同时运行浏览器、IDE、Docker 风险高 |
| 独显 | NVIDIA MX250，2 GiB | 禁止重型后处理和无界纹理加载 |
| 集显 | Intel UHD Graphics 620 | 浏览器可能落到集显，性能报告需记录实际适配器 |
| D 盘空闲 | 64,737,095,680 bytes，约 60.29 GiB | 资产流水线可用，但要避免缓存无界增长 |
| 系统 Python | 3.13.9 | 不作为项目运行时 |
| 项目 `.venv` | Python 3.12.13 | 与 `pyproject.toml` 一致 |
| Node / npm | 24.13.0 / 11.6.2 | 当前前端构建通过 |
| SUMO | 1.27.1，含 Proj、GUI、SWIG | 本地安装可用 |
| Docker | 29.1.3 | 本轮未重建镜像 |

当前 `SUMO_HOME` 未永久配置，但可用安装位于：

`C:\Users\Yaxin Duan\AppData\Local\xiongan-traffic-brain\sumo`

本轮探测到 Vite 预览监听 `127.0.0.1:5174`；没有把它当作后端或 SUMO 正在运行的证据。

## 5. 场景边界与真值来源

### 5.1 两套场景必须继续隔离

1. `official_20_independent`
   - 主办方 20 个独立路口资料复现集；
   - 清单记录 20 份 Excel、20 张地图 PNG、4 个 sumocfg、30 个 SUMO XML；
   - 不是一个官方联通区域路网；
   - 本阶段不得修改或拼接。

2. `xiongan_rongdong_20`
   - 本阶段唯一正式联通 3D 场景；
   - 真实地理拓扑来自 OSM；
   - 参数包括主办方锚点迁移和工程建模，不是现场标定；
   - 不能表述为高精地图或运营级真实城市复刻。

### 5.2 主场景关键文件

| 类型 | 路径 | 当前作用 |
|---|---|---|
| 场景配置 | `scenarios/configs/xiongan_rongdong_20.yaml` | 1800 s、1 s 步长、seed 42、OD、类型、扰动、采样 |
| 场景预设 | `scenarios/configs/presets/S01-S07.yaml` | 平峰、高峰、活动、施工、事故、应急、通信异常 |
| 正式 sumocfg | `scenarios/generated/xiongan_rongdong_20/xiongan_rongdong_20.sumocfg` | 加载多主体网络和机动车/非机动车/行人需求 |
| 网络真值 | `scenarios/generated/xiongan_rongdong_20/rongdong.multimodal.net.xml` | 3D 道路、lane、connection、TLS、crossing 的几何/逻辑来源 |
| 冻结机动车底网 | `scenarios/generated/xiongan_rongdong_20/rongdong.control.net.xml` | SHA-256 `608dbe...e367`，不得被 3D 改写 |
| 机动车需求 | `routes.rou.xml`、`routes.S01.rou.xml`—`routes.S07.rou.xml` | 所有机动车出行 |
| 多主体需求 | `multimodal.rou.xml` | 自行车、电动自行车、行人 |
| additional | `vtypes.add.xml`、`functional_zones.add.xml` | 类型、POI、功能区显示 |
| 20 路口注册表 | `controlled_intersections.json` | 稳定 display ID、SUMO junction ID、位置、拓扑 |
| 路口详单 | `intersection_inventory.json/csv` | 进口、lane、movement、signal program、参数来源 |
| 多主体审计 | `multimodal_network_manifest.json` | 多主体设施与行人信号证据 |

正式 sumocfg 当前配置：

- network：`rongdong.multimodal.net.xml`；
- routes：`routes.rou.xml,multimodal.rou.xml`；
- additional：`vtypes.add.xml,functional_zones.add.xml`；
- begin/end：`0/1800 s`；
- step length：`1 s`；
- seed：`42`；
- teleport：关闭；
- collision action：`warn`。

## 6. 网络、坐标和几何审计

### 6.1 网络规模

`rongdong.multimodal.net.xml` 当前统计：

| 项目 | 数量 |
|---|---:|
| 普通 + crossing + walkingarea edge | 7,077 |
| ordinary road edge | 3,016 |
| crossing edge | 1,689 |
| walkingarea edge | 2,372 |
| 上述非 internal lane | 10,712 |
| pedestrian lane | 7,356 |
| bicycle lane | 3,288 |
| internal edge | 13,334 |
| internal lane | 14,911 |
| 所有 connection | 35,768 |
| 普通 junction/node（sumolib） | 1,205 |
| TLS controller | 85 |
| TLS phase 总数 | 424 |

网络含 primary、secondary、tertiary、residential、service、living_street、footway、pedestrian 等多种道路类型，足以驱动分级道路材质；不能把所有道路统一成同一灰色平面。

### 6.2 坐标定义

网络 `<location>`：

```text
netOffset      = -402358.92,-4317416.65
convBoundary   = 0.00,0.00,13746.09,17380.55
origBoundary   = 115.826838,39.000573,116.031026,39.158097
projParameter  = +proj=utm +zone=50 +ellps=WGS84 +datum=WGS84 +units=m +no_defs
```

SUMO 坐标已经是米。20 路口控制区包络：

```text
min = (3076.56, 5442.80)
max = (4306.74, 7588.83)
size = 1230.18 m × 2146.03 m
center = (3691.65, 6515.815)
```

本轮用 sumolib 对 20 个注册点执行 `XY → lon/lat → XY`：

- 最大往返误差：`1.53e-9 m`；
- 注册表经纬度与网络转换的近似最大差异：`0.0 m`；
- 20 个 junction ID 全部存在；
- 20 个相同 ID 的 TLS controller 全部存在。

这证明当前网络坐标源可用于统一 `CoordinateService`。当前仓库尚无该服务，K06 资产也没有通过统一服务定位。

### 6.3 20 路口清单

20 个受控点组成 20 条直接邻接边的连通控制图，平均相邻道路距离 164.47 m，最大 294.42 m。TLS ID 与 SUMO junction ID 相同。

| 显示 ID | SUMO junction/TLS ID | 角色 | 官方锚点 | SUMO XY (m) | 受控横道 link |
|---|---|---|---|---:|---:|
| B01 | `cluster_10739806290_13007678851_13007678852_9999059766` | controlled | demo_18 | 3912.01, 7588.83 | 0 |
| B02 | `cluster_10739806289_9999059765` | controlled | 无 | 3721.86, 7525.14 | 1 |
| B03 | `cluster_10739806288_8515847056` | controlled | 无 | 3563.03, 7472.33 | 1 |
| B04 | `cluster_10739806287_9999059763` | controlled | 无 | 3526.91, 7460.47 | 1 |
| B05 | `cluster_10739806286_9999059759` | controlled | 无 | 3301.19, 7370.88 | 1 |
| B06 | `cluster_10739806284_10739806285_9999059760` | controlled | demo_20 | 3076.56, 7275.64 | 0 |
| B07 | `cluster_13011794592_7341134038_8515847048` | controlled | 无 | 3153.39, 7075.21 | 0 |
| B08 | `cluster_11204209179_11508862625_11508862626_9215428070` | controlled | 无 | 3236.59, 6856.76 | 0 |
| B09 | `cluster_11204209180_9245378846` | controlled | demo_17 | 3335.17, 6606.42 | 0 |
| B10 | `cluster_11204236168_9245378909` | controlled | 无 | 3402.83, 6430.36 | 0 |
| B11 | `13013166299` | controlled | 无 | 3441.62, 6342.36 | 0 |
| B12 | `cluster_11204226724_9245378838` | controlled | 无 | 3469.28, 6256.33 | 0 |
| K01 | `cluster_7341134071_9197849970_9245379727_9245379728` | core_corridor | 无 | 3521.46, 6113.69 | 0 |
| K02 | `cluster_9245378841_9245379729` | core_corridor | 无 | 3728.30, 6194.33 | 1 |
| K03 | `13007678875` | core_corridor | 无 | 3772.09, 6079.60 | 4 |
| K04 | `9245560423` | core_corridor | 无 | 3883.29, 5791.51 | 4 |
| K05 | `cluster_8515870116_8519484674` | core_corridor | demo_19 | 3941.28, 5636.27 | 1 |
| K06 | `11122023451` | core_corridor | demo_14 | 4005.52, 5451.76 | 3 |
| K07 | `11122023463` | core_corridor | 无 | 4162.35, 5448.06 | 4 |
| K08 | `cluster_11122023464_11122023574` | core_corridor | demo_15 | 4306.74, 5442.80 | 1 |

核心走廊注册顺序是 K01 → K02 → K03 → K04 → K05 → K06 → K07 → K08。11/20 个控制点具备受控横道证据，其余路口不能为视觉完整性伪造“受 SUMO 控制的横道”；可以显示有来源的普通步行设施或明确标注的工程环境设施。

## 7. 需求、车辆类型、行人和非机动车

### 7.1 机动车

基础 `routes.rou.xml` 包含 983 辆车：

| vType | 数量 | SUMO vClass |
|---|---:|---|
| connected_vehicle | 477 | passenger |
| passenger | 278 | passenger |
| non_connected_vehicle | 43 | passenger |
| bus | 43 | bus |
| truck | 40 | truck |
| ride_hailing | 39 | passenger |
| taxi | 31 | taxi |
| delivery_vehicle | 30 | delivery |
| emergency | 2 | emergency |

用户要求的 SUV 当前没有独立 SUMO vType，不能在逻辑层声称存在；可以把 passenger 的视觉模型做确定性外观变体，但不得新增一个虚构交通类型。

S01—S07 的静态机动车数量分别为 737、1,573、983、1,180、1,180、983、983。所有 route 文件引用的 edge 和 vType 均通过本轮只读校验。

### 7.2 非机动车与行人

`multimodal.rou.xml` 同时包含：

- bicycle：160；
- electric_bicycle：210；
- pedestrian：287，其中 adult 263、elderly 24。

这些对象来自 SUMO，不应由前端另行随机生成。当前 3D 尚未渲染它们。

### 7.3 OD 和扰动

主场景有三段机动车 OD，核心验证路线要求至少连续经过 5 个受控路口，背景 OD 允许使用完整网络。S01—S07 对应：

- S01 平峰；
- S02 高峰；
- S03 大型活动散场；
- S04 施工占道；
- S05 事故；
- S06 应急车辆；
- S07 通信异常。

配置里的 `roadwork` 目标目前是语义字符串 `configured_downstream_lane`，没有显式 `lane_id`。运行时在 `ExperimentRunner._roadwork_lane()` 中对受控 lane ID 排序后取中位 lane 作为 fallback。事件日志会记录实际关闭 lane，因此 3D 可以从运行事件映射到真实 lane；但场景配置本身还不能保证“预定施工点就是指定道路”，这是必须修正的真实性缺口。

## 8. TraCI、算法、指标和事件链

### 8.1 可直接复用的 TraCI 能力

`src/traffic_platform/sumo_adapter/adapter.py` 已提供：

- TraCI 与 libsumo 两种 backend；
- 生命周期、暂停、恢复、步进、唯一端口和退出清理；
- 所有活动机动车/自行车的位置、角度、速度、加速度、lane、edge、route 和等待时间；
- 所有 SUMO person 的位置、速度、lane、crossing、waiting area 和 stage；
- TLS phase index、完整 RYG state、phase duration、next switch、controlled lanes/links；
- lane aggregate；
- 施工 lane 关闭/恢复、事故停车/清除、运行时车辆注入、速度引导。

这意味着 P0 实体真值不需要重写 SUMO，也不需要 Three.js 直接连接 TraCI。正确路径是由后端把 adapter 已采集的数据转换成专用 3D 增量协议。

### 8.2 控制链

现有控制链为：

`SUMO → RSU → Edge → Cloud → Edge → Safety Kernel → TraCI/vehicle guidance`

内置算法：

- B0 `fixed-time`；
- B1 `actuated-control`；
- B2 `max-pressure`；
- B3 `coordinated-max-pressure`；
- B4 仅为诚实占位，未实现模型推理。

控制、故障和指标通过 Pydantic 契约、MQTT/仿真总线和实验引擎连接。云端不直接切换信号灯，3D 也不得绕过这条链。

### 8.3 当前聚合与行人相位缺口

`EdgeStateAggregator` 每个 SUMO 步长采集 20 个路口和受控 lane。它把完整 vehicle snapshots 暂存在 `last_vehicle_states`，但当前 API snapshot 没有输出这些实体。

`build_topology()` 仍包含“机动车网络不含 walking edges”的旧注释，并把所有 `pedestrian_phase_ids` 设为空。当前正式网络已经是多主体网络且 11 个路口存在受控横道，因此该映射与现网事实不一致。它不会删除 SUMO 的行人信号，但会让安全/控制拓扑和未来 3D 行人信号映射缺少显式 phase 语义，必须在不改变既有 SUMO 逻辑的前提下修复并测试。

### 8.4 指标与历史真实运行

指标覆盖速度、排队、吞吐、等待、能耗、通信、故障降级、非机动车、行人和冲突代理指标。现有最近的 1800 s 真实结果 `results/exp-5762c0f4f3b4/result.json` 包含：

- 1,800 个指标采样；
- 2,506 个事件；
- `actual_run=true`；
- Python 进程平均 CPU 59.45%；
- Python 进程峰值内存 177.57 MiB；
- `simulation_realtime_factor=0.2754`。

该结果说明当前完整运行链在当时环境下没有达到 1× 实时推进，不能据此承诺 LIVE 模式实时性。它也不是 3D FPS 结果。后续需分别 benchmark：纯 SUMO/TraCI、后端实体编码、WebSocket、浏览器渲染。

## 9. FastAPI、WebSocket、存储和 Replay 审计

### 9.1 现有 REST

现有 API 已覆盖：

- health/readiness/system status；
- 场景列表、校验和生成；
- 实验创建、开始、暂停、恢复、停止、指标、事件、报告；
- 算法列表、校验和激活；
- 故障注入/清除；
- 路口清单、状态和 300 点内存历史。

这些管理面应复用。当前尚无天气、昼夜、相机、分析层、Replay seek/playback 或 3D scene metadata API。

### 9.2 现有 WebSocket

`/ws/v1/realtime` 当前每 1 秒重复发送一份 `state.realtime` 全量聚合快照。快照包含：

- 实验/场景/算法/仿真时间；
- 20 个路口的 phase、phase state、lane aggregate、拥堵、排队；
- 指标、故障、控制模式和事件。

当前不包含：

- vehicle spawn/update/remove；
- bicycle spawn/update/remove；
- pedestrian spawn/update/remove；
- 完整 TLS link/head 映射；
- 静态 scene metadata；
- frame sequence、base snapshot ID、delta recovery；
- 二进制或压缩协议。

`SamplingConfig.dashboard_hz`、`intersection_hz`、`control_hz` 当前只有模型字段，运行时只实际使用了 `vehicle_trajectory_hz`。WebSocket 的 1 Hz 在 API 中写死。后续必须显式实现专用 3D snapshot + delta 流，并用 benchmark 决定 JSON 是否足够。

### 9.3 存储与 Replay

现有 TimescaleDB 保存 metrics、events 和 `vehicle_trajectory_batches`。轨迹批次默认 0.2 Hz，包含机动车、自行车和行人，但：

- `result.json` 只内嵌每秒聚合指标，不内嵌实体轨迹；
- 结果目录没有可独立携带的 Replay 帧文件；
- 没有 Replay API、索引、暂停/seek/倍率或前端 ReplayManager；
- 0.2 Hz 原始轨迹不足以直接作为高质量 30 FPS 回放端点，需按真实数据生成可插值的专用回放包。

LIVE 和 REPLAY 应共享同一个前端 frame consumer；不能复制两套渲染器。

## 10. 当前前端和 Three.js 审计

### 10.1 前端栈

当前前端是 React 19 + TypeScript + Vite 8，不应改成 Vue。ECharts 已用于指标曲线，Three.js 0.185.1 使用 `WebGLRenderer`。

现有驾驶舱能真实消费聚合 WebSocket 数据，具有实验控制、路口拓扑、路口检查器、指标曲线和事件时间线。页面历史长度限制为 180，避免了图表无限增长。

### 10.2 K06 三维样板

文件：

- `assets/3d/k06/k06-hero.blend`；
- `apps/web-dashboard/public/assets/k06/k06-hero.glb`；
- `apps/web-dashboard/public/assets/k06/k06-vehicle.glb`；
- `tools/visualization/build_k06_scene.py`；
- `apps/web-dashboard/src/components/IntersectionScene.tsx`。

资产检查：

| 资产 | 大小 | nodes | meshes | materials | 估算三角形 | 纹理/压缩 |
|---|---:|---:|---:|---:|---:|---|
| `k06-hero.glb` | 2,205,708 B | 31 | 28 | 28 | 28,452 | 3 张 PNG；无 Draco/KTX2 |
| `k06-vehicle.glb` | 183,756 B | 7 | 7 | 7 | 2,044 | 无纹理；无 Draco |

优点：

- Blender 主文件可编辑；
- 资产为仓库脚本原创，没有未核验商业模型；
- 使用 InstancedMesh 渲染 24 辆样板车；
- 有 ACES tone mapping、环境反射、方向光、阴影、相机切换和资源 dispose；
- pixel ratio 上限为 1.5，没有无界放大。

真实性缺口：

- `build_k06_scene.py` 的 `MAIN_CENTERLINE`/`EAST_CENTERLINE` 是手写常量，不是从 lane shape 自动生成；
- `IntersectionScene.tsx` 的 6 条 route definition 是手写曲线；
- 24 辆车的数量、速度、位置和颜色来自前端确定性样板，不来自 SUMO ID；
- 3D 信号按 `Math.floor(timeBase / 12)` 交替，没有使用 `realtime.phase_state`；
- 点击车辆显示的是 `XA-001` 类 preview ID，不是 SUMO vehicle ID；
- 没有行人、非机动车、完整 TLS head、施工设施或事件空间映射；
- 没有 LOD、对象池生命周期、Draco、KTX2、资产 manifest、GPU 预算和性能监测；
- 只有 K06，没有完整 20 路口。

因此当前 K06 只能作为“视觉样板/hero 资产参考”，不能作为已完成数字孪生的证据。

## 11. 建筑、绿化和环境数据可用性

源 OSM 包含 13,217 nodes、1,172 ways，其中：

- building ways：116；
- residential landuse：140；
- construction landuse：28；
- commercial landuse：18；
- school：16；
- park：20；
- water：20。

这些数据足以提供部分建筑/功能区证据，但 116 个建筑 footprint 不能覆盖整个 20 路口视觉区域。后续建筑必须分成：

1. OSM 有 footprint/tag 的可追溯建筑；
2. 根据地块和功能区生成的工程环境建筑；
3. 核心路口原创 hero 建筑。

第 2/3 类必须明确标记 `modeled` 或 `authored_context`，不得描述成雄安真实建筑复刻。

## 12. 当前自动验证结果

本轮当前工作树验证：

| 验证 | 命令 | 结果 |
|---|---|---|
| Python unit | `.\.venv\Scripts\python.exe -m pytest tests\unit -q` | 77/77 通过 |
| Ruff | `.\.venv\Scripts\python.exe -m ruff check src tests` | 通过 |
| Mypy | `.\.venv\Scripts\python.exe -m mypy src` | 83 个源文件通过 |
| Vitest | `npm run test` | 1/1 通过 |
| 前端生产构建 | `npm run build` | 通过；Three 和 ECharts chunk 超过 500 kB 警告 |
| SUMO 结构/ID | sumolib 只读校验脚本 | 20 junction/TLS、所有 route edge/type 通过 |
| 坐标往返 | sumolib `XY↔lon/lat` | 最大误差 `1.53e-9 m` |

本轮没有重跑 integration/e2e/chaos/performance、真实 MQTT、Docker 镜像重建或完整 SUMO 实验。历史验收报告中的通过项仍是历史证据，不能写成当前源镜像已重新验证。

## 13. 问题清单与优先级

### 13.1 P0：进入真实 3D 同步前必须解决

| ID | 问题 | 影响 | 决策 |
|---|---|---|---|
| P0-01 | 无统一 `scene.json` | Three.js 只能自行查 XML 或手写几何 | Phase 1 建立可追溯中间格式 |
| P0-02 | 无 `CoordinateService` | 模块容易各自写翻转/偏移魔法数 | 单一米制双向转换 + 测试 |
| P0-03 | WebSocket 无实体增量帧 | 车辆/人/自行车无法真实同步 | 新增 scene init + delta frame |
| P0-04 | 当前 3D 车流和灯色是 preview | 会造成“动画冒充仿真”风险 | 在真实流接通前保留 preview 标签，不对外宣称完成 |
| P0-05 | 只有 K06 手写局部几何 | 不能证明 20 路口拓扑一致 | 从 SUMO lane/junction shape 自动生成 |
| P0-06 | 无 TLS physical head/link 映射 | 无法把 RYG 字符串放到正确灯头 | 生成并验证 `traffic_light_mapping.json` |
| P0-07 | `pedestrian_phase_ids` 被全部置空 | 多主体安全/显示语义与现网不一致 | 从受控 crossing links 推导并测试 |
| P0-08 | 施工配置未绑定显式 lane | 预定事件与空间展示可能语义漂移 | 配置/生成期解析实际 lane，事件继续回传实际 ID |
| P0-09 | dashboard sampling 配置未生效 | 协议频率不可控 | 统一调度，不改变 SUMO 1 s 实验步长 |
| P0-10 | 历史长跑实时因子仅 0.275 | LIVE 可能无法 1× 推进 | 分层 benchmark 后决定 TraCI/libsumo/编码频率 |

### 13.2 P1/P2：性能与产品完整性问题

| ID | 问题 | 当前状态 |
|---|---|---|
| P1-01 | 无车辆/行人/建筑/设施 LOD | 未实现 |
| P1-02 | 无通用对象池和实体插值器 | 未实现；仅 24 车 InstancedMesh 样板 |
| P1-03 | 无 Draco/KTX2/资产 manifest | K06 GLB 为 PNG + 未压缩几何 |
| P1-04 | 无 Texture/GPU/Shadow budget manager | 未实现 |
| P1-05 | 无天气、夜间和分析层 | 未实现 |
| P1-06 | 无浏览器 FPS/Draw Call/显存/内存报告 | 未测 |
| P1-07 | 无 Replay 文件协议和播放器 | 仅有 DB 0.2 Hz 轨迹批次 |
| P1-08 | 无固定镜头截图验收 | 未实现 |
| P1-09 | 无 3D 一键启动/停止脚本 | 只有通用 `task.ps1` |
| P1-10 | 无 Git 基线 | 无 HEAD，全部 untracked |

## 14. 可复用、需适配与新建矩阵

### 14.1 直接复用

- `rongdong.multimodal.net.xml` 的 lane/junction/connection/crossing/TLS geometry；
- `controlled_intersections.json` 的稳定 20 点 ID 和核心走廊；
- `vtypes.add.xml` 和全部真实 route/person demand；
- `TraciSumoAdapter` 的车辆、行人、信号和事件操作；
- 现有实验生命周期、算法切换、故障、指标、TimescaleDB；
- React/Vite/ECharts 驾驶舱和 REST 管理面；
- K06 Blender 原创资产的材质、视觉方向和面数参考。

### 14.2 适配后复用

- `EdgeStateAggregator.last_vehicle_states`：改由专用 3D telemetry publisher 消费；
- `/ws/v1/realtime`：保留聚合驾驶舱流，新增或版本化实体 delta 流；
- trajectory batch：扩展为可导出的真实 Replay 包；
- K06 GLB：作为局部 hero overlay，而不是道路真值；
- 现有事件日志：补充稳定 event payload 和空间对象 ID。

### 14.3 必须新建

- 统一 scene schema、生成器和 manifest；
- `CoordinateService`；
- 自动道路/lane/junction/crossing/marking builders；
- TLS head/link mapping；
- vehicle/bicycle/pedestrian managers、对象池和插值；
- 资产、材质、纹理、LOD、阴影和质量预算；
- LIVE/REPLAY 共用 frame consumer；
- 3D 性能采集、固定镜头验收和一键启动脚本。

## 15. Phase 1 进入条件与实施约束

Phase 1 只做统一场景中间格式，不提前制作天气、动画或假车流。具体门禁：

1. 输入固定为 `rongdong.multimodal.net.xml`、`controlled_intersections.json`、additional 和 OSM 功能区；
2. 输出建议为 `generated/scenes/xiongan_rongdong_20.scene.json`，不写入主办方目录；
3. scene metadata 必须记录所有源文件 SHA-256、网络 projection、netOffset 和生成器版本；
4. 所有 junction/edge/lane/TLS ID 原样保留并提供正反索引；
5. 先覆盖 20 路口控制区及其连接道路，外围按明确空间裁剪规则进入 LOD，不把拓扑改成棋盘；
6. buildings/vegetation/device 的 `provenance` 必填；
7. scene schema 和生成器必须有自动测试；
8. 生成完成后先做计数、ID、坐标和连通性验收，再进入 Three.js 道路渲染。

## 16. Phase 0 最终判断

Phase 0 已完成当前工程审计。没有需要用户立即决定的重大歧义：

- 正式 3D 场景确定为 `xiongan_rongdong_20`；
- 前端继续 React/Vite/Three.js/WebGLRenderer；
- SUMO 1 s 步长保持不变；
- `official_20_independent` 继续只读；
- K06 保留为视觉资产参考，但真实道路和交通必须由 SUMO 数据替换；
- 下一步按既定顺序进入 Phase 1：scene JSON 生成与统一坐标服务。

Phase 0 不能被表述为“3D 系统完成”，也不能用当前 K06 preview 截图作为 SUMO 实体同步证明。
