# 城市环境基础层（Phase 6）

## 数据真实性

当前建筑与绿地均从统一 `scene.json` 读取，没有手工挪动到另一套路网坐标：

- 79 个建筑轮廓来自 OSM；
- 12 个绿地/公园边界来自 OSM；
- 其中 1 个建筑有高度、1 个有楼层信息，78 个缺失高度；
- 缺失高度使用基于 `sceneId` 的确定性 10–28.6 m 工程默认值；
- 720 棵树为绿地内确定性采样，并执行道路中心线 7.5 m 避让；
- 269 盏路灯按普通机动车道路的外侧车道中点实例化。

建筑高度默认值、树木位置和路灯位置都是场景化假设，不是雄安现场测绘或资产台账。它们在界面和文档中不被描述为真实设施位置。

## 低配置实现

- `BuildingManager`：按住宅、商业、公共、普通四类材质合并 79 个拉伸建筑；
- 立面窗户沿真实轮廓边布置，统一为一个 `InstancedMesh`，不使用独立窗户 Draw Call；
- `VegetationManager`：绿地面合并为一个网格，树干和树冠各一个 `InstancedMesh`；
- `StreetFurnitureManager`：灯杆和灯头各一个 `InstancedMesh`，没有为每盏路灯创建实时光源；
- `HeroContextManager`：只在 K06 路口近景按需加载 `k06-hero.glb` 中 `K06_Architecture_*` 建筑节点；显式过滤模型内道路、标线、信号灯和家具，离开镜头后释放并恢复普通建筑；
- 全部几何使用米制 `CoordinateService`，静态对象不在运行帧中重建。

核心文件：

- `apps/web-dashboard/src/3d/environment/BuildingManager.ts`
- `apps/web-dashboard/src/3d/environment/VegetationManager.ts`
- `apps/web-dashboard/src/3d/environment/StreetFurnitureManager.ts`
- `apps/web-dashboard/src/3d/environment/HeroContextManager.ts`

固定画面：

- `outputs/3d/phase6/09_urban_overview.png`
- `outputs/3d/phase6/10_urban_buildings_closeup.png`

## 当前限制

OSM 在该范围只提供 79 个建筑轮廓，城市覆盖仍稀疏；没有在空白地块批量伪造“真实建筑”。K06 A 级建筑是原创 Blender 场景化资产，不是现场 BIM；B/C 级远景仍是基于 OSM 的低成本基础层。后续扩大建筑覆盖必须明确标注为程序背景，并先做道路/绿地/真实 footprint 排除。
