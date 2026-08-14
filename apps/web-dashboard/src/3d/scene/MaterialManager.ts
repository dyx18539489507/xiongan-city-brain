import * as THREE from "three";
import {KTX2Loader} from "three/addons/loaders/KTX2Loader.js";

export type LaneMaterialKey =
  | "motor-primary"
  | "motor-secondary"
  | "motor-local"
  | "bicycle"
  | "pedestrian"
  | "shared";

export class MaterialManager {
  private readonly materials = new Map<string, THREE.Material>();
  private readonly textures = new Map<string, THREE.Texture>();
  private compressedAsphalt: THREE.CompressedTexture | null = null;

  async prepareCompressedTextures(renderer: THREE.WebGLRenderer): Promise<boolean> {
    const loader = new KTX2Loader()
      .setTranscoderPath("/assets/decoders/basis/")
      .detectSupport(renderer);
    try {
      const texture = await loader.loadAsync("/assets/3d/textures/k06_asphalt.ktx2");
      texture.name = "asphalt-color-ktx2";
      texture.wrapS = THREE.RepeatWrapping;
      texture.wrapT = THREE.RepeatWrapping;
      texture.anisotropy = Math.min(2, renderer.capabilities.getMaxAnisotropy());
      texture.colorSpace = THREE.SRGBColorSpace;
      this.compressedAsphalt = texture;
      this.textures.set(texture.name, texture);
      return true;
    } catch (error: unknown) {
      console.warn("KTX2 asphalt unavailable; using deterministic DataTexture fallback", error);
      return false;
    } finally {
      loader.dispose();
    }
  }

  lane(key: LaneMaterialKey): THREE.MeshStandardMaterial {
    const cached = this.materials.get(key);
    if (cached) return cached as THREE.MeshStandardMaterial;
    const color: Record<LaneMaterialKey, number> = {
      "motor-primary": 0x222829,
      "motor-secondary": 0x282e2f,
      "motor-local": 0x303536,
      bicycle: 0x3f5a4c,
      pedestrian: 0x77736b,
      shared: 0x4c534d,
    };
    const material = new THREE.MeshStandardMaterial({
      name: `lane-${key}`,
      color: color[key],
      roughness: key.startsWith("motor") ? 0.84 : 0.92,
      metalness: 0.02,
    });
    if (key.startsWith("motor")) {
      material.map = this.compressedAsphalt ?? this.surfaceTexture("asphalt-color", "color");
      material.normalMap = this.surfaceTexture("asphalt-normal", "normal");
      material.normalScale.set(0.26, 0.26);
      material.roughnessMap = this.surfaceTexture("asphalt-roughness", "roughness");
      material.aoMap = this.surfaceTexture("asphalt-ao", "ao");
      material.aoMapIntensity = 0.42;
    }
    this.materials.set(key, material);
    return material;
  }

  junction(): THREE.MeshStandardMaterial {
    return this.cachedStandard("junction", 0x272d2e, 0.88);
  }

  marking(): THREE.MeshBasicMaterial {
    const key = "marking";
    const cached = this.materials.get(key);
    if (cached) return cached as THREE.MeshBasicMaterial;
    const material = new THREE.MeshBasicMaterial({color: 0xe8e8dd, toneMapped: false});
    this.materials.set(key, material);
    return material;
  }

  crossingBase(): THREE.MeshStandardMaterial {
    return this.cachedStandard("crossing-base", 0x333839, 0.9);
  }

  ground(): THREE.MeshStandardMaterial {
    return this.cachedStandard("ground", 0x4b5b46, 1);
  }

  marker(): THREE.MeshBasicMaterial {
    const key = "controlled-marker";
    const cached = this.materials.get(key);
    if (cached) return cached as THREE.MeshBasicMaterial;
    const material = new THREE.MeshBasicMaterial({color: 0xffffff, toneMapped: false});
    this.materials.set(key, material);
    return material;
  }

  dispose(): void {
    this.materials.forEach((material) => material.dispose());
    this.textures.forEach((texture) => texture.dispose());
    this.materials.clear();
    this.textures.clear();
  }

  private cachedStandard(key: string, color: number, roughness: number): THREE.MeshStandardMaterial {
    const cached = this.materials.get(key);
    if (cached) return cached as THREE.MeshStandardMaterial;
    const material = new THREE.MeshStandardMaterial({name: key, color, roughness, metalness: 0});
    this.materials.set(key, material);
    return material;
  }

  private surfaceTexture(
    key: string,
    kind: "color" | "normal" | "roughness" | "ao",
  ): THREE.DataTexture {
    const cached = this.textures.get(key);
    if (cached instanceof THREE.DataTexture) return cached;
    const size = 64;
    const data = new Uint8Array(size * size * 4);
    let seed = 0x6d2b79f5;
    const random = () => {
      seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
      return seed / 0x1_0000_0000;
    };
    for (let index = 0; index < size * size; index += 1) {
      const offset = index * 4;
      const noise = random() - 0.5;
      if (kind === "normal") {
        data[offset] = Math.round(128 + noise * 20);
        data[offset + 1] = Math.round(128 + (random() - 0.5) * 20);
        data[offset + 2] = 250;
      } else if (kind === "color") {
        const value = Math.round(218 + noise * 26);
        data[offset] = value;
        data[offset + 1] = value;
        data[offset + 2] = Math.max(0, value - 3);
      } else {
        const base = kind === "roughness" ? 224 : 238;
        const value = Math.round(base + noise * (kind === "roughness" ? 28 : 18));
        data[offset] = value;
        data[offset + 1] = value;
        data[offset + 2] = value;
      }
      data[offset + 3] = 255;
    }
    const texture = new THREE.DataTexture(data, size, size, THREE.RGBAFormat);
    texture.name = key;
    texture.wrapS = THREE.RepeatWrapping;
    texture.wrapT = THREE.RepeatWrapping;
    texture.anisotropy = 2;
    if (kind === "color") texture.colorSpace = THREE.SRGBColorSpace;
    texture.needsUpdate = true;
    this.textures.set(key, texture);
    return texture;
  }
}
