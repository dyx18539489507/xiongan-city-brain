# 正式实验关键发现（快速评估边界）



1. 结论：快速矩阵 20/20 runs 完成。条件：Medium、N0、60 s、5 seeds、B0--B3。指标：完成率 100%。图表：无。数据：`metadata/formal_experiment_matrix.csv`。

2. 结论：评估窗内无满足筛选条件的完成机动车行程。条件：depart >= 10 s 且 arrival <= 60 s。指标：completed trips=0，因此旅行时间/等待/延误=NA。图表：不生成。数据：`processed/benchmark_summary.csv`。

3. 结论：B0 短窗口平均速度为 8.560 ± 0.140 m/s。条件：Medium、N0、n=5。图表：Figure 1。数据：`tables/aggregate_statistics.csv`。

4. 结论：B3 短窗口平均速度为 8.600 ± 0.029 m/s。条件：Medium、N0、n=5。图表：Figure 1。数据：`tables/aggregate_statistics.csv`。

5. 结论：B0 短窗口平均排队为 3.508 ± 0.151 veh。条件：Medium、N0、n=5。图表：Figure 2。数据：`tables/aggregate_statistics.csv`。

6. 结论：B3 短窗口平均排队为 3.468 ± 0.091 veh。条件：Medium、N0、n=5。图表：Figure 2。数据：`tables/aggregate_statistics.csv`。

7. 结论：B0 最大排队统计为 7.400 ± 0.548 veh。条件：Medium、N0、n=5。图表：Figure 3。数据：`tables/aggregate_statistics.csv`。

8. 结论：B3 最大排队统计为 7.400 ± 0.548 veh。条件：Medium、N0、n=5。图表：Figure 3。数据：`tables/aggregate_statistics.csv`。

9. 结论：B0 仿真实时因子为 1.234 ± 0.085。条件：快速 runner。图表：Figure 5。数据：`tables/aggregate_statistics.csv`。

10. 结论：B3 仿真实时因子为 1.044 ± 0.144。条件：快速 runner。图表：Figure 5。数据：`tables/aggregate_statistics.csv`。

11. 结论：B3 v2 的 120 s 单种子真实配对验收中，在线预测就绪率 88.3%，平均置信度 0.837，60 s 队列预测 MAE 1.999 veh，算法失败/超时/安全拒绝均为 0。条件：BASE、seed 202613、B0/B3 同路网同需求配对，仅功能与预测链路验收。图表：驾驶舱“B0 / B3 排队演化”和“B3 预测命中证据”。数据：`results/benchmarks/b3-v2-paired-verified/benchmark.json`。该 120 s 结果中 B3 的平均速度和平均排队均劣于 B0，必须如实展示，不得外推为性能优越性。



> 上述结论不得外推为长时、多负荷或真实道路结论。

