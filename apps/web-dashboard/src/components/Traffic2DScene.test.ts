import {describe, expect, it, vi} from "vitest";
import {createCameraSyncBus} from "./Traffic2DScene";

describe("paired 2D camera synchronization", () => {
  it("publishes a camera pose only to the opposite map", () => {
    const bus = createCameraSyncBus();
    const baseline = vi.fn();
    const candidate = vi.fn();
    bus.subscribe("baseline", baseline);
    bus.subscribe("candidate", candidate);
    const pose = {centerX: 120, centerY: 240, scale: 1.75};

    bus.publish("baseline", pose);

    expect(baseline).not.toHaveBeenCalled();
    expect(candidate).toHaveBeenCalledOnce();
    expect(candidate).toHaveBeenCalledWith(pose);
    expect(bus.currentFor("candidate")).toEqual(pose);
    expect(bus.currentFor("baseline")).toBeNull();
  });

  it("stops updating a map after it unsubscribes", () => {
    const bus = createCameraSyncBus();
    const candidate = vi.fn();
    const unsubscribe = bus.subscribe("candidate", candidate);
    unsubscribe();

    bus.publish("baseline", {centerX: 1, centerY: 2, scale: 3});

    expect(candidate).not.toHaveBeenCalled();
  });
});
