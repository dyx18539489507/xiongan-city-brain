# 三维坐标系统

## 唯一坐标规则

`rongdong.multimodal.net.xml` 的 `<location>` 是坐标真值。当前网络使用 WGS84 / UTM zone 50N，并带 SUMO `netOffset`：

- `netOffset = (-402358.92, -4317416.65)`；
- `convBoundary = (0, 0, 13746.09, 17380.55)`；
- `origBoundary = (115.826838, 39.000573, 116.031026, 39.158097)`；
- 投影：`+proj=utm +zone=50 +ellps=WGS84 +datum=WGS84 +units=m +no_defs`。

Three.js 世界单位固定为米。轴定义固定为：

- `+X`：向东；
- `+Y`：向上；
- `-Z`：向北。

世界浮动原点取 20 个控制点包围盒中心并保留 3 位小数，当前为 SUMO `(3691.650, 6515.815)`。所有道路、车辆、信号灯、行人、非机动车和路侧设备都必须调用同一个服务，不允许模块局部加入偏移或翻转。

## 变换

SUMO 到 Three.js：

```text
world.x = sumo.x - origin.x
world.y = height
world.z = origin.y - sumo.y
```

Three.js 到 SUMO：

```text
sumo.x = world.x + origin.x
sumo.y = origin.y - world.z
```

SUMO 角度到 Three.js yaw 统一取负并归一化；逆变换归一化到 `[0, 360)`。后续车辆插值必须对 quaternion 做最短弧插值，不能直接线性插值欧拉角。

SUMO 到经纬度时先去除 `netOffset` 得到 UTM easting/northing，再投影到 WGS84；逆变换按相反次序执行。后端采用 `pyproj`，前端采用相同 WGS84/UTM 公式，正式绘制仍以场景中的 SUMO 米制 geometry 为准，经纬度仅用于地理联动和诊断。

## 实现位置

- Python：`src/traffic_platform/scene/coordinates.py`
- TypeScript：`apps/web-dashboard/src/3d/core/CoordinateService.ts`
- 后端测试：`tests/unit/test_scene_generator.py`
- 前端测试：`apps/web-dashboard/src/3d/core/CoordinateService.test.ts`

## 当前验收

注册路口 K06 的 SUMO 坐标 `(4005.52, 5451.76)` 转换为约 `(115.9179083104, 39.0498753480)`，再逆转换的误差小于 `1e-6 m`。全网 sumolib 只读抽查的经纬度往返最大误差约 `1.53e-9 m`。这证明数学转换一致，但道路、车辆、TLS 和行人的最终空间贴合仍需在 Phase 2—5 的固定镜头和运行态验收中分别确认。
