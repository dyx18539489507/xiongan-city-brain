import * as THREE from "three";
import {DRACOLoader} from "three/addons/loaders/DRACOLoader.js";
import {GLTFLoader} from "three/addons/loaders/GLTFLoader.js";
import {KTX2Loader} from "three/addons/loaders/KTX2Loader.js";

export type AssetManagerSnapshot = {
  requested: number;
  loaded: number;
  failed: number;
};

export class AssetManager {
  private readonly loader = new GLTFLoader();
  private readonly draco = new DRACOLoader();
  private readonly ktx2: KTX2Loader | null;
  private readonly cache = new Map<string, Promise<THREE.Group>>();
  private loaded = 0;
  private failed = 0;

  constructor(renderer?: THREE.WebGLRenderer) {
    this.draco.setDecoderPath("/assets/decoders/draco/");
    this.loader.setDRACOLoader(this.draco);
    this.ktx2 = renderer
      ? new KTX2Loader()
          .setTranscoderPath("/assets/decoders/basis/")
          .detectSupport(renderer)
      : null;
    if (this.ktx2) this.loader.setKTX2Loader(this.ktx2);
  }

  loadTemplate(url: string): Promise<THREE.Group> {
    const cached = this.cache.get(url);
    if (cached) return cached;
    const pending = this.loader.loadAsync(url).then(
      (gltf) => {
        this.loaded += 1;
        gltf.scene.name = `AssetTemplate:${url}`;
        return gltf.scene;
      },
      (error: unknown) => {
        this.failed += 1;
        this.cache.delete(url);
        throw error;
      },
    );
    this.cache.set(url, pending);
    return pending;
  }

  snapshot(): AssetManagerSnapshot {
    return {requested: this.cache.size, loaded: this.loaded, failed: this.failed};
  }

  dispose(): void {
    this.draco.dispose();
    this.ktx2?.dispose();
    this.cache.clear();
  }
}
