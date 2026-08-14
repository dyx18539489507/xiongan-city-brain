import * as THREE from "three";

export type LightingMode = "clear" | "cloudy" | "dusk" | "night" | "rain" | "fog";

type LightingProfile = {
  sky: number;
  ground: number;
  hemisphereIntensity: number;
  sun: number;
  sunIntensity: number;
  sunPosition: [number, number, number];
  exposure: number;
};

const PROFILES: Record<LightingMode, LightingProfile> = {
  clear: {
    sky: 0xe9f4f5,
    ground: 0x354032,
    hemisphereIntensity: 1.25,
    sun: 0xfff2d7,
    sunIntensity: 1.85,
    sunPosition: [-900, 1800, 800],
    exposure: 0.92,
  },
  cloudy: {
    sky: 0xdce6e8,
    ground: 0x465047,
    hemisphereIntensity: 1.05,
    sun: 0xdbe5e8,
    sunIntensity: 0.72,
    sunPosition: [-800, 1500, 700],
    exposure: 0.82,
  },
  dusk: {
    sky: 0x7886a5,
    ground: 0x2d2523,
    hemisphereIntensity: 0.72,
    sun: 0xff9460,
    sunIntensity: 1.08,
    sunPosition: [-1200, 360, 620],
    exposure: 0.74,
  },
  night: {
    // Moonlit visibility is intentionally brighter than physical darkness so
    // roads and participants remain readable on a competition projector.
    sky: 0x8dadd0,
    ground: 0x27384c,
    hemisphereIntensity: 1.35,
    sun: 0xa8c4dc,
    sunIntensity: 0.38,
    sunPosition: [-900, 1100, 800],
    exposure: 0.96,
  },
  rain: {
    sky: 0xafc0c8,
    ground: 0x3b4850,
    hemisphereIntensity: 1.25,
    sun: 0xd1dde1,
    sunIntensity: 0.62,
    sunPosition: [-850, 1250, 760],
    exposure: 0.9,
  },
  fog: {
    sky: 0xd8dddd,
    ground: 0x696f69,
    hemisphereIntensity: 0.95,
    sun: 0xf1eee7,
    sunIntensity: 0.5,
    sunPosition: [-750, 1200, 650],
    exposure: 0.8,
  },
};

export class LightingManager {
  readonly hemisphere = new THREE.HemisphereLight();
  readonly sun = new THREE.DirectionalLight();

  constructor(
    private readonly scene: THREE.Scene,
    private readonly renderer: Pick<THREE.WebGLRenderer, "toneMappingExposure">,
  ) {
    this.hemisphere.name = "EnvironmentHemisphereLight";
    this.sun.name = "EnvironmentSun";
    this.sun.castShadow = true;
    this.sun.shadow.mapSize.set(512, 512);
    this.sun.shadow.camera.near = 20;
    this.sun.shadow.camera.far = 3200;
    this.sun.shadow.camera.left = -140;
    this.sun.shadow.camera.right = 140;
    this.sun.shadow.camera.top = 140;
    this.sun.shadow.camera.bottom = -140;
    this.sun.shadow.bias = -0.00025;
    this.scene.add(this.hemisphere, this.sun);
    this.apply("clear");
  }

  apply(mode: LightingMode): void {
    const profile = PROFILES[mode];
    this.hemisphere.color.setHex(profile.sky);
    this.hemisphere.groundColor.setHex(profile.ground);
    this.hemisphere.intensity = profile.hemisphereIntensity;
    this.sun.color.setHex(profile.sun);
    this.sun.intensity = profile.sunIntensity;
    this.sun.position.set(...profile.sunPosition);
    this.renderer.toneMappingExposure = profile.exposure;
  }

  dispose(): void {
    this.hemisphere.removeFromParent();
    this.sun.removeFromParent();
  }
}
