# Web 3D 性能实测报告

## 最终代码的正式 MX250 矩阵

- 合并报告：`outputs/3d/benchmarks/matrix-final-mx250-20260810.json`
- 原始来源：`matrix-20260809T225736Z.json`（S01–S02）、`matrix-20260809T230322Z.json`（S03–S04）和 `matrix-20260809T230827Z.json`（S05）
- 合并器：`tools/benchmark/merge_3d_matrix.mjs`；校验相同 MX250 renderer、无重复 profile、每 profile 恰好 9 个天气/镜头组合、0 page errors
- renderer：`ANGLE (NVIDIA, NVIDIA GeForce MX250, Direct3D11)`
- 视口：1280×720，devicePixelRatio 1
- 场景：`xiongan_rongdong_20`
- 工况：S01、S02、S03、S04、S05
- 环境：晴、夜、雨
- 镜头：全域、核心走廊、选中路口
- 组合：45/45；全部 `concurrentWithSumo=true`；page errors 0
- 采样：每次切换天气/镜头先重置 240 帧环形窗口，等待至少 20 个新帧，再采 3 个 1 秒样本

| 工况 | 9 组合平均 FPS | 最低组合平均 FPS | 最低 P1 FPS | 采样中最大机动车/非机动车/行人 |
|---|---:|---:|---:|---:|
| S01 | 18.80 | 12.8 | 2.2 | 27 / 18 / 8 |
| S02 | 12.20 | 8.1 | 1.1 | 65 / 20 / 9 |
| S03 | 15.02 | 10.6 | 2.5 | 37 / 18 / 8 |
| S04 | 13.96 | 8.1 | 1.9 | 42 / 18 / 8 |
| S05 | 16.37 | 13.2 | 2.1 | 46 / 19 / 9 |

全部 45 组合：平均 15.27 FPS，中位 15.0，最低组合平均 8.1，最高 23.4；最低 P1 1.1，最大 frame time 899.7 ms，最大 43 draw calls、196,653 triangles、153.4 MB JS Heap。全部组合保持 `native`、与 SUMO 并发，page errors 0。

结论：当前冻结 checkout 明显没有达到 25–30 FPS。矩阵在连续两轮长稳、多轮构建/测试和性能复测之后采集，机器热状态与 CPU/系统调度会造成波动，但不能据此丢弃较差结果。Draw Calls/三角形预算仍受控；矩阵同时启用了实际 KTX2、真实冲突、K06 Blender 建筑、TLS 方向/人/非机符号和近景低骨骼人物，没有为提高分数关闭验收能力。

## 为什么保留旧矩阵与失败矩阵

- `matrix-20260809T035302Z.json`：首次前台 45 组合，实际 renderer 是 Intel UHD 620；同时发现性能环形窗口跨工况污染。组合/并发证据有效，FPS 不进入正式表。
- `matrix-20260809T040325Z.json`：Windows 高性能 GPU 偏好后的单组合探针；确认 MX250，S01/晴/全域为 27.1 FPS。
- `matrix-20260808T081905Z.json`：headless SwiftShader，只验证工具链，禁止当作 GPU 数据。
- `matrix-20260809T075159Z.json`：质量门槛过度降级，完成 S01/S02 后超时；不能作为最终性能。
- `matrix-20260809T080225Z.json`：45/45 完成但所有组合被错误锁在 `performance`，用于发现策略自限，不作为最终性能。
- `matrix-20260809T081440Z.json`：最终策略下完成 S01–S04，启动 S05 后等待超时；其 36 项与独立 S05 报告通过合并器形成最终矩阵。
- `matrix-20260809T081440Z.json` + `matrix-20260809T082232Z.json` 曾合并得到平均 24.49 FPS；该结果保留为优化过程证据，不再作为当前 checkout 最终值。
- `matrix-20260809T105748Z.json` + `matrix-20260809T110757Z.json` 是机非人远景实例化后的中间复测，平均 14.64 FPS，仅保留为机器热状态/过程证据。
- `matrix-20260809T141730Z.json` + `matrix-20260809T142106Z.json` + `matrix-20260809T142503Z.json` 是冲突、实际 KTX2、K06 hero 与动态实例化共同存在时的阶段代码来源；合并器把报告和截图路径归一化为仓库相对路径。
- 上述三份报告曾合并得到 22.66 FPS；加入 TLS 专用灯面和近景低骨骼人物后，它们降级为过程证据。
- `matrix-20260809T225736Z.json` + `matrix-20260809T230322Z.json` + `matrix-20260809T230827Z.json` 是最终冻结代码来源，合并为 `matrix-final-mx250-20260810.json`，即使数值较低也作为正式最终证据。

## 长时稳定性

当前冻结代码正式报告：`outputs/3d/benchmarks/stability-20260809T231157Z.json`。

| 项目 | 结果 |
|---|---:|
| renderer | NVIDIA GeForce MX250 |
| 采样窗 | 1811.2 s（脚本总墙钟约 31.5 min） |
| 原始样本 | 84（20 s 间隔） |
| 仿真时间 | 0 → 663 s |
| page errors | 0 |
| sampling timeout | 0（连续 3×10 s 才判持续卡死） |
| 最大机动车/非机动车/行人 | 379 / 128 / 51 |
| JS Heap 首/尾/峰值 | 62.7 / 132.5 / 159.8 MB |
| Heap 全程线性斜率 | +0.39 MB/min |
| 后端内存峰值 | 155.07 MB |
| 后端平均 CPU | 60.32% |
| 平均/最低窗口 FPS | 19.31 / 16.3 |
| 最低 P1 / 最大 frame time | 2.5 / 951.1 ms |
| 最大 Draw Calls | 29 |
| 真实 Replay | 672 帧 / 48.3 MB |

实验在 1810 s 墙钟上限时仍运行，脚本随后按实验 ID 停止；采样窗达到 1811.2 s。0 page errors、0 sampling timeout，关闭了当前冻结 checkout 的完整 30 分钟墙钟缺口；但仿真只到 T+663，未完成 3600 s。Heap 斜率为正且实体量持续增长，因此只能说明该 30 分钟内没有崩溃或无界爆炸，不能证明零泄漏。高负载平均 19.31 FPS，也不能表述为高峰稳定 25–30 FPS。

两次失败长稳被保留：`stability-20260809T060957Z.json` 在约 24.5 分钟、397 辆车时采样失联；`stability-20260809T064733Z.json` 在约 14.7 分钟、270 辆车时失联。它们促成远景车辆 InstancedMesh、P1/长帧感知质量档、20 FPS 高负载 CPU 预算和禁用基准浏览器后台降频。`stability-20260809T145848Z.json` 是 TLS/骨骼补丁前的 1807.3 s 过程证据，峰值 532/177/86、0 错误；不替代当前正式报告。

高负载回放探针 `replay-probe-after-all-dynamic-instancing.json` 在 T+747、441 辆机动车的真实回放帧上为 MX250、0 page errors、23 draw calls、平均 17.89 FPS。机非人远景合批把同源长稳末端 121 draw calls 降到 23；说明极端负载可响应性改善，但仍不满足 25–30 FPS。

## GPU/显存边界

WebGL debug extension能确认实际 renderer，但浏览器没有可靠、可移植的显存占用 API；当前只报告纹理估算、draw calls、triangles、JS Heap 和系统 GPU 名称，不伪造显存利用率。

## 复现

```powershell
.\scripts\benchmark_3d.ps1 `
  -Profiles S01,S02,S03,S04,S05 `
  -Conditions clear,night,rain `
  -Views overview,corridor,junction `
  -WarmupS 2 -SampleS 3

.\scripts\benchmark_3d_stability.ps1 `
  -Profile S02 -DurationS 3600 -SampleIntervalS 20 -MaxWallS 1810
```

正式验收前必须检查报告内 `browser.webglRenderer`/`renderer.renderer`，不能仅凭机器装有 MX250 推断浏览器使用了它。
