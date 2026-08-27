import {describe, expect, it} from "vitest";
import {buildMapTileRetryUrls} from "./mapTileRetry";

describe("map tile retry URLs", () => {
  it("tries every AutoNavi subdomain before the fallback provider", () => {
    const primary = "https://webrd01.is.autonavi.com/tile/16/25032/53869";
    const fallback = "https://map.geoq.cn/tile/16/25032/53869";

    expect(buildMapTileRetryUrls(primary, fallback)).toEqual([
      "https://webrd01.is.autonavi.com/tile/16/25032/53869",
      "https://webrd02.is.autonavi.com/tile/16/25032/53869",
      "https://webrd03.is.autonavi.com/tile/16/25032/53869",
      "https://webrd04.is.autonavi.com/tile/16/25032/53869",
      fallback,
    ]);
  });

  it("keeps the assigned subdomain first without duplicating it", () => {
    const urls = buildMapTileRetryUrls(
      "https://webrd03.is.autonavi.com/tile/16/25032/53869",
      "https://map.geoq.cn/tile/16/25032/53869",
    );

    expect(urls.map((url) => url.match(/webrd0([1-4])/)?.[1] ?? "fallback")).toEqual([
      "3",
      "1",
      "2",
      "4",
      "fallback",
    ]);
  });
});
