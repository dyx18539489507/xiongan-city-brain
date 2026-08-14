import * as THREE from "three";
import {AssetManager} from "../assets/AssetManager";
import {VehiclePool, type VehicleModelDefinition} from "./VehiclePool";

type VehiclePreview = {
  label: string;
  definition: VehicleModelDefinition;
  color: number;
  z: number;
};

const PREVIEWS: VehiclePreview[] = [
  {
    label: "城市公交 · 11.8 m",
    definition: {
      asset: "/assets/3d/vehicles/urban-bus.optimized.glb",
      baseYawRad: Math.PI / 2,
      groundOffsetM: 0.02,
      dimensionsM: [11.8, 3.2, 2.5],
      wheelAxlesM: [3.8, -3.6],
      wheelRadiusM: 0.52,
    },
    color: 0x4d9eaa,
    z: -5.1,
  },
  {
    label: "城市物流卡车 · 8.2 m",
    definition: {
      asset: "/assets/3d/vehicles/urban-truck.optimized.glb",
      baseYawRad: Math.PI / 2,
      groundOffsetM: 0.02,
      dimensionsM: [8.2, 3.4, 2.5],
      wheelAxlesM: [2.65, -2.45, -3.35],
      wheelRadiusM: 0.5,
    },
    color: 0xd68846,
    z: 0,
  },
  {
    label: "末端配送车 · 5.6 m",
    definition: {
      asset: "/assets/3d/vehicles/delivery-van.optimized.glb",
      baseYawRad: Math.PI / 2,
      groundOffsetM: 0.02,
      dimensionsM: [5.6, 2.55, 2.15],
      wheelAxlesM: [1.8, -1.55],
      wheelRadiusM: 0.43,
    },
    color: 0x8d73c2,
    z: 4.6,
  },
];

/** Mount a disposable fixed-camera asset acceptance view for Playwright/manual QA. */
export async function mountVehicleAssetQa(): Promise<{
  models: number;
  triangles: number;
  calls: number;
}> {
  document.querySelector("[data-vehicle-asset-qa]")?.remove();
  const shell = document.createElement("section");
  shell.dataset.vehicleAssetQa = "true";
  shell.setAttribute("aria-label", "车辆资产视觉验收");
  Object.assign(shell.style, {
    position: "fixed",
    inset: "0",
    zIndex: "9999",
    overflow: "hidden",
    background: "#07131a",
    color: "#dcebf0",
    fontFamily: "Arial, sans-serif",
  });
  document.body.append(shell);

  const heading = document.createElement("div");
  Object.assign(heading.style, {
    position: "absolute",
    zIndex: "2",
    top: "32px",
    left: "42px",
    letterSpacing: "0.08em",
  });
  heading.innerHTML =
    "<strong style='font-size:22px'>PROJECT-AUTHORED VEHICLE ASSETS</strong>" +
    "<div style='margin-top:7px;color:#83a3af;font-size:12px'>" +
    "独立轮廓 · PBR 材质 · 运行时轮组 · Blender 可导入 GLB</div>";
  shell.append(heading);

  const captions = document.createElement("div");
  Object.assign(captions.style, {
    position: "absolute",
    zIndex: "2",
    left: "42px",
    right: "42px",
    bottom: "28px",
    display: "grid",
    gridTemplateColumns: "repeat(3, 1fr)",
    gap: "16px",
    color: "#9db7c1",
    fontSize: "12px",
  });
  for (const [index, preview] of [...PREVIEWS].reverse().entries()) {
    const caption = document.createElement("div");
    caption.textContent = `${String(index + 1).padStart(2, "0")}  ${preview.label}`;
    caption.style.borderTop = "1px solid #26424d";
    caption.style.paddingTop = "9px";
    captions.append(caption);
  }
  shell.append(captions);

  const renderer = new THREE.WebGLRenderer({antialias: true, alpha: false});
  renderer.setPixelRatio(1);
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.08;
  shell.prepend(renderer.domElement);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x07131a);
  scene.fog = new THREE.Fog(0x07131a, 22, 54);
  const camera = new THREE.PerspectiveCamera(
    36,
    window.innerWidth / window.innerHeight,
    0.1,
    100,
  );
  camera.position.set(16.5, 11.8, 17.5);
  camera.lookAt(0, 1.0, 0);
  scene.add(new THREE.HemisphereLight(0xcce7ef, 0x1d302d, 1.9));
  const key = new THREE.DirectionalLight(0xfff1d7, 3.2);
  key.position.set(8, 15, 10);
  scene.add(key);
  const rim = new THREE.DirectionalLight(0x54b9d0, 1.4);
  rim.position.set(-12, 6, -8);
  scene.add(rim);

  const ground = new THREE.Mesh(
    new THREE.PlaneGeometry(42, 30),
    new THREE.MeshStandardMaterial({color: 0x14262d, roughness: 0.9, metalness: 0.04}),
  );
  ground.rotation.x = -Math.PI / 2;
  ground.position.y = -0.02;
  scene.add(ground);
  const grid = new THREE.GridHelper(42, 42, 0x31515c, 0x203740);
  grid.position.y = 0.001;
  scene.add(grid);

  const assets = new AssetManager(renderer);
  for (const preview of PREVIEWS) {
    const pool = new VehiclePool(1, [100, 300], preview.definition, assets);
    await pool.initialize(preview.definition.asset);
    const vehicle = pool.acquire(preview.label);
    vehicle.root.position.z = preview.z;
    vehicle.root.rotation.y = -0.10;
    for (const material of vehicle.paintMaterials) material.color.setHex(preview.color);
    for (const material of vehicle.headlightMaterials) material.emissiveIntensity = 1.8;
    for (const material of vehicle.taillightMaterials) material.emissiveIntensity = 0.7;
    scene.add(pool.root);
  }
  renderer.render(scene, camera);
  return {
    models: PREVIEWS.length,
    triangles: renderer.info.render.triangles,
    calls: renderer.info.render.calls,
  };
}
