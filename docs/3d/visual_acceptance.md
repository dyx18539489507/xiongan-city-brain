# Web 3D 固定镜头视觉验收

## 最终发布镜头

| 编号 | 文件 | 数据/模式 | 结论 |
|---:|---|---|---|
| 01 | `outputs/3d/final/01_overview_day.png` | 20 路口全域晴天 | 完整区域与 20/20 TLS 可见 |
| 02 | `outputs/3d/final/02_core_corridor.png` | K01–K08 走廊 | 连续路口和道路耦合可见 |
| 03 | `outputs/3d/final/03_junction_closeup.png` | `exp-d5ab3145cf24` T+600 K06 | 当前冻结代码的建筑、排队、车道、标线与 TLS 可检查 |
| 04 | `outputs/3d/final/04_pedestrian_crossing.png` | `exp-d5ab3145cf24` T+600 行人 | 当前低骨骼/LOD 人物与道路空间关系可见 |
| 05 | `outputs/3d/final/05_bicycle_flow.png` | `exp-d5ab3145cf24` T+600 非机动车 | 113 个真实非机动车状态中的近景实体、专用 TLS 符号与车辆空间关系可见 |
| 06 | `outputs/3d/final/06_night.png` | 夜间 | 路灯、TLS、窗和车辆发光材质可读 |
| 07 | `outputs/3d/final/07_rain.png` | 雨天 | 湿路面、雨粒子和能见度变化可见 |
| 08 | `outputs/3d/final/08_construction.png` | 真实 lane 关闭 | 锥桶/障碍与关闭 lane 对齐 |
| 09 | `outputs/3d/final/09_event.png` | `exp-d39eab8f13b5` T+50 | 可见真实停止的 delivery 车、事故标记、lane 和 TLS |
| 10 | `outputs/3d/final/10_analysis_mode.png` | 城市大脑分析层 | 拥堵/排队/设备叠加可关闭 |
| 11 | `outputs/3d/final/11_vehicle_variants.png` | 资产验收 | 实际加载公交、卡车、配送车 GLB |

09 的真实链：T+34 接受停车计划，T+45 SUMO 实际 stopped，截图 T+50，T+84 前解除。事故对象 `od00_00004` 为 delivery，lane `916884512#1_1` 在 scene 内。它不是静态摆拍或前端预录动画。

03–05 已在最终冻结代码上用长稳真实 Replay `exp-d5ab3145cf24` 更新；该回放在 T+600 含 329 辆机动车、113 辆非机动车和 39 名行人。截图使用 headless Chromium，截图等待期 FPS 受软件渲染/调度影响，只作视觉证据，不进入 MX250 性能报告。

## 自动与人工检查

- scene 测试验证 20 TLS、lane/edge/junction/TLS ID 映射和坐标边界；
- Playwright 验证 WebGL 页面、天气/分析/导演和车辆 GLB；
- 固定截图人工检查浮空、陷地、严重 z-fighting、建筑压路、树侵入主车道和标线方向；
- 最终 09 曾因活动区圆盘遮挡、重复标识、事故选中自行车、事故在 scene bounds 外四次拒绝，修正后才替换。

## 尚不能自动证明的项目

当前没有像素级视觉回归阈值、深度缓冲读回或语义分割，因此“全部树木永不侵道”“全场无任何 z-fighting”仍需人工固定镜头与漫游复核。程序建筑较轻量，画面不应描述为真实雄安建筑或电影级资产。

## 性能解释

固定截图脚本使用 headless Chromium/软件渲染，其 FPS 只用于截图等待，不进入 MX250 性能结论。最终冻结代码的正式性能证据是 `outputs/3d/benchmarks/matrix-final-mx250-20260810.json`，来源报告及合并校验见 `docs/3d/performance_report.md`。

最终构建的当前文案/布局截图另保留在 `outputs/3d/benchmarks/matrix-20260809T105748Z-screenshots/S01_clear_overview.png`；原 01–11 固定图不覆盖，以保留阶段性事故、施工、机非人和天气证据。

KTX2、真实冲突协议和 K06 Blender 建筑层接入后的 MX250 当前矩阵截图位于 `outputs/3d/benchmarks/matrix-20260809T141730Z-screenshots/`；其中 `S01_clear_junction.png` 验证 K06 英雄建筑与 SUMO 道路共存，模型内手工道路/标线/TLS 已被过滤。截图只证明视觉加载与空间关系，不单独证明 FPS；性能数字取同批 JSON 聚合结果。
