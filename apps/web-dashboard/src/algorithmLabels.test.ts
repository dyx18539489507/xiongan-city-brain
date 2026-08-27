import {describe, expect, it} from "vitest";
import {algorithmLabel, algorithmOptionLabel, sortAlgorithms} from "./algorithmLabels";

describe("algorithmLabel", () => {
  it("shows every registered algorithm in Chinese", () => {
    expect(algorithmLabel("fixed-time")).toBe("固定配时控制");
    expect(algorithmLabel("actuated-control")).toBe("感应控制");
    expect(algorithmLabel("max-pressure")).toBe("最大压力控制");
    expect(algorithmLabel("coordinated-max-pressure")).toBe("协同最大压力控制");
  });

  it("orders algorithm choices from B0 through B3", () => {
    const unordered = [
      {name: "actuated-control"},
      {name: "coordinated-max-pressure"},
      {name: "fixed-time"},
      {name: "max-pressure"},
    ];
    expect(sortAlgorithms(unordered).map((item) => item.name)).toEqual([
      "fixed-time",
      "actuated-control",
      "max-pressure",
      "coordinated-max-pressure",
    ]);
    expect(algorithmOptionLabel("fixed-time")).toBe("B0 · 固定配时控制");
    expect(algorithmOptionLabel("coordinated-max-pressure")).toBe("B3 · 协同最大压力控制");
  });
});
