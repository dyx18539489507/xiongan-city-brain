# `xiongan_rongdong_20` 三维场景生成流水线

## 目标与证据边界

Phase 1 把已有联通 SUMO 场景转换为一个可追溯、可校验的静态中间格式。生成过程不修改 SUMO，不从 `official_20_independent` 取代联通路网，也不补造不存在的 RSU、公交站或实测建筑。OSM 派生建筑和功能区是工程场景资料，不声明为雄安现场测绘结果。

## 输入

生成器固定读取以下来源，并把路径、用途和 SHA-256 写入场景 metadata：

| 来源 | 用途 |
|---|---|
| `scenarios/generated/xiongan_rongdong_20/rongdong.multimodal.net.xml` | 路网、lane、connection、crossing、TLS 真值 |
| `scenarios/generated/xiongan_rongdong_20/controlled_intersections.json` | 20 个控制点和 K01—K08 注册关系 |
| `scenarios/generated/xiongan_rongdong_20/functional_zones.json` | 功能区清单来源 |
| `scenarios/source/xiongan_rongdong_20/rongdong_bbox.osm.xml` | OSM 建筑、植被、区域和设备证据 |
| `scenarios/generated/xiongan_rongdong_20/vtypes.add.xml` | SUMO 参与者类型来源 |
| `scenarios/configs/xiongan_rongdong_20.yaml` | 场景配置来源 |

## 选择规则

20 个注册控制路口的包围盒向外扩展 300 m，所有几何包围盒与该范围相交的 SUMO 对象进入场景。这个规则保留控制区上下文，但不是裁剪后的独立 SUMO 网络；动态仿真仍使用完整联通网络。

场景包含稳定 ID 映射：

- `junction:<SUMO junction id>`；
- `edge:<SUMO edge id>`；
- `lane:<SUMO lane id>`；
- `tls:<SUMO TLS id>`；
- `road:osm-way:<normalized way id>`。

每个 lane、connection、crossing 和 TLS link 均保留原始 SUMO ID。K01—K08 走廊按相邻注册路口分别计算 SUMO 有向最短路，`segments` 同时保存正向和反向 edge 列表；不存在的方向保持空列表，绝不把反向 edge 冒充正向可行驶路径。

## 生成命令

```powershell
.\.venv\Scripts\python.exe -m traffic_platform.cli generate-3d-scene
```

也可使用：

```powershell
.\deployment\scripts\task.ps1 generate-3d-scene
```

输出：

- `generated/scenes/xiongan_rongdong_20.scene.json`
- `generated/scenes/xiongan_rongdong_20.scene.schema.json`
- `generated/scenes/xiongan_rongdong_20.scene.manifest.json`
- `generated/scenes/xiongan_rongdong_20.traffic_light_mapping.json`

JSON 使用紧凑编码以减少首次下载和解析压力；schema 保留缩进以便审阅。相同输入和生成器版本应产生完全相同的 scene SHA-256。源文件哈希变化时必须重新生成并重新执行验收。

## 当前生成范围

当前生成物包含 20 个受控路口和对应 TLS、SUMO 道路/车道/连接/横道/步行区、可识别的自行车区域、OSM 建筑/植被/功能区以及核心走廊和 edge 分区。`busStops` 为 0 表示当前来源范围没有匹配证据。40 个 `roadsideDevices` 是生成器 1.2.0 基于真实受控进口 lane 建立的工程布局，provenance 与 `runtime_unbound` 状态禁止其被解释为真实部署清单。

2026-08-07 的 Phase 1 生成快照为：

| 对象 | 数量 | 对象 | 数量 |
|---|---:|---|---:|
| junctions | 1513 | roads | 181 |
| edges | 7042 | lanes | 8914 |
| connections | 12211 | crossings | 633 |
| trafficLights | 20 | pedestrianAreas | 794 |
| bicycleAreas | 1743 | buildings | 79 |
| vegetation | 12 | zones | 75 |
| busStops | 0 | roadsideDevices | 40（20 RSU + 20 camera，工程建模） |

紧凑 scene 文件为 `11,868,663 bytes`，SHA-256 为 `8c2e916243b53bb18678de2cd5745f6628febdf2d4e6295ffcd66b965288095b`。这只是静态初始化数据体积；Phase 2 在浏览器加载前仍需按渲染职责拆分或提供压缩传输，不能让低配置机器长期保留 XML、完整 JSON 字符串和解析后对象的多份副本。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\test_scene_generator.py -q
.\.venv\Scripts\python.exe -m ruff check src\traffic_platform\scene tests\unit\test_scene_generator.py
.\.venv\Scripts\python.exe -m mypy src
```

自动测试验证：严格 schema、20 个受控 junction/TLS、K01—K08 顺序、7 个有向走廊区段、lane/connection 引用闭包、源文件 SHA-256 和关键坐标往返。
