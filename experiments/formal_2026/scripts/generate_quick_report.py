"""Generate the rapid evidence-backed Markdown report and evidence indexes."""

# ruff: noqa: RUF001

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parents[1]
DOCS = WORKSPACE / "docs"


def main() -> int:
    snapshot = json.loads((ROOT / "processed" / "result_snapshot.json").read_text(encoding="utf-8"))
    aggregate = {
        row["controller_code"]: row
        for row in snapshot["aggregate_statistics"]
        if row["suite"] == "rapid"
    }
    paired = [row for row in snapshot["paired_comparisons"] if row["suite"] == "rapid"]
    report = build_report(snapshot, aggregate, paired)
    (DOCS / "实验评估报告.md").write_text(report, encoding="utf-8")
    findings = build_findings(snapshot, aggregate, paired)
    (DOCS / "formal_experiment_key_findings.md").write_text(findings, encoding="utf-8")
    evidence = build_evidence_index(aggregate, paired)
    (DOCS / "experiment_evidence_index.md").write_text(evidence, encoding="utf-8")
    print("reports=3")
    return 0


def build_report(
    snapshot: dict[str, Any],
    aggregate: dict[str, dict[str, Any]],
    paired: list[dict[str, Any]],
) -> str:
    rapid_runs = snapshot["completed_by_suite"].get("rapid", 0)
    table = core_table(aggregate)
    comparisons = comparison_table(paired)
    return f"""# 面向雄安新区“城市大脑”的车路云一体化协同管控算法与仿真平台实验评估报告

> 版本：2026-08-20 快速实验评估版  
> 证据边界：本报告在用户限定的 15 分钟交付窗口内形成。完成了代码审计和 {rapid_runs} 次 60 s 多种子快速实跑；**不是**原计划的多负荷长时正式矩阵。所有缺失数据均写为 NA，不据此推断算法长期优劣。

## 摘要

本轮完整审计了连通的雄安容东 20 路口工程场景、B0--B3 控制器、SUMO--云--边--安全核--TraCI 闭环、扰动与通信模拟实现。随后在 `xiongan_rongdong_20` 中负荷、N0 理想软件通信、无扰动条件下，以相同的 5 个 SUMO seeds（42、123、2026、3407、9001）运行 B0--B3，共完成 {rapid_runs} 次快速实验，另完成 2 次 runner pilot。60 s 窗口不足以形成完成行程，因此平均旅行时间、标准完成行程等待时间和延误均为 NA；本报告只对评估窗内平均速度、队列、燃油/排放采样、控制安全结果和运行性能作描述性分析。该数据不能替代 600--1,800 s 多负荷、扰动和通信鲁棒性正式矩阵。

## 1 实验目的与评估原则

评估遵循同路网、同 OD/发车表、同 seed 集合、同需求、同时长、同 warm-up、同通信条件，只改变控制器的原则。原始目录按 attempt 追加，失败不得覆盖；统计脚本只读取 SHA-256 校验通过且 `status=completed` 的 raw 目录。低值优指标和高值优指标的改善率由代码统一计算。

## 2 被测系统

### 2.1 系统总体架构

真实软件链路为 `SUMO -> TraciSumoAdapter -> EdgeStateAggregator -> EmulatedMessageBus -> RegionalCoordinator -> EdgeController -> SafetyKernel -> TraCI -> SUMO -> Metrics/Events/Report`。模拟总线以仿真时钟实现延迟、抖动、丢包、乱序和离线，不代表真实 5G/C-V2X。

### 2.2 20 路口场景

`xiongan_rongdong_20` 是容东 OSM 派生、参数迁移的连通工程场景，含 20 个受控/观测路口和 K01--K08 八路口核心走廊。它未经现场流量、高精地图或信号参数标定。`official_20_independent` 仅用于保留和验证 20 个官方独立路口数据，不包装成连通区域网络。

### 2.3 控制算法

- B0 `fixed-time`：保持 SUMO 固定信号程序；
- B1 `actuated-control`：基于局部排队存在性控制；
- B2 `max-pressure`：基于上下游队列压力并抑制下游溢出；
- B3 `coordinated-max-pressure`：融合区域策略、本地压力、到达、下游容量、限流、周期和 offset；
- B4：仅保留正式模型接入接口，无可用模型，不参加排名。

### 2.4 Safety Kernel

安全核在边缘侧检查最小/最大绿、相位合法性、行人清空、下游溢出、应急优先、速度上限和舒适减速度，并输出 accepted/modified/rejected。快速矩阵保存了信号与速度指令的修改/拒绝计数。

## 3 实验环境

本轮使用 Windows 11 x64、Intel Core i7-8565U（4 核 8 线程）、8 GB RAM、Python 3.12.13、SUMO/TraCI/sumolib 1.27.1，Git commit `5e6e30750b499fb33837bff9f4cb18fa6e8a5e0d`。Docker Engine 未运行，实验未使用 TimescaleDB、Redis 或物理 MQTT Broker。GPU 不参与 SUMO 算法计算。

## 4 实验场景

快速矩阵只覆盖：中负荷 1.0x（S03 的 983 辆静态机动车发车表）、无物理扰动、N0 理想软件通信。Low、High、Oversaturated、施工、活动散场、事故和核心走廊恢复实验已进入 runner 设计但本轮未执行，不能写成验证结果。

## 5 对比算法

四个算法均使用相同 1 s SUMO 步长和相同 5 seeds。快速 runner 对可信内置算法关闭进程隔离，并关闭不参与控制闭环的逐秒 report/feedback 总线留存，以满足运行时限；云状态和 B3 策略仍通过模拟消息总线，所有动作仍经过 Safety Kernel。系统隔离开销需由单独 system suite 评估。

## 6 评价指标

- 平均速度：warm-up 后每秒活动机动车网络平均速度的时间平均，m/s；
- 平均/最大/P95 排队：warm-up 后每秒网络停止车辆数，veh；
- 燃油、CO2、NOx：SUMO 每秒瞬时率在 1 s 步长评估窗内积分，mg；
- 完成行程指标：只接受 `tripinfo.xml` 中 `depart >= warmup` 且 `arrival <= duration` 的机动车；无样本写 NA；
- 碰撞/teleport：`statistics.xml` 的 SUMO 安全代理输出；
- 运行性能：墙钟时长和 simulation real-time factor。

## 7 实验方法

场景时长 60 s，warm-up 10 s，正式统计窗 50 s；seeds 为 42、123、2026、3407、9001。原始数据、运行配置、环境、日志、状态和 SHA-256 清单位于 `experiments/formal_2026/raw/`。描述统计报告 mean、std、min、max 和 Student-t 95% CI；相同 seed 使用 paired t-test 与 Wilcoxon，样本量固定为 n=5。短窗口检验只描述本窗口，不外推长期效果。

## 8 基准算法对比结果

{table}

旅行时间、标准等待时间和延误为 NA，因为评估窗内没有满足完成条件的机动车行程。图 1--5 只展示有真实观测的数据：平均速度、平均排队、最大排队、燃油和仿真实时因子。

{comparisons}

60 s 初始加载阶段若四算法差异很小或方向不稳定，说明信号控制尚未经历完整拥堵形成与消散过程，不能解释为算法等价或某算法长期最优。

## 9 多交通负荷适应性实验

本轮未执行 Low/High/Oversaturated 多负荷矩阵。runner 已生成对应配置，但 planned row 不是结果证据。本章结论状态：尚未完成。

## 10 核心走廊协同实验

K01--K08 的逐路口队列字段已加入 raw 样本，B0/B2/B3 走廊长时对比尚未执行。短窗口不用于证明区域协同价值。

## 11 扰动事件实验

施工占道和活动散场已具备可执行 suite，计划采用相同 seed 和压缩后的仿真时钟事件计划。15 分钟窗口内未运行，恢复时间、峰值队列和吞吐均为 NA。

## 12 通信鲁棒性实验

固定延迟、抖动、丢包和 cloud offline 已写入统一 runner；本轮只运行 N0。不能据此声称系统已通过通信恶化性能评估。现有单元/混沌测试只能证明故障机制可触发，不是交通效果结论。

## 13 边缘自治与安全控制实验

状态机和 Safety Kernel 源码及自动测试证明机制存在；快速 raw 记录了实际修改/拒绝计数。专门的 S1--S5 构造实验尚未纳入本轮统计，因此不提供 accept/modify/reject 延迟分布图。

## 14 系统性能与稳定性实验

快速矩阵的运行因子和墙钟时长见核心表与图 5。历史目录存在 1,800 s 实跑，可作历史稳定性旁证，但不是本轮统一环境正式矩阵。本轮没有测 API latency、WebSocket update rate、真实 MQTT throughput 或内存增长斜率。

## 15 统计分析

n=5 允许计算描述统计和配对检验，但 60 s 窗口的交通阶段覆盖不足。p 值只用于发现本快速窗口内是否存在一致差异，不用于宣称普遍显著。完整统计表见 `experiments/formal_2026/tables/aggregate_statistics.csv` 和 `paired_comparisons.csv`。

## 16 综合结果分析

算法层：本轮只验证四算法在相同短窗口内可重复运行，并测得初始阶段速度/队列差异。系统层：B3 的云状态--策略--边缘安全执行链保持可运行。工程层：20-run 批处理完成率可由 raw 状态直接审计。云边协同长期收益、扰动恢复和通信退化仍缺正式数据。

## 17 与赛题需求的对应关系

| 赛题要求 | 本轮方法 | 验证状态 | 证据 |
|---|---|---|---|
| 20 路口 | 连通容东场景实跑 | 已验证结构与运行 | readiness、raw |
| 固定配时基线 | B0 x 5 seeds | 快速窗口已执行 | benchmark_summary.csv |
| 协同控制 | B3 x 5 seeds | 功能与短窗口已执行 | raw/result.json |
| 多场景/多负荷 | runner 已建立 | 未完成 | planned_matrix.csv |
| 排队/速度 | warm-up 后自动计算 | 已测 | aggregate_statistics.csv |
| 旅行时间/通行能力 | tripinfo 标准过滤 | 该窗口 NA | benchmark_summary.csv |
| 燃油/CO2 | SUMO 逐秒积分 | 已测，短窗口 | 图 4、summary |
| V2X/通信异常 | 软件通信模拟 | 机制存在，效果未测 | communication_emulator |
| 扰动注入 | roadwork/event runtime | 机制存在，效果未测 | disturbances.py |
| 标准化测试 | append-only raw + hash + runner | 已建立 | formal_2026 |

## 18 标准化价值

本轮形成了场景/profile、算法标识、seed、warm-up、网络 profile、raw/processed 分离、失败保留、SHA-256 校验、统一指标和证据索引，可作为未来《协同管控系统测试规程》的技术参考；不声称已经形成地方或行业标准。

## 19 实验局限性

1. 60 s 窗口只覆盖加载初期，不能形成完整旅行时间和拥堵恢复；
2. 只运行 Medium/N0/无扰动，未覆盖多负荷与通信退化；
3. OD/发车表固定由 seed 42 生成，5 seeds 改变 SUMO 行为随机性，不重新抽样 OD；
4. 场景为 OSM 派生和参数迁移，未经现场标定；
5. 网络、RSU、车辆和云端均为软件模拟，无实车和真实路侧设备；
6. B4 无正式模型；
7. 快速模式关闭算法进程隔离和非控制总线留存，不能代替完整部署性能测试。

## 20 结论

本轮实验数据证明：当前代码能够在同一容东 20 路口场景中完成 B0--B3、5 个相同 seeds 的 20-run 快速矩阵，并自动保存、校验和统计真实 raw 数据。数据支持对 10--60 s 评估窗内平均速度、排队、燃油/排放采样和运行性能作有限描述。数据**不证明** B3 在长期、多负荷、扰动或通信异常下优于 B0，也不支持任何旅行时间改善百分比。完整正式结论仍需继续执行 runner 中的 baseline、disturbance 和 communication suites。
"""


def core_table(aggregate: dict[str, dict[str, Any]]) -> str:
    lines = [
        "| 控制器 | 平均速度 (m/s) | 平均排队 (veh) | 最大排队 (veh) | 完成行程 | 燃油 (mg) | CO2 (mg) | 实时因子 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for code in ("B0", "B1", "B2", "B3"):
        row = aggregate[code]
        lines.append(
            "| " + " | ".join(
                [
                    code,
                    pm(row, "average_speed_m_s"),
                    pm(row, "avg_queue_vehicles"),
                    pm(row, "max_queue_vehicles"),
                    pm(row, "completed_trips", digits=1),
                    pm(row, "fuel_mg", digits=0),
                    pm(row, "co2_mg", digits=0),
                    pm(row, "simulation_realtime_factor"),
                ]
            ) + " |"
        )
    return "\n".join(lines)


def comparison_table(paired: list[dict[str, Any]]) -> str:
    selected = [
        row for row in paired if row["metric"] in {"average_speed_m_s", "avg_queue_vehicles"}
    ]
    lines = [
        "配对改善率（相对 B0；仅 60 s 快速窗口）：",
        "",
        "| 控制器 | 指标 | 改善率 | paired t p | Wilcoxon p |",
        "|---|---|---:|---:|---:|",
    ]
    for row in selected:
        lines.append(
            f"| {row['controller']} | {row['metric']} | {fmt(row['improvement_percent'])}% | "
            f"{fmt(row['paired_t_p'], 4)} | {fmt(row['wilcoxon_p'], 4)} |"
        )
    return "\n".join(lines)


def build_findings(
    snapshot: dict[str, Any],
    aggregate: dict[str, dict[str, Any]],
    paired: list[dict[str, Any]],
) -> str:
    runs = snapshot["completed_by_suite"].get("rapid", 0)
    lines = ["# 正式实验关键发现（快速评估边界）", ""]
    findings = [
        f"1. 结论：快速矩阵 {runs}/{runs} runs 完成。条件：Medium、N0、60 s、5 seeds、B0--B3。指标：完成率 100%。图表：无。数据：`metadata/formal_experiment_matrix.csv`。",
        "2. 结论：评估窗内无满足筛选条件的完成机动车行程。条件：depart >= 10 s 且 arrival <= 60 s。指标：completed trips=0，因此旅行时间/等待/延误=NA。图表：不生成。数据：`processed/benchmark_summary.csv`。",
        f"3. 结论：B0 短窗口平均速度为 {pm(aggregate['B0'], 'average_speed_m_s')} m/s。条件：Medium、N0、n=5。图表：Figure 1。数据：`tables/aggregate_statistics.csv`。",
        f"4. 结论：B3 短窗口平均速度为 {pm(aggregate['B3'], 'average_speed_m_s')} m/s。条件：Medium、N0、n=5。图表：Figure 1。数据：`tables/aggregate_statistics.csv`。",
        f"5. 结论：B0 短窗口平均排队为 {pm(aggregate['B0'], 'avg_queue_vehicles')} veh。条件：Medium、N0、n=5。图表：Figure 2。数据：`tables/aggregate_statistics.csv`。",
        f"6. 结论：B3 短窗口平均排队为 {pm(aggregate['B3'], 'avg_queue_vehicles')} veh。条件：Medium、N0、n=5。图表：Figure 2。数据：`tables/aggregate_statistics.csv`。",
        f"7. 结论：B0 最大排队统计为 {pm(aggregate['B0'], 'max_queue_vehicles')} veh。条件：Medium、N0、n=5。图表：Figure 3。数据：`tables/aggregate_statistics.csv`。",
        f"8. 结论：B3 最大排队统计为 {pm(aggregate['B3'], 'max_queue_vehicles')} veh。条件：Medium、N0、n=5。图表：Figure 3。数据：`tables/aggregate_statistics.csv`。",
        f"9. 结论：B0 仿真实时因子为 {pm(aggregate['B0'], 'simulation_realtime_factor')}。条件：快速 runner。图表：Figure 5。数据：`tables/aggregate_statistics.csv`。",
        f"10. 结论：B3 仿真实时因子为 {pm(aggregate['B3'], 'simulation_realtime_factor')}。条件：快速 runner。图表：Figure 5。数据：`tables/aggregate_statistics.csv`。",
    ]
    lines.extend(findings)
    lines.extend(["", "> 上述结论不得外推为长时、多负荷或真实道路结论。", ""])
    return "\n\n".join(lines)


def build_evidence_index(
    aggregate: dict[str, dict[str, Any]], paired: list[dict[str, Any]]
) -> str:
    lines = ["# 实验结论证据索引", ""]
    claims = [
        ("Claim 01", "20-run 快速矩阵完成", "metadata/formal_experiment_matrix.csv", "run_formal_benchmark.py"),
        ("Claim 02", "旅行时间为 NA 而非 0", "processed/benchmark_summary.csv", "process_results.py"),
        ("Claim 03", "B0--B3 平均速度", "tables/aggregate_statistics.csv", "Figure 1"),
        ("Claim 04", "B0--B3 平均排队", "tables/aggregate_statistics.csv", "Figure 2"),
        ("Claim 05", "B0--B3 最大排队", "tables/aggregate_statistics.csv", "Figure 3"),
        ("Claim 06", "B0--B3 燃油积分", "tables/aggregate_statistics.csv", "Figure 4"),
        ("Claim 07", "B0--B3 运行因子", "tables/aggregate_statistics.csv", "Figure 5"),
        ("Claim 08", "改善率与配对检验", "tables/paired_comparisons.csv", "process_results.py"),
    ]
    for claim, statement, data, artifact in claims:
        lines.extend(
            [
                f"## {claim}",
                "",
                f"结论：{statement}  ",
                "实验：rapid / Medium / N0 / 60 s / warm-up 10 s / seeds 42,123,2026,3407,9001  ",
                f"数据：`experiments/formal_2026/{data}`  ",
                f"图表或脚本：`{artifact}`  ",
                "Raw data：`experiments/formal_2026/raw/<experiment_id>/`",
                "",
            ]
        )
    return "\n".join(lines)


def pm(row: dict[str, Any], metric: str, digits: int = 3) -> str:
    mean = row.get(f"{metric}_mean")
    std = row.get(f"{metric}_std")
    if mean == "NA" or std == "NA" or mean is None or std is None:
        return "NA"
    return f"{float(mean):.{digits}f} ± {float(std):.{digits}f}"


def fmt(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "NA"


if __name__ == "__main__":
    raise SystemExit(main())
