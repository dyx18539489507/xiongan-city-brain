# B3 Coordinated Max Pressure

把云端区域权重、预测到达量和下游剩余容量叠加到本地最大压力，策略失效时自主退回 B2。实现：`src/traffic_platform/algorithms/coordinated.py`。
