# K06 三维资产来源与证据边界

## 可复现来源

- 场景几何生成脚本：`tools/visualization/build_k06_scene.py`
- 路网锚点：`scenarios/generated/xiongan_rongdong_20/rongdong.multimodal.net.xml`
- 目标路口：SUMO junction `11122023451`，展示编号 `K06`，场景锚点 `demo_14`
- Blender 工具链：Blender Foundation 4.5.12 LTS Windows x64 portable，下载包在本机通过官方 SHA-256 校验
- 道路、建筑、植被、车辆、信号机和三张基础纹理均由仓库内脚本生成，没有引入第三方商业模型或未核验素材

## 使用边界

K06 的路口类型、道路走向和车道组织取自当前连通 SUMO 工程场景。建筑立面、绿化、街具和车辆属于面向展示的原创工程视觉资产，不是现场测绘重建。该场景应表述为“仿真三维可视化样板”或“准数字孪生展示”，不得表述为厘米级、实景复刻或运行级数字孪生。
