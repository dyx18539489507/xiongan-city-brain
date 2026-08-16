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

## Unity 网页三维场景补充（2026-08-16）

当前比赛展示使用的 Unity WebGL 场景已经在上述可追溯基础上增加程序化城市背景，解决 OSM 建筑稀疏导致的大面积无建筑问题。烘焙场景共显示 1079 栋建筑：

- 79 栋来自统一 `scene.json` 的 OSM footprint；
- 12 栋为 K08 主展示区原创工程建筑；
- 248 栋为 20 个控制路口周边的程序化工程组团；
- 740 栋为全城功能区和道路沿线的程序化背景建筑。

全城背景按 112 m 规划网格分轮生成，并以道路距离、真实 OSM footprint、已生成建筑占地、控制路口安全区和公园/绿地边界执行排除。生成顺序经过确定性空间交错，避免旧版顺序扫描让城市一端先耗尽数量上限。10 个大型公园/绿地区域增加了实体慢行步道、铺装和公共廊亭，用空间用途解释保留的无建筑区域。

程序建筑采用雄安新区的规划新城视觉语言：低中层板楼和围合组团为主，办公/商业使用克制的裙房与塔楼组合，校园采用低层条形体量；立面统一为浅暖石材、灰白预制板、低饱和蓝灰玻璃、水平窗带和少量竖向构件。该设计只是区域风格建模，不代表对应地块的真实建筑、BIM、层数或立面测绘。

道路沥青、建筑墙面、屋面和铺装继续使用程序材质与实体网格，不加载照片、背景板或建筑/墙面位图。2026-08-16 构建门禁再次检查这些材质没有纹理引用；位图只允许用于有来源的独立三维树木/路灯道具。当前 WebGL 产物为 168,622,466 bytes，Unity 场景约 122.7 MB 压缩 / 306.2 MB 解压。
