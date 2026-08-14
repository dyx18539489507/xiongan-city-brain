import {describe, expect, it} from "vitest";
import {DemoDirector, type DemoCue} from "./DemoDirector";

describe("DemoDirector", () => {
  it("fires ordered cues once and stops at the declared duration", () => {
    const cues: DemoCue[] = [
      {atS: 0, label: "overview", view: "overview"},
      {atS: 5, label: "corridor", view: "corridor"},
    ];
    const fired: string[] = [];
    const director = new DemoDirector(
      {id: "test", durationS: 10, cues},
      (cue) => fired.push(cue.label),
    );
    expect(director.start().label).toBe("overview");
    director.update(4);
    expect(fired).toEqual(["overview"]);
    director.update(2);
    expect(fired).toEqual(["overview", "corridor"]);
    expect(director.update(10).running).toBe(false);
  });
});
