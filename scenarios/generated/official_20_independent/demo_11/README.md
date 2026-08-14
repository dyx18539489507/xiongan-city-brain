# 官方独立路口 demo_11

这是一个可运行的独立 SUMO 路口工程，不是凭空生成的规则路口：

- 流量、15 分钟时变分布、转向运动和固定配时取自主办方 Excel；
- 中心位置、道路方位、道路等级及有标签时的车道数参考 OSM；
- 路口形态和车道可见信息由主办方高精地图 PNG 交叉核验；
- 主办方没有提供车辆类型构成，因此本样例仅采用 `1 PCU = 1 passenger`，未伪造车型比例；
- 所有小汽车采用用户指定主题色 `#FFFF00`；
- SUMO-GUI 演示步进延迟固定为 `300ms`；
- 道路中心线沿OSM node chain延伸到下一处拓扑路口；OSM拓扑与Excel进口方向冲突时会在manifest中明确记录；
- Excel源表内部一致性：`False`；不一致项见 `manifest.json` 的 `workbook_source_audit`；
- 本工程属于建模结果，不等同于测绘级/车道级高精地图真值。

| 时段 | 原始时钟 | 2小时车辆数 | 执行周期/Excel周期(s) | 9000秒内清空 |
|---|---:|---:|---:|---:|
| am_peak | 07:00-09:00 | 5962 | 170 / 170 | False |
| offpeak | 14:30-16:30 | 5180 | 130 / 130 | False |
| pm_peak | 17:30-19:30 | 6881 | 176 / 176 | False |

## 运行

```powershell
$env:SUMO_HOME='C:/path/to/sumo'
& $env:SUMO_HOME/bin/sumo-gui.exe -c demo_11_am_peak.sumocfg
& $env:SUMO_HOME/bin/sumo.exe -c demo_11_pm_peak.sumocfg
```

`validation.json` 是实际 SUMO 运行结果；`manifest.json` 保存源文件与派生文件哈希。
