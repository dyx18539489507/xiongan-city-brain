import * as THREE from "three";
import {LightingManager, type LightingMode} from "./LightingManager";

export type WeatherMode = LightingMode;

type MaterialBaseline = {
  material: THREE.MeshStandardMaterial;
  color: THREE.Color;
  emissive: THREE.Color;
  emissiveIntensity: number;
  roughness: number;
  metalness: number;
};

type WeatherProfile = {
  skyTop: number;
  skyBottom: number;
  fogColor: number;
  fogNear: number;
  fogFar: number;
  roadDarkening: number;
  roadRoughness: number | null;
};

const PROFILES: Record<WeatherMode, WeatherProfile> = {
  clear: {skyTop: 0x5d91b0, skyBottom: 0xd7ddd2, fogColor: 0xaebfbd, fogNear: 3000, fogFar: 7200, roadDarkening: 1, roadRoughness: null},
  cloudy: {skyTop: 0x718895, skyBottom: 0xc4cbca, fogColor: 0x9ca9aa, fogNear: 2100, fogFar: 5600, roadDarkening: 0.9, roadRoughness: null},
  dusk: {skyTop: 0x3f5074, skyBottom: 0xd49278, fogColor: 0x6f6d72, fogNear: 2200, fogFar: 5200, roadDarkening: 0.72, roadRoughness: null},
  night: {skyTop: 0x081426, skyBottom: 0x23354a, fogColor: 0x111d2a, fogNear: 1700, fogFar: 4300, roadDarkening: 0.72, roadRoughness: null},
  rain: {skyTop: 0x445863, skyBottom: 0x879395, fogColor: 0x65747a, fogNear: 720, fogFar: 2500, roadDarkening: 0.78, roadRoughness: 0.36},
  fog: {skyTop: 0xbfc8c8, skyBottom: 0xd9dcda, fogColor: 0xc6cdcb, fogNear: 180, fogFar: 1800, roadDarkening: 0.83, roadRoughness: null},
};

function gradientTexture(top: number, bottom: number): THREE.DataTexture {
  const height = 256;
  const data = new Uint8Array(height * 4);
  const topColor = new THREE.Color(top);
  const bottomColor = new THREE.Color(bottom);
  const mixed = new THREE.Color();
  for (let y = 0; y < height; y += 1) {
    const ratio = y / (height - 1);
    mixed.lerpColors(topColor, bottomColor, ratio);
    const offset = y * 4;
    data[offset] = Math.round(mixed.r * 255);
    data[offset + 1] = Math.round(mixed.g * 255);
    data[offset + 2] = Math.round(mixed.b * 255);
    data[offset + 3] = 255;
  }
  const texture = new THREE.DataTexture(data, 1, height, THREE.RGBAFormat);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.needsUpdate = true;
  return texture;
}

function isRoadMaterial(name: string): boolean {
  return name.startsWith("lane-") ||
    name === "junction" ||
    name === "crossing-base" ||
    name === "ground";
}

export class WeatherManager {
  readonly rainDropCount = 560;
  private readonly backgrounds = new Map<WeatherMode, THREE.DataTexture>();
  private readonly baselines = new Map<THREE.MeshStandardMaterial, MaterialBaseline>();
  private readonly rainGeometry: THREE.BufferGeometry;
  private readonly rainMaterial: THREE.LineBasicMaterial;
  private readonly rain: THREE.LineSegments;
  private readonly rainPositions: THREE.BufferAttribute;
  private currentMode: WeatherMode = "clear";

  constructor(
    private readonly scene: THREE.Scene,
    private readonly lighting: LightingManager,
  ) {
    for (const [mode, profile] of Object.entries(PROFILES) as Array<[WeatherMode, WeatherProfile]>) {
      this.backgrounds.set(mode, gradientTexture(profile.skyTop, profile.skyBottom));
    }
    const positions = new Float32Array(this.rainDropCount * 6);
    let state = 0x5f3759df;
    const random = () => {
      state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
      return state / 0x1_0000_0000;
    };
    for (let index = 0; index < this.rainDropCount; index += 1) {
      const offset = index * 6;
      const x = (random() - 0.5) * 90;
      const y = (random() - 0.5) * 42;
      const z = (random() - 0.5) * 90;
      positions[offset] = x;
      positions[offset + 1] = y;
      positions[offset + 2] = z;
      positions[offset + 3] = x - 0.18;
      positions[offset + 4] = y - 1.25;
      positions[offset + 5] = z + 0.08;
    }
    this.rainPositions = new THREE.BufferAttribute(positions, 3);
    this.rainGeometry = new THREE.BufferGeometry();
    this.rainGeometry.setAttribute("position", this.rainPositions);
    this.rainMaterial = new THREE.LineBasicMaterial({
      color: 0xc9e7ef,
      transparent: true,
      opacity: 0.42,
      depthWrite: false,
    });
    this.rain = new THREE.LineSegments(this.rainGeometry, this.rainMaterial);
    this.rain.name = "LocalRainField";
    this.rain.frustumCulled = false;
    this.rain.visible = false;
    this.scene.add(this.rain);
    this.apply("clear");
  }

  captureMaterials(root: THREE.Object3D): void {
    root.traverse((object) => {
      if (!(object instanceof THREE.Mesh)) return;
      const materials = Array.isArray(object.material) ? object.material : [object.material];
      for (const material of materials) {
        if (!(material instanceof THREE.MeshStandardMaterial) || this.baselines.has(material)) continue;
        this.baselines.set(material, {
          material,
          color: material.color.clone(),
          emissive: material.emissive.clone(),
          emissiveIntensity: material.emissiveIntensity,
          roughness: material.roughness,
          metalness: material.metalness,
        });
      }
    });
    this.applyMaterials(this.currentMode);
  }

  apply(mode: WeatherMode): void {
    this.currentMode = mode;
    const profile = PROFILES[mode];
    this.scene.background = this.backgrounds.get(mode) ?? null;
    this.scene.fog = new THREE.Fog(profile.fogColor, profile.fogNear, profile.fogFar);
    this.lighting.apply(mode);
    this.rain.visible = mode === "rain";
    this.applyMaterials(mode);
  }

  update(deltaSeconds: number, camera: THREE.Camera): void {
    if (!this.rain.visible) return;
    this.rain.position.set(camera.position.x, Math.max(18, camera.position.y - 12), camera.position.z);
    const values = this.rainPositions.array as Float32Array;
    const fall = Math.min(deltaSeconds, 0.1) * 34;
    for (let index = 0; index < this.rainDropCount; index += 1) {
      const offset = index * 6;
      values[offset + 1] -= fall;
      values[offset + 4] -= fall;
      if (values[offset + 4] < -21) {
        values[offset + 1] += 42;
        values[offset + 4] += 42;
      }
    }
    this.rainPositions.needsUpdate = true;
  }

  mode(): WeatherMode {
    return this.currentMode;
  }

  dispose(): void {
    this.rain.removeFromParent();
    this.rainGeometry.dispose();
    this.rainMaterial.dispose();
    this.backgrounds.forEach((texture) => texture.dispose());
    this.backgrounds.clear();
    this.baselines.clear();
  }

  private applyMaterials(mode: WeatherMode): void {
    const profile = PROFILES[mode];
    for (const baseline of this.baselines.values()) {
      const {material} = baseline;
      material.color.copy(baseline.color);
      material.emissive.copy(baseline.emissive);
      material.emissiveIntensity = baseline.emissiveIntensity;
      material.roughness = baseline.roughness;
      material.metalness = baseline.metalness;
      if (isRoadMaterial(material.name)) {
        material.color.multiplyScalar(profile.roadDarkening);
        if (profile.roadRoughness !== null) {
          material.roughness = profile.roadRoughness;
          material.metalness = Math.max(material.metalness, 0.09);
        }
      }
      if (material.name === "building-windows") {
        if (mode === "night") {
          material.emissive.setHex(0xffc56d);
          material.emissiveIntensity = 1.6;
        } else if (mode === "dusk") {
          material.emissive.setHex(0xc87944);
          material.emissiveIntensity = 0.72;
        }
      }
      if (material.name === "street-light-head") {
        if (mode === "night" || mode === "rain" || mode === "fog") {
          material.emissive.setHex(0xffd08a);
          material.emissiveIntensity = mode === "night" ? 2.8 : 1.5;
        }
      }
      material.needsUpdate = true;
    }
  }
}
