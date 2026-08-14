import * as THREE from "three";

export type TextureBudgetSnapshot = {
  textures: number;
  estimatedBytes: number;
  budgetBytes: number;
  withinBudget: boolean;
};

function textureBytes(texture: THREE.Texture): number {
  const source = texture.source?.data as {width?: number; height?: number} | undefined;
  const width = source?.width ?? 0;
  const height = source?.height ?? 0;
  // RGBA8 plus a conservative full mip-chain estimate.
  return Math.round(width * height * 4 * (4 / 3));
}

export class TextureManager {
  private readonly textures = new Set<THREE.Texture>();

  constructor(private readonly budgetBytes = 192 * 1024 * 1024) {}

  capture(root: THREE.Object3D): void {
    root.traverse((object) => {
      if (!(object instanceof THREE.Mesh)) return;
      const materials = Array.isArray(object.material) ? object.material : [object.material];
      for (const material of materials) {
        for (const value of Object.values(material)) {
          if (value instanceof THREE.Texture) this.textures.add(value);
        }
      }
    });
  }

  snapshot(): TextureBudgetSnapshot {
    const estimatedBytes = [...this.textures].reduce(
      (total, texture) => total + textureBytes(texture),
      0,
    );
    return {
      textures: this.textures.size,
      estimatedBytes,
      budgetBytes: this.budgetBytes,
      withinBudget: estimatedBytes <= this.budgetBytes,
    };
  }

  dispose(): void {
    for (const texture of this.textures) texture.dispose();
    this.textures.clear();
  }
}
