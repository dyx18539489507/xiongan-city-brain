# 城市大脑三维分析模式

## 实时拥堵与排队

Phase 10 新增 `apps/web-dashboard/src/3d/analytics/AnalyticsLayerManager.ts`。分析层不生成随机热力数据，而是按每个 WebSocket 实体快照聚合真实 `VehicleEntity`：

- lane ID：决定光带落在哪条 SUMO lane；
- speed：计算 lane 平均速度；
- status / speed < 0.5 m/s：计算排队车辆；
- lane shape：决定三维光带几何；
- lane 末端：决定排队柱的位置。

颜色分级是当前可解释的展示规则，不是交通行业定标结论：

- 平均速度小于 2 m/s 或等待车辆不少于 3：严重，红色；
- 平均速度小于 5 m/s 或存在等待车辆：拥堵，橙色；
- 平均速度小于 8 m/s：缓行，黄色；
- 其他有车 lane：畅通，绿色。

只为当前有真实车辆的 lane 提交动态顶点。每个 lane 使用三条窄并行光带增强区域鸟瞰辨识度，但仍共享一个 BufferGeometry 和一个材质 draw call。排队柱使用固定 240 容量的 InstancedMesh。

完成态 `exp-9903c2e0b908` 验收快照得到 44 条 active lane、17 条 severe lane 和 22 辆 waiting vehicle。证据：`outputs/3d/phase10/17_analysis_mode.png`。

## RSU 与摄像头

原始 OSM 范围没有可用路侧设备清单。生成器 1.2.0 因此创建了一套明确标注为工程建模的设备布局：

- 每个真实受控路口 1 个 RSU，共 20 个；
- 每个真实受控路口 1 个摄像头，共 20 个；
- 位置由该 TLS 的真实 incoming SUMO lane 末端及车道法向确定；
- 稳定 ID 为 `rsu:<SUMO junction id>` / `camera:<SUMO junction id>`；
- provenance 为 `engineering_model_from_controlled_junction_and_sumo_lane`；
- communicationStatus 为 `runtime_unbound`。

前端 `apps/web-dashboard/src/3d/roadside/RoadsideDeviceManager.ts` 使用实例化杆体、设备盒和摄像头；分析模式用一个实例化圆环批次显示建模覆盖范围，并用一个 LineSegments 批次显示设备管理关系。`BOUND 0` 明确表示尚未连接真实设备运行状态，不能把圆环宣称为实际射频覆盖测量。

设备近景证据：`outputs/3d/phase10/18_rsu_analysis.png`。

## 真实冲突与协同图层

后端 `SafetyMonitor` 每个仿真 tick 观察实际机动车、非机动车和行人，输出参与者 ID、冲突类型、SUMO 坐标、最小距离、相对速度、TTC、PET 和严重度。实时协议把这些观测作为 `conflicts` 发送；`ConflictAreaManager` 只在分析模式、且当前帧确有冲突时生成可点击六边形，不预置静态热点。

绿波层只依据核心走廊真实 lane/TLS 的 `g/G` 状态生成开放窗口；通信层按选中/代表实体聚合车辆—RSU—边缘—云关系，避免为全部车辆绘制连线。设备在线/通信状态来自系统快照，覆盖圆环仍是工程布局，不代表现场 RF 测量。

## 尚未关闭的边界

- RSU 状态已能绑定系统级在线/通信快照，但真实丢包、时延尚未按物理 device ID 接入，不能宣称现场链路遥测；
- 绿波与 V2X 聚合层已经实现；完整 OD 历史路径、经过交通标定的建议速度和现场相位到达标定仍未实现；
- 当前分析阈值需要在最终比赛指标口径确定后配置化；
- 自动化浏览器长等待会被降频，本阶段截图中的低 FPS 不能作为 GPU 性能结论。
