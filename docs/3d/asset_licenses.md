# 三维资产来源与许可

## 使用原则

当前 3D 资产不包含破解模型、来源不明商业模型或从第三方作品直接提取的网格。新增第三方资产前必须在本表记录 URL、作者、许可和比赛展示许可；无法确认时不得进入正式版本。

| 名称 | 文件 | 来源/作者 | License | 比赛展示 | 修改 | 证据边界 |
|---|---|---|---|---|---|---|
| K06 完整场景 | `apps/web-dashboard/public/assets/k06/k06-hero.glb` | 仓库内 `tools/visualization/build_k06_scene.py` 原创生成；项目团队 | 项目自有资产 | 是 | Blender 程序化生成 | 道路逻辑锚定 K06；建筑、绿化与街具是场景化假设，不是实景测绘 |
| K06 城市轿车 | `apps/web-dashboard/public/assets/k06/k06-vehicle.glb` | 同上；项目团队 | 项目自有资产 | 是 | Three.js 运行时增加独立轮组和低成本灯具 | 原创工程车辆，不对应具体厂牌 |
| 城市公交 | `apps/web-dashboard/public/assets/3d/vehicles/urban-bus.glb` | `tools/asset_pipeline/build_vehicle_variants.py` 原创生成；项目团队 | 项目自有资产 | 是 | PBR GLB、运行时轮组和 LOD | 工程车型轮廓，不对应具体厂牌或现场车队 |
| 城市物流卡车 | `apps/web-dashboard/public/assets/3d/vehicles/urban-truck.glb` | 同上；项目团队 | 项目自有资产 | 是 | PBR GLB、三轴运行时轮组和 LOD | 工程车型轮廓，不对应具体厂牌或现场车队 |
| 末端配送车 | `apps/web-dashboard/public/assets/3d/vehicles/delivery-van.glb` | 同上；项目团队 | 项目自有资产 | 是 | PBR GLB、运行时轮组和 LOD | 工程车型轮廓，不对应具体厂牌或现场车队 |
| K06 Blender 源文件 | `assets/3d/k06/k06-hero.blend` | 同上；项目团队 | 项目自有资产 | 是 | 可复现编辑 | 生成脚本与当前导出物的来源记录见 `assets/3d/k06/ASSET_SOURCES.md` |
| 道路/草地/铺装纹理 | `assets/3d/k06/textures/*.png` | 仓库内脚本原创生成；项目团队 | 项目自有资产 | 是 | 程序纹理 | 非航拍或现场材质采样 |
| ETC1S 道路纹理 | `apps/web-dashboard/public/assets/3d/textures/k06_asphalt.ktx2` | 上述原创 `k06_asphalt.png` 经 `encode_ktx2.ps1` 编码 | 项目自有资产 | 是 | KTX2/ETC1S、9 mip levels | 运行时机动车道路 base color；不是现场材质采样 |
| 行人参考 PNG | `scenarios/source/xiongan_rongdong_20/pedestrian_*.png` | 当前场景源资料 | 仅限现有工程内部使用，待补原始作者/许可证据 | 暂不进入 Three.js 正式资产 | 无 | 在许可证据补齐前不得作为 Web 3D 人物纹理发布 |
| 程序化建筑基础层 | `apps/web-dashboard/src/3d/environment/BuildingManager.ts` | 项目团队原创代码；轮廓数据来自项目 OSM 派生场景 | 代码随项目许可；OSM 数据沿用 ODbL 归属要求 | 是 | 运行时拉伸、合批与实例窗户 | 轮廓来自 OSM；78 个缺失高度为场景化假设，不是测绘高度 |
| 程序化树木与路灯 | `apps/web-dashboard/src/3d/environment/VegetationManager.ts`、`StreetFurnitureManager.ts` | 项目团队原创程序几何 | 项目自有资产 | 是 | 实例化生成 | 绿地边界来自 OSM；树木和路灯具体位置为工程假设 |
| 程序化自行车与骑行者 | `apps/web-dashboard/src/3d/bicycles/BicycleManager.ts` | 项目团队原创程序几何 | 项目自有资产 | 是 | 运行时对象池、LOD 和基础动画 | 不对应具体厂牌或真实人物 |
| 程序化行人 | `apps/web-dashboard/src/3d/pedestrians/PedestrianManager.ts` | 项目团队原创程序几何 | 项目自有资产 | 是 | 近景蒙皮/两骨骼肢链、对象池与三级 LOD | 未使用许可证据未明的行人参考 PNG |
| Draco Web 解码器 | `apps/web-dashboard/public/assets/decoders/draco/*` | Google Draco，经当前 Three.js npm 包分发 | Apache-2.0 | 是 | 未修改二进制；仅复制发布 | README 与许可链接随文件保留；只负责运行时解码 |
| Basis Universal 转码器 | `apps/web-dashboard/public/assets/decoders/basis/*` | Binomial LLC Basis Universal，经当前 Three.js npm 包分发 | Apache-2.0 | 是 | 未修改二进制；仅复制发布 | README 与许可链接随文件保留；只负责 KTX2/Basis 运行时转码 |
| KTX-Software 开发工具 | `tools/asset_pipeline/.tools/ktx-4.4.2/`（gitignored） | Khronos Group 官方 KTX-Software 4.4.2 | Apache-2.0 | 不随比赛包发布 | 固定版本与安装包 SHA，仅用于本地编码/验证 | 编码脚本可复现；工具二进制不进入仓库资产包 |

## 当前缺口

独立公交、卡车和物流车已纳入，并由固定镜头 `outputs/3d/final/11_vehicle_variants.png` 验证实际 GLB 加载；K06 A 级原创 Blender 建筑层已由 MX250 固定镜头验收。SUV、高精人物和独立自行车/电动自行车 GLB 尚未纳入；近景人物已用项目原创蒙皮几何满足低骨骼动画链路。当前人物、自行车、树木、路灯和普通建筑为原创低成本程序资产。
