# Web 3D 数字孪生架构

## 当前实现边界

本文随阶段更新。当前完成 Phase 14 工程闭环：统一静态场景、坐标服务、完整控制区道路、实体级 `init + delta`、车辆/非机动车/行人/TLS/冲突、城市环境、扰动、天气、分析层、自适应质量、真实实验回放、DemoDirector 与一键启停已经接入。LIVE 与 REPLAY 共用协议状态机、实体管理器和单一 Three.js WebGLRenderer。运行时已能选择现有 `BASE/S01—S07` SUMO 工况，并在请求、实时指标、结果与清单中保留工况代码。实际 Draco 车型、ETC1S KTX2 道路纹理、K06 按需 Blender 建筑、MX250 45 组合矩阵和 30 min 长稳均已有证据；剩余边界是稳定 25–30 FPS、更多独立高细节资产、现场数据/设备/RF 标定和正式成对比赛脚本。

逻辑真值划分如下：

| 层 | 唯一真值 | 当前状态 |
|---|---|---|
| 路网拓扑、车道和 TLS 定义 | `xiongan_rongdong_20` SUMO 网络 | 已接入 scene 生成器 |
| 车辆、行人、非机动车、TLS 动态状态 | SUMO/TraCI | 实体流、对象池、插值、三维模型和真实回放已接入 |
| 三维空间变换 | `CoordinateService` | Python/TypeScript 双端已实现 |
| 三维几何、材质和视觉插值 | Three.js | 道路、主体、环境、天气和分析层已实现；资产质量仍分阶段提升 |
| 控制命令 | 现有 FastAPI → 实验服务 → TraCI | 复用，不由 Three.js 自行改变交通 |

## 分层结构

```text
SUMO network/config/routes/additional
                │
                ├── Phase 1 scene generator ──> versioned scene.json
                │                                  │
                │                                  └── Three.js static scene
                │
SUMO/TraCI runtime ──> init + delta ──> shared state ──> entity managers/interpolators
          │                                  ▲                    │
          └── truthful NDJSON recorder ──> ReplayManager ─────────┘
          ▲                                                       │
          └──────────────── verified control commands ────────────┘
```

静态对象与动态对象分离：道路、车道、路口、横道、TLS 拓扑、OSM 建筑和区域进入 `scene.json`；位置、速度、信号、生成、更新和离开等运行态不写进静态文件。这样不会每个 tick 重发 20 路口全部几何。

## 已实现模块

- `src/traffic_platform/scene/models.py`：严格 Pydantic 场景契约，未知字段拒绝。
- `src/traffic_platform/scene/coordinates.py`：后端坐标、投影和角度转换。
- `src/traffic_platform/scene/generator.py`：只读解析 SUMO/OSM/注册表并生成确定性场景。
- `apps/web-dashboard/src/3d/core/CoordinateService.ts`：浏览器端等价转换。
- `apps/web-dashboard/src/3d/network/`：场景加载、道路/车道/路口/横道/标线合批生成。
- `apps/web-dashboard/src/3d/scene/MaterialManager.ts`：当前轻量道路材质共享管理。
- `src/traffic_platform/realtime/`：实体契约、增量编码和有界发布缓冲。
- `apps/web-dashboard/src/3d/network/DigitalTwinStore.ts`：严格序列状态机和有界当前实体状态。
- `apps/web-dashboard/src/3d/network/DigitalTwinSocket.ts`：断线退避与完整 init 重同步。
- `apps/web-dashboard/src/3d/vehicles/`：共享 GLB、车型映射、对象池、车辆插值和轻量车辆行为。
- `apps/web-dashboard/src/3d/bicycles/`、`pedestrians/`、`trafficLights/`：多主体与 TLS 三维同步。
- `apps/web-dashboard/src/3d/environment/`、`analytics/`、`roadside/`：城市环境、K06 hero、天气、真实冲突/分析层与路侧设备。
- `apps/web-dashboard/src/3d/performance/`：监测与自适应渲染质量。
- `apps/web-dashboard/src/3d/replay/`：真实 NDJSON 回放、累计播放时钟和 LIVE/REPLAY 控制。
- `generated/scenes/xiongan_rongdong_20.scene.json`：静态场景生成物。

## 后续模块约束

道路生成器只消费统一场景数据，没有回到多个 XML 中分别查找坐标，也没有使用硬编码中心线。主画布原先的 24 辆预览车和 12 秒假信号周期已经移除。实体协议采用“初始化快照 + 增量帧”，回放逐行原样记录同一协议；短样本下 JSON 尚未形成瓶颈，是否切换二进制协议仍须由高峰 benchmark 决定。原 K06 GLB 只作为资产和画面参考保留，不再作为主画布的逻辑真值。

为了适配 MX250 2GB，架构默认单 Three.js 画布、30 FPS 视觉目标、浮动原点、按场景加载、对象池、实例化、LOD、自适应 render scale 和显式资源释放。正式配置保持 1 s SUMO 步长和 1 Hz 实体推送，通过插值提高视觉帧率；约 10 Hz 仅是经过后端和浏览器 benchmark 后可调整的目标。回放不会创建第二个 Renderer。Cesium 如后续引入，只能是与 Three.js 不同时常驻的独立城市态势视图。
