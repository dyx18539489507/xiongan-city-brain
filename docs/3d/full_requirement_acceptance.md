# Web 3D 原始 70 节逐项验收矩阵

更新时间：2026-08-10。验收对象是当前工作区真实文件、`xiongan_rongdong_20` 真实 SUMO 运行、WebSocket 实体帧和 Three.js 页面。`official_20_independent` 未修改。

当前计数：63 节通过、3 节部分通过（第 1/22/70 节）、1 节可选未启用（第 41 节）、3 个原文跳号（第 42/43/45 节），合计逐项覆盖 70/70。部分通过项不被包装为完成。

## 判定口径

- **通过**：已有可定位实现，并至少有静态测试、自动测试、真实运行、截图或性能报告中的一种运行证据；
- **部分通过**：主链已实现，但原文中的某个明确细项仍缺少实现或充分运行证据；
- **可选未启用**：原文明确为可选，不阻塞 WebGL 正式版本；
- **原文无此编号**：用户原文跳号，不补造需求；
- 任何 OSM、程序化建筑、RSU/摄像头工程布设都不是现场测绘或真实设备台账；任何算法对比都不推断收益。

## 逐节结论

| 节 | 原始要求核验 | 状态 | 当前证据与边界 |
|---:|---|---|---|
| 1 | i7-8565U、8 GB、MX250 2 GB、720p 25–30 FPS、禁用 UE/CARLA/光追 | 部分通过（性能边界） | `matrix-final-mx250-20260810.json`：MX250、45/45 组合与 SUMO 并发、平均 15.27 FPS、中位 15.0、最差组合平均 8.1、最低 P1 1.1；没有安装 UE/CARLA。硬件与禁用项满足，但当前冻结代码未达到 25–30 FPS。 |
| 2 | SUMO/TraCI、Python/FastAPI、WebSocket、Vite、Three.js WebGLRenderer、GLB/PBR/ECharts | 通过 | 复用仓库 FastAPI、Vite/React 和 SUMO；`apps/web-dashboard/src/3d/` 为 WebGLRenderer 主链；未重写框架。 |
| 3 | 20 路口城市空间与车辆/人/非机动车/事件/车路云状态来自真实仿真 | 通过（工程场景） | `generated/scenes/xiongan_rongdong_20.scene.json` 加真实回放；建筑和路侧设备含明确工程假设，不声称现场复刻。 |
| 4 | 仅以 `xiongan_rongdong_20` 为正式 3D 主场景，保留官方独立路口库 | 通过 | scene/API/启动脚本固定主场景；没有修改 `official_20_independent`。 |
| 5 | Phase 0 全工程审计 | 通过 | `docs/3d/current_project_audit.md` 基于实际路径、配置、ID、步长、投影和入口生成。 |
| 6 | 统一 scene 中间格式与稳定 SUMO ID 映射 | 通过 | scene JSON 含 metadata、coordinateSystem、junctions、roads、edges、lanes、connections、crossings、TLS、建筑、绿化、设备、zone、corridor、edgeRegions；SUMO ID 保留。 |
| 7 | 集中 CoordinateService、正逆转换和测试 | 通过 | `apps/web-dashboard/src/3d/core/CoordinateService.ts` 与测试覆盖坐标/角度正逆转换；道路、实体、TLS 共用。 |
| 8 | 从 SUMO lane/junction/crossing 自动生成道路与标线 | 通过 | `RoadGeometryBuilder`、`JunctionGeometryBuilder`、`RoadMarkingBuilder` 从 scene 几何生成道路面、边界、停止线、斑马线等；不逐路口手画。 |
| 9 | 道路 PBR、normal/roughness/AO、湿润和磨损变化 | 通过（轻量混合纹理） | `MaterialManager` 使用共享 MeshStandardMaterial，机动车道路 base color 实际加载 ETC1S KTX2，normal/roughness/AO 使用小型程序 DataTexture；WeatherManager 调整湿润粗糙度和暗度，无 4K 铺图。 |
| 10 | A/B/C 建筑体系、门窗屋顶材质、资料/假设边界 | 通过（工程资产边界） | 79 个 OSM footprint 形成 B/C 级程序建筑；K06 近景按需加载 Blender 原创 `k06-hero.glb` 的 `K06_Architecture_*` A 级建筑层，含立面、窗、屋顶和材质。道路/标线/TLS 节点被过滤，不覆盖 SUMO 真值；全部建筑仍是场景化假设，不是雄安实景复刻。 |
| 11 | 树、草、灌木、路灯、护栏、标牌、公交站、RSU 等实例化 | 通过（轻量资产） | `BuildingManager`、`VegetationManager`、`StreetFurnitureManager`、`RoadsideDeviceManager` 使用 InstancedMesh/共享材质；设施为工程布设。 |
| 12 | 所有车辆来自 SUMO，对象池、多车型和配置映射 | 通过 | `VehicleManager`、`VehiclePool`、`vehicle_model_mapping.json`；轿车、公交、卡车、配送车等按真实 vType/vClass 映射，退出归池。 |
| 13 | 轮转、前轮转角、加减速、转弯、灯光和 quaternion 插值 | 通过 | `VehicleInterpolator` 与车辆池驱动姿态、轮组、转向/刹车/转向灯和夜间发光；SUMO 为位置真值。 |
| 14 | 车辆三级 LOD 且阈值配置化 | 通过 | Three.LOD 与 `performance/lod_config.json`；近中远细节、灯光和阴影预算分级。 |
| 15 | 自行车/电动车、骑行者、排队/转向、车轮和轻量姿态 | 通过（轻量动画） | `BicycleManager` 仅消费 SUMO bicycle/e-bike 集合，含车轮、转向、倾斜和 LOD；不是小汽车随机动画。 |
| 16 | 行人生成/等待/过街、动画、外观和 LOD | 通过（低骨骼预算） | `PedestrianManager` 消费 SUMO person；25 m 内使用共享蒙皮几何与两骨骼肢链，25–65 m 低面模型，65 m 外 InstancedMesh；walking/waiting、衣着变化和点击状态均保留。 |
| 17 | 逐进口/方向 TLS 映射且 SUMO 为唯一真值 | 通过 | `TrafficLightManager`、`traffic_light_mapping.json`、验证测试；20/20 TLS、完整 link state、相位和剩余时间来自 SUMO。真实 `fromLane→toLane` 几何驱动左/直/右符号，`pedestrian*`/`bicycle*` lane 使用低位专用剪影；不生成假相位。 |
| 18 | 冲突区域分析：机右×人/非机、左转×对向等 | 通过 | 后端 `SafetyMonitor` 计算真实参与者、位置、最小距离、相对速度、TTC/PET 和严重度；`ConflictAreaManager` 只在存在观测冲突时于真实 SUMO 坐标生成可点击六边形，普通模式/无冲突时不显示。 |
| 19 | 真实模式与城市大脑分析模式，图层可开关 | 通过 | 页面提供 real/analysis；拥堵、排队、轨迹、绿波、设备覆盖和通信等按实际快照生成并可关闭。 |
| 20 | RSU/摄像头/边缘/控制机/VMS 及聚合通信展示 | 通过（无真实硬件遥测） | 40 个工程设备、SUMO TLS 运行绑定、状态和覆盖；通信展示聚合，`mqtt_online`/cloud 状态来自运行指标；不是现场 RF 测量。 |
| 21 | 初始化快照 + 增量 WebSocket 协议、避免全量重复 | 通过 | `DigitalTwinInit` + delta 的 spawn/update/remove/TLS/ped/bicycle/events；静态 scene 用 URL/hash 引用；activeEvents 支持重连。 |
| 22 | SUMO 步长不变、约 10 Hz 推送、Three.js 30 FPS 插值 | 部分通过 | 保持项目 1 s SUMO 步长，前端以 rAF/30 FPS 插值；当前实体真值通常 1 Hz 而非约 10 Hz，未为追求画面改变实验步长。 |
| 23 | 施工占道和 lane 精确对应 | 通过 | 真实 `ROADWORK_LANE_CLOSED/REOPENED` 驱动同 lane 锥桶、水马/障碍；`outputs/3d/final/08_construction.png`。 |
| 24 | 大型活动、集中进出和临时组织三维化 | 通过（工程 zone） | 真实 `event_dispersal` 注入与 active zone 边界；`exp-cb2caa1204ad` 实际注入 90 辆并结束；zone 为场景工程映射。 |
| 25 | 事故/故障车辆、占道、排队、事件接口，不伪造 | 通过 | `exp-d39eab8f13b5`：先 `INCIDENT_STOP_SCHEDULED`，SUMO `isStopped` 后再发布 STOPPED；delivery 车、0.007 m/s、可视 lane、随后清除；`09_event.png`。 |
| 26 | 晴/阴/黄昏/夜/雨/雾轻量天气，雨天湿路 | 通过 | `WeatherManager`、环境/雾/雨粒子/路面参数与灯光联动；无实时光追。 |
| 27 | 夜间路灯、TLS/建筑窗/车辆灯和反光感 | 通过（发光材质优先） | 夜间模式按预算开启实例路灯和 emissive，不为每车创建 SpotLight；`06_night.png`。 |
| 28 | HDRI/环境/方向光/AO/有限动态阴影与 ShadowBudget | 通过（无外部 HDRI） | `LightingManager`、PBR 环境光、方向光、512 阴影和 `ShadowBudgetManager`；远景无动态阴影。 |
| 29 | 适度后处理并 benchmark，不强制高成本效果 | 通过（轻量路线） | 使用 tone mapping、抗锯齿/像素比质量降级；未常驻 SSR/GI/DOF；没有为“可考虑”的 composer 特效牺牲 MX250。 |
| 30 | 全 20 路口保留，核心走廊和英雄路口资源分层 | 通过（资产边界） | K01–K08 核心走廊、K06 英雄近景、不同相机/LOD/阴影距离已分层；`HeroContextManager` 仅在 K06 路口近景按需加载原创 Blender 建筑层，离开后释放/恢复普通建筑。近景人物使用低骨骼蒙皮，高精扫描人物仍属美术提升项。 |
| 31 | 全域/走廊/路口/侧视/跟车/驾驶员/RSU/监控/自由/巡航/自动相机 | 通过 | 12 个页面视图、`CameraManager` 和 `camera_presets.json`；RSU/监控/驾驶员使用真实设备或实体位置。 |
| 32 | DemoDirector 比赛自动镜头时间线 | 通过（正式脚本待定稿） | 原文要求“预留”并说明实际时间以后调整；`DemoDirector` 与 60 秒真实时间线可自动执行。正式 6 分钟比赛脚本尚未绑定两组固定 seed 的 baseline/算法实验证据，列入演示内容边界而非模块缺失。 |
| 33 | 3D 核心画布和分层顶部/左右/底部 UI | 通过 | 当前 React 页面以 3D 为核心，状态、控制、指标、时间线分层；`frontend-skill` 促使采用克制的冷色交通工作站布局。 |
| 34 | 点击车/路口/道路/TLS/RSU/摄像头/事件查看真实属性 | 通过 | `InteractionManager` Raycaster 支持 Mesh/InstancedMesh、拖拽排除和实体详情面板。 |
| 35 | 车辆/建筑/树/人/设施的真正 LOD 与裁剪 | 通过 | `LODManager`、Three.LOD、距离分级、视锥裁剪和核心优先级；阈值在 JSON。 |
| 36 | 大量重复对象 InstancedMesh/共享 geometry/material | 通过 | 树、灯、TLS、RSU、摄像头、锥桶、障碍、建筑窗以及远景机动车/非机动车/行人等批量实例化；高负载同源探针 draw calls 从 121 降到 23。 |
| 37 | 纹理复用、按场景释放、预算统计和显存估算 | 通过（估算值） | `TextureManager` 去重/捕获/估算，192 MB 预算，scene dispose；浏览器无法可靠直接读 MX250 显存占用。 |
| 38 | 模型面数预算，用法线而非无限多边形 | 通过 | 资产 manifest 记录字节/三角形/LOD；当前完整矩阵最高 196,653 triangles。 |
| 39 | Draco 与 KTX2/Basis 资产优化流水线 | 通过 | Blender 4.5 实际生成 4 个带 `KHR_draco_mesh_compression` 的 optimized GLB 并用于车型映射；`encode_ktx2.ps1` 固定 KTX-Software 4.4.2/安装包 SHA，实际生成并验证 11,192 B、256×256、9 mip、ETC1S `k06_asphalt.ktx2`，`MaterialManager` 已将其用于机动车道路。 |
| 40 | 第三方资产来源、license、修改和比赛可用性 | 通过 | `docs/3d/asset_licenses.md`；当前车辆变体为工程原创/项目资产，解码器许可证随资源记录。 |
| 41 | CesiumJS 可选独立城市模式 | 可选未启用 | 正式版本只运行 Three.js，未让 Cesium 与完整场景同时常驻；当前没有 CityOverviewMode。 |
| 42 | 原文无本节 | 原文无此编号 | 不臆造验收项。 |
| 43 | 原文无本节 | 原文无此编号 | 不臆造验收项。 |
| 44 | S0/S1/S2/S4/S5 多镜头多天气真实性能报告 | 通过（目标未全达） | `matrix-final-mx250-20260810.json`：S01–S05、45 项、MX250、0 page errors、全部 native；平均 15.27、中位 15.0、最低 8.1、最高 23.4，报告完整但 25–30 FPS 目标未达到。 |
| 45 | 原文无本节 | 原文无此编号 | 不臆造验收项。 |
| 46 | 8 GB 内存约束、dispose、环形缓冲和长稳监测 | 通过（泄漏结论受限） | 当前冻结代码 `stability-20260809T231157Z.json`：MX250、1811.2 s 采样窗、峰值 379/128/51 实体、0 page errors、0 sampling timeout；Heap 62.7→132.5 MB、峰值 159.8 MB、全程斜率 +0.39 MB/min 且实体持续增长，不能证明零泄漏。 |
| 47 | 基于真实实验数据的 Replay、暂停/快进/慢放/跳转/逐帧/自动镜头 | 通过 | NDJSON 由实时 hub 录制；前端提供播放、暂停、单步、0.5–8×、seek，并复用相机导演。 |
| 48 | LIVE 与 REPLAY 共用 Renderer | 通过 | `ReplayManager` 复用协议 parser/state/IntersectionScene；切换时停止/恢复实时 WebSocket。 |
| 49 | baseline 与算法顺序/指标对比，不强制双 3D | 通过（无收益声明） | 同一画布选择真实 replay，右侧对比实际 result 指标；不伪造同步双场景，不推断算法收益。 |
| 50 | 可关闭的拥堵道路态势 | 通过 | `AnalyticsLayerManager` 用实际平均速度/排队生成道路叠加；真实模式保留原材质。 |
| 51 | 排队车辆数/长度轻量可视化 | 通过 | 路口/路段实际 queue 指标和透明带/图例展示，不以大 UI 遮挡主体。 |
| 52 | 核心走廊绿波方向/窗口/车辆到达 | 通过（不伪造建议速度） | 仅对核心走廊且 SUMO link state 为 g/G 的 lane 生成 green window；统计开放窗口；没有无来源建议速度。 |
| 53 | 车→RSU→边缘→云聚合通信展示 | 通过（逻辑通信） | 选中/代表实体与聚合线，受 analysis 可见性和池预算限制；状态来自系统通信指标，不代表现场无线链路。 |
| 54 | 开始/暂停/停止/倍率/场景/算法/seed/事件/天气/相机/图层均有后端响应 | 通过（天气/相机为前端渲染控制） | 生命周期、算法/seed、事故、施工、流量突增、活动、通信故障调用真实 API；天气/昼夜/相机/图层作用于 Renderer。 |
| 55 | 合理扩展工程目录，不破坏既有结构 | 通过 | `frontend/src/3d` 对应项目实际为 `apps/web-dashboard/src/3d`；backend 复用现有 `src/traffic_platform`；tools/generated/docs 分层。 |
| 56 | 建议核心模块且避免循环依赖 | 通过 | 原文为建议结构；Coordinate/geometry/material/assets/vehicles/peds/bikes/TLS/weather/camera/interaction/analytics/events/replay/quality/performance/demo 均有真实模块边界，没有为名称对齐额外创建空的 DigitalTwinApp/SceneManager。 |
| 57 | 分阶段加载、核心优先和真实进度 | 通过 | 页面显示 scene 下载、道路/标线/建筑/设备/池/WebSocket 初始化状态；非关键 GLB 异步加载并有占位。 |
| 58 | WebSocket/SUMO/未知类型/lane/TLS/资产失败恢复 | 通过（日志级） | 自动重连、协议 resync、占位车、未知映射告警、加载 error 状态、旧对象清理；不会因单一 GLB 失败清空场景。 |
| 59 | 坐标/解析/映射/对象池/协议/replay/质量/事件自动测试 | 通过 | Python、Vitest、Playwright、scene/asset/协议测试；最终次数见本文“最终验证”。 |
| 60 | 01–10 固定截图且无明显视觉错误 | 通过（人工固定镜头） | `outputs/3d/final/01...10` 全部存在，另有 `11_vehicle_variants.png`；09 来自真实事故回放。尚无自动像素级树侵道/z-fighting 检测。 |
| 61 | P0→P10 顺序实施 | 通过 | 审计、scene、道路、同步、车辆、TLS、城市、机非人、事件、天气、分析、视觉/性能按 phase 文档递进。 |
| 62 | Phase 0–14 每阶段测试，避免一次性巨改 | 通过（最终仍有边界） | phase 截图、测试和文档均保留；本轮发现并修正事故对象/空间/事件时序和 benchmark 窗口问题。 |
| 63 | 拓扑/交通/视觉/交互四类真实性 | 通过（资料边界） | 拓扑和交通来自 SUMO；视觉为轻量 PBR 工程场景；交互事件真实修改 SUMO。建筑和设备位置不是现场实测。 |
| 64 | 禁止 UE/CARLA/假交通/假 TLS/删路口/盗版资产/伪 benchmark 等 | 通过 | 未安装重型引擎、未改官方场景、未造假实体/指标；保留 SwiftShader、Intel、MX250、失败事故实验和较差 P1。 |
| 65 | 指定 3D 文档与 README 启动说明 | 通过 | `docs/3d/` 包含所有点名文档，本文件补充总矩阵；README 有 3D 启停和边界。 |
| 66 | 一键 start/stop、环境检查、日志和精确进程清理 | 通过 | `scripts/start_3d.ps1`、`stop_3d.ps1`，以及 benchmark/stability wrapper；使用记录 PID，不广泛杀进程。 |
| 67 | 最低验收清单 | 通过（性能目标另由第 1/70 节约束） | 清单中的联通路网、20 路口、机非人/TLS 同步、PBR、城市环境、RSU、分析、事件、昼夜天气、交互、LOD/实例/对象池、实际 KTX2、Replay、Demo 和本机运行均有实现或运行证据；性能目标不伪装达标，单列在第 1/70 节。 |
| 68 | 核心高精、外围积极 LOD、静态烘焙/动态重点 | 通过（轻量实现） | 质量、LOD、阴影、实例和纹理预算按视距与重要性执行，20 路口始终保留。 |
| 69 | 完成后按 30 项真实路径/命令/测试/问题汇报 | 通过（交付格式） | 最终对话回复和本矩阵按证据汇报，未完成项单列。 |
| 70 | 交通可信、空间可信、视觉优秀、过程可解释、结果可验证且本机可运行 | 部分通过 | 工程级数字孪生闭环和 MX250 30 分钟可运行已成立；现场级城市复刻、真实 RF/设备台账、完整 3600 s 仿真、高峰 25–30 FPS 和全部高细节资产仍未成立。 |

## 本轮关键纠错证据

1. 第一次前台矩阵实际 renderer 为 Intel UHD 620，且采样窗口跨工况污染；保留 `matrix-20260809T035302Z.json`，不作为最终 MX250 FPS。
2. 修复后 benchmark 在进程期间临时为 Playwright Chromium 选择 Windows 高性能 GPU，并在 `finally` 恢复原注册表状态；`matrix-20260809T040325Z.json` 探针确认 MX250。当前冻结代码矩阵由 `matrix-20260809T225736Z.json`（S01–S02）、`matrix-20260809T230322Z.json`（S03–S04）和 `matrix-20260809T230827Z.json`（S05）经校验合并为 `matrix-final-mx250-20260810.json`；较早结果只保留为过程证据。
3. 事故链曾错误选中 SUMO vehicle 域中的自行车，又曾选中 3D bounds 外车辆；均未删除失败证据。最终 `exp-d39eab8f13b5` 只选择当前位于核心 edge 的机动车，并以 SUMO `isStopped` 区分“计划停车”和“实际停车”。
4. 长稳脚本到墙钟上限后收尾解析失败，但原始样本完整；修复并用 `finalize_stability_report.mjs` 恢复分析，报告明确 `terminatedByWallLimit=true`。
5. 后续两次长稳分别在约 24.5 和 14.7 分钟出现采样失联；保留 `stability-20260809T060957Z.json`、`stability-20260809T064733Z.json`。继而完成远景机动车/非机动车/行人 InstancedMesh、质量档、基准浏览器后台降频和连续超时判据；最终冻结代码 `stability-20260809T231157Z.json` 取得 1811.2 秒采样窗、0 page errors、0 sampling timeout。
6. 质量策略一度让所有普通工况错误卡在 performance 档；保留 `matrix-20260809T075159Z.json` 和 `matrix-20260809T080225Z.json`，最终改为基于真实动态实体数量触发高负载降级。
7. 长稳回放增多后，首次页面会并发全盘统计 Replay 帧数，E2E 一度在 45 秒内未 ready；加入按 size/mtime 的真实帧数缓存及 2 秒 inventory 锁缓存后，冷启动 probe 从 35.25 秒降至 20.18 秒，E2E 复验 3/3 通过。
8. 当前 Docker 占用 8000/5173，原一键脚本默认端口会冲突；正式 3D 默认改为 8013/5177，并实测 `/ready` 返回 ready、前端 HTTP 200、停止后精确 PID 清理完成。
9. 当前代码高负载回放探针在 T+747、441 辆机动车时为 23 draw calls；远景机动车/非机动车/行人合批相对同源长稳末端的 121 draw calls 明显下降，但 17.89 FPS 仍不满足目标。
10. 真实冲突从后端 `SafetyMonitor` 进入 `init + delta`，前端只对实际 participant/坐标生成可点击分析六边形；无观测冲突时不显示热点，不用静态“高风险区”冒充实时状态。
11. KTX-Software 4.4.2 安装包经固定 SHA-256 校验后在仓库忽略目录中本地提取；`toktx --encode etc1s` 生成的道路 KTX2 已通过 `ktx validate`、manifest 头解析和浏览器 KTX2Loader 运行验收。
12. K06 Blender hero 只保留 `K06_Architecture_*` 建筑节点；模型内手工道路、标线和信号灯全部过滤，确保 SUMO scene 继续是拓扑和道路几何唯一真值。
13. 逐字复核发现 TLS 方向/人/非机灯面与近景骨骼人物仍有缺口；现已依据真实 lane 族和 `fromLane→toLane` 几何生成三类共享符号批次，并将行人分为 25 m 内低骨骼、25–65 m 低模、65 m 外 InstancedMesh。补丁后重跑了最终矩阵与 30 分钟长稳。

## 可复现命令

```powershell
$env:SUMO_HOME='C:\xiongan-sumo'
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy --strict src

Push-Location apps\web-dashboard
npm test
npm run build
Pop-Location

.\scripts\benchmark_3d.ps1 `
  -Profiles S01,S02,S03,S04,S05 `
  -Conditions clear,night,rain `
  -Views overview,corridor,junction

.\scripts\benchmark_3d_stability.ps1 -Profile S02 -DurationS 3600 -MaxWallS 1810
```

## 尚未关闭的硬边界

- 真实地理/现场：没有现场流量、高精测绘、建筑 BIM、设备台账或 RF 测量；
- 资产：实际 ETC1S KTX2、K06 A 级 Blender 建筑和近景低骨骼人物已接入；独立 SUV、精细电动自行车和高精人物 GLB 仍不足；
- 性能：当前冻结代码 MX250 45 组合平均 15.27、中位 15.0、最差 8.1、P1 最低 1.1；连续多轮后的机器热负载明显，未达到稳定 25–30 FPS；
- 长稳：当前冻结代码 1811.2 秒采样窗已关闭墙钟缺口，但只推进到仿真 T+663，且 +0.39 MB/min Heap 斜率在实体增长背景下不能证明零泄漏；
- 演示：60 秒自动导演可运行，正式 6 分钟脚本尚未绑定一组同 seed 的真实 baseline/算法成对结果；
- 可选 Cesium 城市模式未启用。

## 最终验证（2026-08-09）

- Python：`117 passed, 1 skipped, 1 warning`；跳过项为无 SUMO 环境时的兼容门禁，本次真实 SUMO 验收另行通过。
- Ruff：`All checks passed!`。
- mypy：`Success: no issues found in 91 source files`（`--strict`）。
- Vitest：`23 passed` 测试文件，`37 passed` 测试。
- 前端生产构建：`tsc -b && vite build` 成功；保留 Three.js 731.74 kB、ECharts 511.34 kB 的分块告警。
- Playwright：三项真实依赖端到端验收全部通过，覆盖拓扑/实体、Replay 列表与场景下载。
- 一键启停：默认 8013/5177 冷启动健康检查通过，`stop_3d.ps1` 后进程清单为 `stopped`。
- 正式 MX250 矩阵：`outputs/3d/benchmarks/matrix-final-mx250-20260810.json`，45/45 组合、0 page errors、平均 15.27 FPS、中位 15.0、最差组合平均 8.1。
- 长稳：`outputs/3d/benchmarks/stability-20260809T231157Z.json`，1811.2 s 采样窗、0 page errors、0 sampling timeout；高负载平均 19.31 FPS，`terminatedByWallLimit=true` 表示主动到时停止。
