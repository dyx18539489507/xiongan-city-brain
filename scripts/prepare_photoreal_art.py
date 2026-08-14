from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
TEXTURES = ROOT / "apps" / "unity-digital-twin" / "Assets" / "Xiongan" / "Resources" / "Art" / "Textures"


def normal_from_height(image: Image.Image, strength: float = 2.2) -> Image.Image:
    gray = np.asarray(image.convert("L").filter(ImageFilter.GaussianBlur(1.1)), dtype=np.float32) / 255.0
    grad_y, grad_x = np.gradient(gray)
    nx = -grad_x * strength
    ny = -grad_y * strength
    nz = np.ones_like(gray)
    length = np.sqrt(nx * nx + ny * ny + nz * nz)
    normal = np.stack(((nx / length + 1.0) * 127.5, (ny / length + 1.0) * 127.5, nz / length * 255.0), axis=-1)
    return Image.fromarray(np.clip(normal, 0, 255).astype(np.uint8), "RGB")


def mask_from_roughness(image: Image.Image) -> Image.Image:
    roughness = np.asarray(image.convert("L"), dtype=np.uint8)
    alpha = 255 - roughness
    zeros = np.zeros_like(alpha)
    return Image.fromarray(np.stack((zeros, zeros, zeros, alpha), axis=-1), "RGBA")


def prepare_facades() -> None:
    facade_dir = TEXTURES / "Facades"
    for atlas in sorted(facade_dir.glob("*_atlas.png")):
        image = Image.open(atlas).convert("RGB")
        width, height = image.size
        for index in range(4):
            left = round(width * index / 4)
            right = round(width * (index + 1) / 4)
            crop = image.crop((left, 0, right, height))
            stem = f"{atlas.stem.removesuffix('_atlas')}_{index + 1}"
            crop.save(facade_dir / f"{stem}_albedo.png", optimize=True)
            normal_from_height(crop, 1.45).save(facade_dir / f"{stem}_normal.png", optimize=True)
            luminance = np.asarray(crop.convert("L"), dtype=np.uint8)
            smooth = np.clip(72 + (luminance.astype(np.int16) - 96) // 2, 45, 190).astype(np.uint8)
            rgba = np.stack((np.zeros_like(smooth), np.zeros_like(smooth), np.zeros_like(smooth), smooth), axis=-1)
            Image.fromarray(rgba, "RGBA").save(facade_dir / f"{stem}_mask.png", optimize=True)


def prepare_pbr_masks() -> None:
    for roughness_path in TEXTURES.glob("PBR/*/*_rough_2k.jpg"):
        stem = roughness_path.name.replace("_rough_2k.jpg", "")
        mask_from_roughness(Image.open(roughness_path)).save(roughness_path.parent / f"{stem}_mask_2k.png", optimize=True)


def prepare_tree_alpha() -> None:
    tree_dir = TEXTURES.parent / "Models" / "island_tree_02" / "textures"
    color_path = tree_dir / "island_tree_02_leaves_diff_1k.png"
    alpha_path = tree_dir / "island_tree_02_leaves_alpha_1k.png"
    if not color_path.exists() or not alpha_path.exists():
        return
    color = Image.open(color_path).convert("RGB")
    alpha = Image.open(alpha_path).convert("L").resize(color.size, Image.Resampling.LANCZOS)
    rgba = color.copy()
    rgba.putalpha(alpha)
    rgba.save(tree_dir / "island_tree_02_leaves_rgba_1k.png", optimize=True)


if __name__ == "__main__":
    prepare_facades()
    prepare_pbr_masks()
    prepare_tree_alpha()
    print(f"Prepared photoreal art assets under {TEXTURES}")
