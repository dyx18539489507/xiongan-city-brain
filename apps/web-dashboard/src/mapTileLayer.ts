import * as L from "leaflet";
import {buildMapTileRetryUrls} from "./mapTileRetry";

export const primaryChineseMapTiles = "https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}";
export const mapTileAttemptTimeoutMs = 6_000;

export class RetryingTileLayer extends L.TileLayer {
  constructor(url: string, options: L.TileLayerOptions, private readonly onRetry: (attempt: number) => void) {
    super(url, options);
  }

  protected createTile(coords: L.Coords, done: L.DoneCallback): HTMLElement {
    const tile = document.createElement("img");
    const primaryUrl = this.getTileUrl(coords);
    const fallbackUrl = `https://map.geoq.cn/ArcGIS/rest/services/ChinaOnlineCommunity/MapServer/tile/${this._getZoomForUrl()}/${coords.y}/${coords.x}`;
    const retryUrls = buildMapTileRetryUrls(primaryUrl, fallbackUrl);
    let attempt = 0;
    let finished = false;
    let attemptTimer: number | null = null;

    tile.alt = "";
    tile.setAttribute("role", "presentation");
    if (this.options.crossOrigin || this.options.crossOrigin === "") tile.crossOrigin = this.options.crossOrigin === true ? "" : this.options.crossOrigin;
    if (this.options.referrerPolicy) tile.referrerPolicy = this.options.referrerPolicy === true ? "no-referrer" : this.options.referrerPolicy;

    const finish = (error?: Error) => {
      if (finished) return;
      finished = true;
      if (attemptTimer !== null) window.clearTimeout(attemptTimer);
      tile.onload = null;
      tile.onerror = null;
      done(error, tile);
    };

    const handleFailure = (attemptIndex: number) => {
      if (finished || attemptIndex !== attempt) return;
      attempt += 1;
      if (attempt < retryUrls.length) {
        this.onRetry(attempt);
        beginAttempt(attempt);
        return;
      }
      finish(new Error("在线地图瓦片加载失败"));
    };

    const beginAttempt = (attemptIndex: number) => {
      if (attemptTimer !== null) window.clearTimeout(attemptTimer);
      tile.onload = () => {
        if (attemptIndex === attempt) finish();
      };
      tile.onerror = () => handleFailure(attemptIndex);
      tile.src = retryUrls[attemptIndex];
      attemptTimer = window.setTimeout(() => handleFailure(attemptIndex), mapTileAttemptTimeoutMs);
    };

    beginAttempt(attempt);
    return tile;
  }
}

export function createRetryingChineseMapLayer(
  onRetry: (attempt: number) => void = () => undefined,
  options: L.TileLayerOptions = {},
): RetryingTileLayer {
  return new RetryingTileLayer(primaryChineseMapTiles, {
    subdomains: ["1", "2", "3", "4"],
    maxNativeZoom: 18,
    maxZoom: 20,
    keepBuffer: 4,
    referrerPolicy: "no-referrer",
    ...options,
  }, onRetry);
}
