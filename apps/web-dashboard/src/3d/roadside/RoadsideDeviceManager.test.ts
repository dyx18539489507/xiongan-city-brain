import {describe, expect, it} from "vitest";
import {CoordinateService} from "../core/CoordinateService";
import type {SceneJunction, SceneRoadsideDevice} from "../scene/types";
import {RoadsideDeviceManager} from "./RoadsideDeviceManager";

const coordinates = new CoordinateService({
  units: "m",
  projection: "+proj=utm +zone=50",
  utmZone: 50,
  northernHemisphere: true,
  netOffset: {x: 0, y: 0},
  worldOriginSumo: {x: 0, y: 0},
});
const junction: SceneJunction = {
  sceneId: "junction:j0",
  sumoJunctionId: "j0",
  junctionType: "traffic_light",
  position: {x: 5, y: 5},
  shape: [],
  controlled: true,
  displayId: "K01",
  displayName: "K01",
  role: "core_corridor",
};
function device(deviceId: string, deviceType: string): SceneRoadsideDevice {
  return {
    deviceId,
    deviceType,
    position: {x: 2, y: 3},
    status: "modeled_asset",
    managedJunctions: ["j0"],
    communicationStatus: "runtime_unbound",
    provenance: "engineering_model_from_controlled_junction_and_sumo_lane",
  };
}

describe("RoadsideDeviceManager", () => {
  it("batches modeled RSUs/cameras and keeps analysis coverage optional", () => {
    const manager = new RoadsideDeviceManager(
      coordinates,
      [device("rsu:j0", "rsu"), device("camera:j0", "camera")],
      [junction],
    );
    expect(manager.stats.devices).toBe(2);
    expect(manager.stats.rsus).toBe(1);
    expect(manager.stats.cameras).toBe(1);
    expect(manager.stats.runtimeBound).toBe(0);
    expect(manager.analysisRoot.visible).toBe(false);
    manager.setAnalysisVisible(true);
    expect(manager.analysisRoot.visible).toBe(true);
    manager.dispose();
  });
});
