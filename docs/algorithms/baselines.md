# 基线算法 B0–B4

| 编号 | 实现 | 区域信息 | 下游饱和保护 | 失效行为 |
|---|---|---|---|---|
| B0 | FixedTimeController | 无 | SUMO 原始固定方案 | 最终安全回退 |
| B1 | ActuatedController | 无 | 本地存在检测 | 保持当前安全相位 |
| B2 | MaxPressureController | 无 | 出口占有率进入压力并抑制放行 | 固定配时 |
| B3 | CoordinatedMaxPressureController | 云端目标、预测到达、剩余容量、动态周期与偏移 | 本地压力、云权重和绿波相位窗口共同约束 | 策略过期后退回 B2 |
| B4 | PredictiveAIControllerPlaceholder | 预留 ONNX/PyTorch | 不产生伪预测 | `MODEL_NOT_AVAILABLE` |

所有算法实现统一 `initialize/reset/observe/decide/feedback/health/close` 协议，通过注册表发现并校验配置。算法只能返回解释性决策，不能直接访问数据库、前端或 TraCI。

最大压力按“进口排队 − 出口可用容量惩罚”计算相位分数，并加入最短绿、最大绿和切换惩罚。B3 额外引入云端上游限流、下游疏散优先级、预测到达量、60—120 s 自适应周期、按走廊累计距离计算的相位偏移和策略 TTL；命中绿波窗口时输出原因码 `GREEN_WAVE_PHASE_ALIGNMENT`。边缘始终拥有最终执行权，行人条件并行与清空时间仍由派生信号方案和安全内核约束。

STGNN、MPC、MARL 采用独立的高级模型 artifact 协议：必须提供版本、输入输出签名、SHA-256、训练完成和验证通过证据才能激活。当前没有合格模型文件，因此不产生推断结果，也不将接口预留描述为已训练模型。
