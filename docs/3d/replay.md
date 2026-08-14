# 真实仿真回放系统

## 真实性边界

`DigitalTwinHub` 在收到 ExperimentRunner/TraCI 的实际帧时同步写入 `results/<experiment-id>/digital_twin.replay.ndjson`。回放不修改轨迹、不补造参与者，包含机动车、非机动车、行人、20 TLS、事件、全局指标和 20 路口汇总。

文件顺序是 init、delta…、终态 init。API：

```text
GET /api/v1/replays
GET /api/v1/replays/{experiment_id}
```

列表同时读取 `actual_run=true` 的 `result.json`，返回 algorithm/profile/seed/summaryMetrics；缺少真实结果时不伪造比较指标。

Replay inventory 不再在每次请求同步解析全部帧：首尾帧分别读取，真实 `frameCount` 按 NDJSON 文件 size/mtime 缓存；并发列表请求由异步锁和 2 秒短缓存合并。文件变化后签名失效并重新统计，不以估算值冒充真实帧数。该修复把当前数据集的冷启动 scene probe 从 35.25 秒降至 20.18 秒。

## 前端播放

`ReplayManager` 复用实时协议 parser/reducer 和同一个 `IntersectionScene` Renderer，支持：LIVE/REPLAY、加载、播放、暂停、单步、0.5/1/2/4/8×、时间轴 seek。进入 REPLAY 时停止实时 WebSocket 和会修改后端的控制按钮，返回 LIVE 后重新连接并从 init 恢复。

相机、车辆池、TLS、行人/非机动车、天气、分析层和事件管理器不复制第二套场景。初始化帧的 `activeEvents` 可恢复 seek 时正在进行的施工/事故/活动；旧 replay 缺字段时按空集合兼容。

## 流式与内存上限

`ReplayManager.load()` 使用 `response.body.getReader()` + `TextDecoder` 增量解码 NDJSON，不再调用一次性 `response.text()`。硬限制：

- 文件 100 MB；
- 最多 120,000 帧；
- 必须以 init 开始；
- 逐行拒绝损坏 JSON、协议错误和 sequence 错误；
- 指标图使用 180 点环形窗口；
- unload 后释放帧、状态和旧 WebSocket。

这避免了完整文本副本和解析对象同时常驻的额外峰值。超过 100 MB 的长期实验应采用分段/索引协议，不应直接放宽上限。

## 真实对比

页面允许选择两份 `actual_run=true` replay 作为 Baseline/Candidate，显示相同真实 result 指标及有利方向；3D 画布顺序切换，避免 MX250 同时渲染双场景。没有配对 seed/算法证据时不写“提升”。

## 已知限制

- replay 保存路口级指标，不保存每条 lane 的完整历史指标；
- DemoDirector 的 60 秒 smoke 可用于 replay，但正式 6 分钟比赛脚本尚未绑定两组同 seed 实验；
- 当前冻结 checkout 的长稳报告 `stability-20260809T231157Z.json` 覆盖 1811.2 秒采样窗并产生 48.3 MB、672 帧真实回放；仿真只到 T+663 左右，因此仍不是完整 3600 s 仿真回放验收。

## 测试

`ReplayManager` 测试覆盖流式分行、限制、seek、播放时钟和旧帧兼容；Python 契约测试覆盖列表/下载与路径隔离；Playwright 验证真实页面加载 replay。
