import {describe, expect, it} from "vitest";
import type {ScenarioDraft} from "./api";
import {
  draftNetworkBounds,
  draftSelectionBounds,
  readScenarioFactorySession,
  scenarioFactorySessionStorageKey,
  selectScenarioFactoryRestoreTarget,
  writeScenarioFactorySession,
} from "./scenarioFactoryPersistence";

describe("scenario factory persistence", () => {
  it("restores the selected and generated network bounds from an OSM draft", () => {
    const draft = {
      source: {
        bbox: {west: 115.91, south: 39.05, east: 115.92, north: 39.06},
        network_context: {network_bbox: {west: 115.9, south: 39.04, east: 115.93, north: 39.07}},
      },
    } as unknown as ScenarioDraft;

    expect(draftSelectionBounds(draft)).toEqual({west: 115.91, south: 39.05, east: 115.92, north: 39.06});
    expect(draftNetworkBounds(draft)).toEqual({west: 115.9, south: 39.04, east: 115.93, north: 39.07});
  });

  it("round-trips the exact map and selection state", () => {
    let stored = "";
    const storage = {
      getItem: (key: string) => key === scenarioFactorySessionStorageKey ? stored : null,
      setItem: (key: string, value: string) => {if (key === scenarioFactorySessionStorageKey) stored = value;},
    };
    const state = {
      buildId: "build-1",
      draftId: "draft-1",
      sourceType: "osm_bbox" as const,
      bbox: {west: 115.91, south: 39.05, east: 115.92, north: 39.06},
      selectedIntersectionIds: ["junction-1"],
      displayName: "恢复场景",
      mapView: {center: {lat: 39.055, lon: 115.915}, zoom: 18},
    };

    writeScenarioFactorySession(storage, state);
    expect(readScenarioFactorySession(storage)).toEqual(state);
  });

  it("restores a parsed draft without replacing it with an older completed build on remount", () => {
    let stored = "";
    const storage = {
      getItem: (key: string) => key === scenarioFactorySessionStorageKey ? stored : null,
      setItem: (key: string, value: string) => {if (key === scenarioFactorySessionStorageKey) stored = value;},
    };
    const parsedDraftState = {
      draftId: "draft-parsed-without-build",
      sourceType: "osm_bbox" as const,
      bbox: {west: 115.908019, south: 39.052553, east: 115.923998, north: 39.06345},
      selectedIntersectionIds: ["junction-1", "junction-2"],
      displayName: "雄安 OSM 框选场景",
      mapView: {center: {lat: 39.0580015, lon: 115.9160085}, zoom: 16},
    };

    writeScenarioFactorySession(storage, parsedDraftState);
    const remountedSession = readScenarioFactorySession(storage);

    expect(remountedSession).toEqual(parsedDraftState);
    expect(selectScenarioFactoryRestoreTarget(remountedSession)).toEqual({
      kind: "draft",
      draftId: "draft-parsed-without-build",
      buildId: null,
    });
  });

  it("uses backend build fallback only when the browser session does not exist", () => {
    expect(selectScenarioFactoryRestoreTarget(null)).toEqual({kind: "fallback"});
    expect(selectScenarioFactoryRestoreTarget({
      sourceType: "osm_bbox",
      bbox: null,
      selectedIntersectionIds: [],
      displayName: "雄安自定义路网场景",
      mapView: null,
    })).toEqual({kind: "session"});
  });
});
