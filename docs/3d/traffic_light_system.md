# Three.js 信号灯系统（Phase 5）

## 真值与边界

信号相位唯一真值是 SUMO/TraCI。前端不生成相位、不轮播颜色，也不按路口聚合成一个三色灯。WebSocket 的 `trafficLights[].state` 按 SUMO `linkIndex` 驱动对应灯面；没有实时状态时所有灯面保持暗态。

静态映射来自 `xiongan_rongdong_20.scene.json`，生成器同时输出：

- `generated/scenes/xiongan_rongdong_20.traffic_light_mapping.json`
- 20 个 `sumoTlsId` / `controlledJunctionId`
- 351 条 `linkIndex -> fromLaneId -> toLaneId -> viaLaneId` 映射
- 每个相位的状态字符串长度

验证命令：

```powershell
.\.venv\Scripts\python.exe tools\scene_generator\validate_traffic_light_mapping.py `
  generated\scenes\xiongan_rongdong_20.scene.json `
  generated\scenes\xiongan_rongdong_20.traffic_light_mapping.json
```

当前真实输出为 `valid=true`、`controllers=20`、`links=351`、`errors=[]`。

## 三维映射

`TrafficLightManager` 根据真实进口车道末端和车道方向放置信号设施：

1. 同一进口车道共享一根物理灯杆；
2. 每条控制链路保留独立灯头和 `linkIndex`；
3. 灯杆、灯箱、红/黄/绿灯面分别合批，方向箭头/行人/非机动车符号再按 3 类共享批次；
4. 信号状态使用 `state[linkIndex]` 更新实例颜色；
5. `pedestrian*` 与 `bicycle/cycle*` lane 使用较低、较小的灯头，无意义黄灯隐藏；
6. 机动车/混合 lane 根据真实 `fromLane -> toLane` 几何判定左/直/右，符号只改变灯面外观，不改变 SUMO `linkIndex` 状态；
7. 不为灯面创建 `PointLight` 或 `SpotLight`。

核心代码：

- `apps/web-dashboard/src/3d/trafficLights/TrafficLightManager.ts`
- `apps/web-dashboard/src/3d/trafficLights/TrafficLightManager.test.ts`

## 当前视觉边界

- 链路级位置、状态和左/直/右符号已经真实映射；行人/非机动车采用轻量剪影，不是高精度灯具 GLB；
- `remainingS` 已在实时协议和点击详情中显示，当前灯杆没有额外倒计时牌；
- 灯杆横臂、遮光罩和道路侧安装细节将在视觉优化阶段继续提升。

这些边界不影响 SUMO 相位真实性；当前已经满足方向、行人和非机动车灯面的功能区分，但不宣称电影级交通灯资产。
