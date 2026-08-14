import * as THREE from "three";
import {AssetManager} from "../assets/AssetManager";
import type {CoordinateService} from "../core/CoordinateService";

const HERO_URL = "/assets/k06/k06-hero.glb";
const HERO_JUNCTION_ID = "11122023451";

export type HeroContextStats = {
  loaded: boolean;
  meshes: number;
  triangles: number;
};

export function isHeroArchitectureName(name: string): boolean {
  return name.startsWith("K06_Architecture_");
}

function triangleCount(root: THREE.Object3D): number {
  let triangles = 0;
  root.traverse((object) => {
    if (!(object instanceof THREE.Mesh)) return;
    triangles += object.geometry.index
      ? object.geometry.index.count / 3
      : object.geometry.getAttribute("position").count / 3;
  });
  return Math.round(triangles);
}

/**
 * Lazy A-class context for the K06 hero view. Only authored architecture is
 * retained from the Blender scene; SUMO-generated road/TLS geometry remains
 * the sole road truth. The ordinary OSM massing can be hidden while this local
 * context is active to prevent overlapping buildings.
 */
export class HeroContextManager {
  readonly root = new THREE.Group();
  readonly junctionId = HERO_JUNCTION_ID;
  stats: HeroContextStats = {loaded: false, meshes: 0, triangles: 0};

  private readonly assets: AssetManager;
  private pending: Promise<boolean> | null = null;
  private requestedActive = false;

  constructor(
    coordinates: CoordinateService,
    renderer: THREE.WebGLRenderer,
    junction: {position: {x: number; y: number}},
  ) {
    this.assets = new AssetManager(renderer);
    this.root.name = "K06HeroArchitecture";
    const world = coordinates.sumoToWorld(junction.position.x, junction.position.y, 0);
    this.root.position.set(world.x, world.y, world.z);
    this.root.visible = false;
  }

  async setActive(active: boolean): Promise<boolean> {
    this.requestedActive = active;
    if (!active) {
      this.root.visible = false;
      return false;
    }
    if (!this.stats.loaded) await this.load();
    this.root.visible = this.requestedActive && this.stats.loaded;
    return this.root.visible;
  }

  dispose(): void {
    const textures = new Set<THREE.Texture>();
    this.root.traverse((object) => {
      if (!(object instanceof THREE.Mesh)) return;
      object.geometry.dispose();
      const materials = Array.isArray(object.material) ? object.material : [object.material];
      for (const material of materials) {
        for (const value of Object.values(material)) {
          if (value instanceof THREE.Texture) textures.add(value);
        }
        material.dispose();
      }
    });
    textures.forEach((texture) => texture.dispose());
    this.root.clear();
    this.root.removeFromParent();
    this.assets.dispose();
    this.pending = null;
  }

  private load(): Promise<boolean> {
    if (this.pending) return this.pending;
    this.pending = this.assets.loadTemplate(HERO_URL).then(
      (template) => {
        const architecture = template.children
          .filter((child) => isHeroArchitectureName(child.name))
          .map((child) => child.clone(true));
        for (const child of architecture) {
          child.traverse((object) => {
            if (object instanceof THREE.Mesh) {
              object.castShadow = true;
              object.receiveShadow = true;
            }
          });
          this.root.add(child);
        }
        this.stats = {
          loaded: architecture.length > 0,
          meshes: architecture.length,
          triangles: triangleCount(this.root),
        };
        return this.stats.loaded;
      },
      (error: unknown) => {
        console.warn("K06 hero architecture failed to load; keeping OSM massing", error);
        return false;
      },
    );
    return this.pending;
  }
}
