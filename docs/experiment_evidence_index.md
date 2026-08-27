# 实验结论证据索引

## Claim 01

结论：20-run 快速矩阵完成  
实验：rapid / Medium / N0 / 60 s / warm-up 10 s / seeds 42,123,2026,3407,9001  
数据：`experiments/formal_2026/metadata/formal_experiment_matrix.csv`  
图表或脚本：`run_formal_benchmark.py`  
Raw data：`experiments/formal_2026/raw/<experiment_id>/`

## Claim 02

结论：旅行时间为 NA 而非 0  
实验：rapid / Medium / N0 / 60 s / warm-up 10 s / seeds 42,123,2026,3407,9001  
数据：`experiments/formal_2026/processed/benchmark_summary.csv`  
图表或脚本：`process_results.py`  
Raw data：`experiments/formal_2026/raw/<experiment_id>/`

## Claim 03

结论：B0--B3 平均速度  
实验：rapid / Medium / N0 / 60 s / warm-up 10 s / seeds 42,123,2026,3407,9001  
数据：`experiments/formal_2026/tables/aggregate_statistics.csv`  
图表或脚本：`Figure 1`  
Raw data：`experiments/formal_2026/raw/<experiment_id>/`

## Claim 04

结论：B0--B3 平均排队  
实验：rapid / Medium / N0 / 60 s / warm-up 10 s / seeds 42,123,2026,3407,9001  
数据：`experiments/formal_2026/tables/aggregate_statistics.csv`  
图表或脚本：`Figure 2`  
Raw data：`experiments/formal_2026/raw/<experiment_id>/`

## Claim 05

结论：B0--B3 最大排队  
实验：rapid / Medium / N0 / 60 s / warm-up 10 s / seeds 42,123,2026,3407,9001  
数据：`experiments/formal_2026/tables/aggregate_statistics.csv`  
图表或脚本：`Figure 3`  
Raw data：`experiments/formal_2026/raw/<experiment_id>/`

## Claim 06

结论：B0--B3 燃油积分  
实验：rapid / Medium / N0 / 60 s / warm-up 10 s / seeds 42,123,2026,3407,9001  
数据：`experiments/formal_2026/tables/aggregate_statistics.csv`  
图表或脚本：`Figure 4`  
Raw data：`experiments/formal_2026/raw/<experiment_id>/`

## Claim 07

结论：B0--B3 运行因子  
实验：rapid / Medium / N0 / 60 s / warm-up 10 s / seeds 42,123,2026,3407,9001  
数据：`experiments/formal_2026/tables/aggregate_statistics.csv`  
图表或脚本：`Figure 5`  
Raw data：`experiments/formal_2026/raw/<experiment_id>/`

## Claim 08

结论：改善率与配对检验  
实验：rapid / Medium / N0 / 60 s / warm-up 10 s / seeds 42,123,2026,3407,9001  
数据：`experiments/formal_2026/tables/paired_comparisons.csv`  
图表或脚本：`process_results.py`  
Raw data：`experiments/formal_2026/raw/<experiment_id>/`

## Claim 09

结论：B3 v2 预测闭环与安全相位执行通过 B0/B3 单种子真实配对验收  
实验：BASE / 120 s / seed 202613 / `fixed-time` 与 `coordinated-max-pressure` 2.0  
指标：prediction ready 88.3%，confidence 0.837，60 s queue MAE 1.999 veh，unsafe rejection 0，algorithm failure/timeout 0  
数据：`results/benchmarks/b3-v2-paired-verified/benchmark.json`  
Raw data：`results/benchmarks/b3-v2-paired-verified/runs/smoke-coordinated-max-pressure-88d1efd4/result.json`  
边界：功能、预测误差和安全执行验收；该短时样本的 B3 速度与排队劣于 B0，不是性能优越性证明
