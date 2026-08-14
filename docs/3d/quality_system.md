# 自适应质量与性能保护

Phase 11 新增 `apps/web-dashboard/src/3d/performance/QualityManager.ts`，与已有 `PerformanceMonitor` 配合。

质量档位只控制渲染缓冲分辨率：

- native：renderScale 1.00；
- balanced：renderScale 0.88；
- performance：renderScale 0.75；
- 最终 pixelRatio 始终不超过 1.25。

只有机/非/人动态实体总数达到 180 时，平均 FPS < 24.5、P1 < 8 或最大帧时 > 300 ms 才记为慢窗口；连续 4 个慢窗口下降一级。低负载下达到当前档位 90% 目标、P1 > 5 且最大帧时 < 250 ms 才记为快窗口；连续 12 个快窗口恢复一级。中间区间重置计数，避免质量来回抖动。页面从后台恢复后不补交渲染帧；native/balanced/performance 的渲染上限分别为 30/24/20 FPS。

该策略不改变 SUMO 步长，不删除 20 路口、行人或非机动车，也不关闭真实数据层。车辆、行人和自行车已有距离 LOD；树木、路灯、RSU、摄像头、施工设施与排队柱采用 InstancedMesh；历史事件与性能窗口均有限长。

单元测试：`apps/web-dashboard/src/3d/performance/QualityManager.test.ts`。

Phase 11 已完成目标 MX250 上 S01–S05×晴/夜/雨×全域/走廊/路口 45 组合矩阵、30 分钟 JS Heap/进程 CPU 内存长稳、实际 ETC1S KTX2 流水线和动态对象实例化。当前冻结代码矩阵平均 15.27 FPS、中位 15.0，最差组合 8.1、最低 P1 1.1，未达到稳定 25–30 FPS。浏览器不能可靠读取独显显存，Three 731.74 kB 与 ECharts 511.34 kB 构建分块告警也仍保留；不能把“Phase 11 有完整报告”误写成“性能目标已达标”。
