import {describe, expect, it} from "vitest";
import {congestionColor} from "./components/TopologyView";

describe("traffic state colors", () => {
  it("keeps unrun and congestion levels distinguishable", () => {
    expect(congestionColor(null)).toBe("#54717f");
    expect(congestionColor(0.2)).toBe("#35d5b3");
    expect(congestionColor(0.7)).toBe("#e7ba63");
    expect(congestionColor(0.9)).toBe("#ff8b5c");
  });
});

