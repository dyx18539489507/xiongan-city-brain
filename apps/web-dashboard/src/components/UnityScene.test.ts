import {describe, expect, it} from "vitest";
import {emptyDigitalTwinState} from "../3d/network/DigitalTwinStore";
import {resolveUnityFrameSource, shouldForwardUnitySnapshot} from "./UnityScene";

describe("resolveUnityFrameSource", () => {
  it("passes the generated scenario identity to the reusable Unity build", () => {
    expect(resolveUnityFrameSource("xiongan osm/01", ""))
      .toBe("/unity/index.html?scenarioId=xiongan+osm%2F01&build=20260828-0327");
  });

  it("preserves the optional performance diagnostics flag", () => {
    expect(resolveUnityFrameSource("generated-osm", "?perf=1"))
      .toBe("/unity/index.html?scenarioId=generated-osm&build=20260828-0327&perf=1");
  });
});

describe("shouldForwardUnitySnapshot", () => {
  it("only forwards initialized traffic belonging to the loaded Unity scene", () => {
    const matching = {...emptyDigitalTwinState, initialized: true, experimentId: "exp-1", scenarioId: "generated-osm"};
    expect(shouldForwardUnitySnapshot(matching, "generated-osm", "exp-1")).toBe(true);
    expect(shouldForwardUnitySnapshot({...matching, scenarioId: "other"}, "generated-osm", "exp-1")).toBe(false);
    expect(shouldForwardUnitySnapshot({...matching, initialized: false}, "generated-osm", "exp-1")).toBe(false);
    expect(shouldForwardUnitySnapshot(matching, "generated-osm", "exp-old")).toBe(false);
    expect(shouldForwardUnitySnapshot(matching, "generated-osm", null)).toBe(false);
  });
});
