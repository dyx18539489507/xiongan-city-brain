# Web 3D 资产流水线

## 运行时

`AssetManager` 共享 GLTFLoader、DRACOLoader 和 KTX2Loader，缓存相同 URL；`TextureManager` 复用纹理、估算 GPU bytes 并在 scene dispose 时释放。解码器位于 `apps/web-dashboard/public/assets/decoders/`，许可证见 `docs/3d/asset_licenses.md`。

## 实际 Draco 输出

Blender 4.5.12 的 glTF exporter 已实际生成 `KHR_draco_mesh_compression`，源文件未覆盖：

| 源资产 | optimized | 源字节 | optimized 字节 | Draco |
|---|---|---:|---:|---|
| `delivery-van.glb` | `delivery-van.optimized.glb` | 45,748 | 16,832 | 是 |
| `urban-bus.glb` | `urban-bus.optimized.glb` | 42,092 | 15,152 | 是 |
| `urban-truck.glb` | `urban-truck.optimized.glb` | 45,952 | 16,940 | 是 |
| `k06-vehicle.glb` | `k06-vehicle.optimized.glb` | 183,756 | 28,044 | 是 |

车型映射已指向 optimized 版本；manifest 测试要求源/优化成对、extensionRequired 为真且字节减少。

复现：

```powershell
.\.venv\Scripts\python.exe tools\asset_pipeline\optimize_glb_with_blender.py
.\.venv\Scripts\python.exe tools\asset_pipeline\build_manifest.py `
  --public-root apps\web-dashboard\public\assets `
  --output apps\web-dashboard\public\assets\manifest.json
```

Blender 路径由项目依赖探测或参数传入；脚本失败时不得伪造 optimized 文件。

## Manifest

`apps/web-dashboard/public/assets/manifest.json` 记录：asset/source/optimized、实际 bytes、SHA-256、triangles、embedded texture bytes、extensionsUsed/Required、Draco、KTX2、license 和 LOD。检测以 GLB JSON chunk 为准，不从文件名推断压缩。

## 实际 KTX2 输出

`tools/asset_pipeline/encode_ktx2.ps1` 固定使用 Khronos KTX-Software 4.4.2，并在运行前校验 Windows x64 安装包 SHA-256 `1f323b0fec19794f5e6c0425a61d4b1da396872a10be862d105f4f4b2d2957fe`。工具只解压到 gitignored 的 `.tools/`，不全局安装。编码使用 `toktx --encode etc1s --genmipmap`，随后执行 `ktx validate`。

```powershell
.\tools\asset_pipeline\encode_ktx2.ps1 `
  -InputPath assets\3d\k06\textures\k06_asphalt.png `
  -OutputPath apps\web-dashboard\public\assets\3d\textures\k06_asphalt.ktx2
```

当前真实输出为 11,192 bytes、256×256、9 mip levels、`vkFormat=0`、`supercompressionScheme=1`（ETC1S/BasisLZ），SHA-256 为 `c50c4b7dce6b701c470e7c6ada288ea10183382c0145242134284f3688204f50`。`build_manifest.py` 直接解析 KTX2 header 并拒绝伪文件；`MaterialManager` 通过 KTX2Loader 将该纹理实际用于机动车道路 base color，加载失败时才回退程序纹理。

这证明“实际 KTX2 编码、验证和运行加载”已闭环；不等于所有 GLB 内嵌纹理都已转换。车辆 optimized GLB 目前以 Draco 几何压缩为主，后续只有在材质/动画/轮组 QA 和下载/显存对比通过后才扩展 KTX2 覆盖，不能单纯为扩展名批量重写。

## 资产许可

当前公交/卡车/配送车为项目工程原创轻量资产，不对应厂牌；第三方解码器与资源来源逐项记录。禁止来源不明或破解商业模型。
