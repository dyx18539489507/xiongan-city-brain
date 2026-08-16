import {describe, expect, it} from "vitest";
import {classifyLaneTraffic, type LaneTrafficInput} from "./trafficState";

const base: LaneTrafficInput = {
  vehicleCount: 0,
  queueVehicleCount: 0,
  queueLengthM: 0,
  occupancy: 0,
  meanSpeedMS: 0,
  speedLimitMS: 13.9,
  laneLengthM: 160,
};

describe("classifyLaneTraffic", () => {
  it("keeps an empty zero-speed SUMO lane out of the severe state", () => {
    expect(classifyLaneTraffic(base)).toEqual({kind: "empty", pressure: 0});
  });

  it("does not call one slow isolated vehicle a traffic jam", () => {
    const result = classifyLaneTraffic({...base, vehicleCount: 1});
    expect(result.kind).toBe("free");
    expect(result.pressure).toBeLessThan(.35);
  });

  it("classifies a dense stopped queue as severe", () => {
    const result = classifyLaneTraffic({...base, vehicleCount: 11, queueVehicleCount: 9, queueLengthM: 105, occupancy: .78});
    expect(result.kind).toBe("severe");
  });

  it("does not let stale aggregate values keep an empty lane congested", () => {
    expect(classifyLaneTraffic({...base, queueLengthM: 80, occupancy: .66})).toEqual({kind: "empty", pressure: 0});
  });

  it("returns unknown for a malformed real-time sample", () => {
    expect(classifyLaneTraffic({...base, meanSpeedMS: Number.NaN})).toEqual({kind: "unknown", pressure: 0});
  });
});
