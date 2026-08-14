import {describe, expect, it} from "vitest";
import * as THREE from "three";
import {LightingManager} from "./LightingManager";
import {WeatherManager} from "./WeatherManager";

describe("WeatherManager", () => {
  it("applies reversible lighting, wet-road and night-emissive profiles", () => {
    const scene = new THREE.Scene();
    const renderer = {toneMappingExposure: 1};
    const lighting = new LightingManager(
      scene,
      renderer as Pick<THREE.WebGLRenderer, "toneMappingExposure">,
    );
    const weather = new WeatherManager(scene, lighting);
    const road = new THREE.MeshStandardMaterial({
      name: "lane-motor-primary",
      color: 0x808080,
      roughness: 0.84,
    });
    const windows = new THREE.MeshStandardMaterial({
      name: "building-windows",
      emissive: 0x010101,
      emissiveIntensity: 0.2,
    });
    const root = new THREE.Group();
    root.add(
      new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), road),
      new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), windows),
    );
    weather.captureMaterials(root);

    weather.apply("rain");
    expect(weather.mode()).toBe("rain");
    expect(road.roughness).toBeCloseTo(0.36);
    expect(road.color.getHex()).toBeLessThan(0x808080);
    expect(renderer.toneMappingExposure).toBeCloseTo(0.9);

    weather.apply("night");
    expect(windows.emissiveIntensity).toBeCloseTo(1.6);
    expect(scene.fog).toBeInstanceOf(THREE.Fog);

    weather.apply("clear");
    expect(road.roughness).toBeCloseTo(0.84);
    expect(road.color.getHex()).toBe(0x808080);
    expect(windows.emissiveIntensity).toBeCloseTo(0.2);
    weather.dispose();
    lighting.dispose();
  });
});
