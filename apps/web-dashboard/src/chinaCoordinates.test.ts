import {describe, expect, it} from "vitest";
import {gcj02ToWgs84, wgs84ToGcj02} from "./chinaCoordinates";

describe("Chinese basemap coordinates", () => {
  it("applies the expected offset inside China", () => {
    const converted = wgs84ToGcj02(116.397128, 39.916527);
    expect(converted.lon).toBeCloseTo(116.403372, 5);
    expect(converted.lat).toBeCloseTo(39.917931, 5);
  });

  it("round-trips Xiongan coordinates without shifting the selected OSM bbox", () => {
    const source = {lon: 115.916, lat: 39.058};
    const displayed = wgs84ToGcj02(source.lon, source.lat);
    const restored = gcj02ToWgs84(displayed.lon, displayed.lat);
    expect(restored.lon).toBeCloseTo(source.lon, 7);
    expect(restored.lat).toBeCloseTo(source.lat, 7);
  });
});
