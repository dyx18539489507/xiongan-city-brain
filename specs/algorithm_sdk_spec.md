# 算法 SDK 规范

算法实现统一遵循 `TrafficControlAlgorithm` 协议：

```python
class TrafficControlAlgorithm(Protocol):
    name: str
    version: str
    def initialize(self, config: AlgorithmConfig, topology: NetworkTopology) -> None: ...
    def reset(self, seed: int) -> None: ...
    def observe(self, state: ControlObservation) -> None: ...
    def decide(self, state: ControlObservation) -> ControlDecision: ...
    def feedback(self, feedback: ExecutionFeedback) -> None: ...
    def health(self) -> AlgorithmHealth: ...
    def close(self) -> None: ...
```

注册表以名称和语义版本发现算法。执行器负责配置校验、决策超时、异常隔离、耗时
统计和输入输出结构化日志。算法只能返回候选 `ControlDecision`，不得直接调用
TraCI、数据库、MQTT 或其他算法内部对象。

当前注册表严格包含四个算法：

- `fixed-time` 1.0.0
- `actuated-control` 1.0.0
- `max-pressure` 1.0.0
- `coordinated-max-pressure` 2.0.0

B3 通过 `CloudStrategy.forecasts` 接收带模型版本、预测时距、置信度和生成时刻的真实在线预测。预测未就绪或置信度不足时在 B3 内部回退到当前状态协调，不注册额外算法。
