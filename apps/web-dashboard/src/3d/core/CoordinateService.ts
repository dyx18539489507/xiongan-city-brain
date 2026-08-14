export type Point2 = {x: number; y: number};
export type WorldPoint = {x: number; y: number; z: number};
export type LonLat = {lon: number; lat: number};

export type SceneCoordinateSystem = {
  units: "m" | string;
  projection: string;
  utmZone: number;
  northernHemisphere: boolean;
  netOffset: Point2;
  worldOriginSumo: Point2;
};

const WGS84_A = 6_378_137;
const WGS84_ECC_SQUARED = 0.00669438;
const UTM_SCALE = 0.9996;

function radians(degrees: number): number {
  return (degrees * Math.PI) / 180;
}

function degrees(value: number): number {
  return (value * 180) / Math.PI;
}

function normalizeRadians(value: number): number {
  const full = Math.PI * 2;
  return ((value + Math.PI) % full + full) % full - Math.PI;
}

/**
 * The only supported SUMO ↔ Three.js transform.
 *
 * SUMO X/Y are east/north meters. Three uses X/east, Y/up and -Z/north.
 * A floating origin keeps the two-kilometre scene numerically stable.
 */
export class CoordinateService {
  constructor(readonly definition: SceneCoordinateSystem) {
    if (definition.units !== "m") {
      throw new Error(`Unsupported scene unit: ${definition.units}`);
    }
    if (definition.utmZone < 1 || definition.utmZone > 60) {
      throw new Error(`Invalid UTM zone: ${definition.utmZone}`);
    }
  }

  sumoToWorld(x: number, y: number, height = 0): WorldPoint {
    return {
      x: x - this.definition.worldOriginSumo.x,
      y: height,
      z: this.definition.worldOriginSumo.y - y,
    };
  }

  worldToSumo(x: number, z: number): Point2 {
    return {
      x: x + this.definition.worldOriginSumo.x,
      y: this.definition.worldOriginSumo.y - z,
    };
  }

  sumoAngleToThree(angleDegrees: number): number {
    return normalizeRadians(radians(-angleDegrees));
  }

  worldAngleToSumo(yawRadians: number): number {
    return ((degrees(-yawRadians) % 360) + 360) % 360;
  }

  sumoToLonLat(x: number, y: number): LonLat {
    const easting = x - this.definition.netOffset.x;
    const northing = y - this.definition.netOffset.y;
    return this.utmToLonLat(easting, northing);
  }

  lonLatToSumo(lon: number, lat: number): Point2 {
    const projected = this.lonLatToUtm(lon, lat);
    return {
      x: projected.x + this.definition.netOffset.x,
      y: projected.y + this.definition.netOffset.y,
    };
  }

  private lonLatToUtm(lon: number, lat: number): Point2 {
    const latitude = radians(lat);
    const longitude = radians(lon);
    const longitudeOrigin = radians((this.definition.utmZone - 1) * 6 - 177);
    const eccentricityPrime =
      WGS84_ECC_SQUARED / (1 - WGS84_ECC_SQUARED);
    const n =
      WGS84_A /
      Math.sqrt(1 - WGS84_ECC_SQUARED * Math.sin(latitude) ** 2);
    const t = Math.tan(latitude) ** 2;
    const c = eccentricityPrime * Math.cos(latitude) ** 2;
    const a = Math.cos(latitude) * (longitude - longitudeOrigin);
    const m =
      WGS84_A *
      ((1 - WGS84_ECC_SQUARED / 4 -
        (3 * WGS84_ECC_SQUARED ** 2) / 64 -
        (5 * WGS84_ECC_SQUARED ** 3) / 256) *
        latitude -
        ((3 * WGS84_ECC_SQUARED) / 8 +
          (3 * WGS84_ECC_SQUARED ** 2) / 32 +
          (45 * WGS84_ECC_SQUARED ** 3) / 1024) *
          Math.sin(2 * latitude) +
        ((15 * WGS84_ECC_SQUARED ** 2) / 256 +
          (45 * WGS84_ECC_SQUARED ** 3) / 1024) *
          Math.sin(4 * latitude) -
        ((35 * WGS84_ECC_SQUARED ** 3) / 3072) *
          Math.sin(6 * latitude));
    const easting =
      UTM_SCALE *
        n *
        (a +
          ((1 - t + c) * a ** 3) / 6 +
          ((5 - 18 * t + t ** 2 + 72 * c - 58 * eccentricityPrime) *
            a ** 5) /
            120) +
      500_000;
    let northing =
      UTM_SCALE *
      (m +
        n *
          Math.tan(latitude) *
          (a ** 2 / 2 +
            ((5 - t + 9 * c + 4 * c ** 2) * a ** 4) / 24 +
            ((61 - 58 * t + t ** 2 + 600 * c - 330 * eccentricityPrime) *
              a ** 6) /
              720));
    if (!this.definition.northernHemisphere) northing += 10_000_000;
    return {x: easting, y: northing};
  }

  private utmToLonLat(easting: number, northing: number): LonLat {
    const eccentricityPrime =
      WGS84_ECC_SQUARED / (1 - WGS84_ECC_SQUARED);
    const e1 =
      (1 - Math.sqrt(1 - WGS84_ECC_SQUARED)) /
      (1 + Math.sqrt(1 - WGS84_ECC_SQUARED));
    const x = easting - 500_000;
    const y = this.definition.northernHemisphere
      ? northing
      : northing - 10_000_000;
    const longitudeOrigin = (this.definition.utmZone - 1) * 6 - 177;
    const m = y / UTM_SCALE;
    const mu =
      m /
      (WGS84_A *
        (1 -
          WGS84_ECC_SQUARED / 4 -
          (3 * WGS84_ECC_SQUARED ** 2) / 64 -
          (5 * WGS84_ECC_SQUARED ** 3) / 256));
    const phi1 =
      mu +
      (3 * e1 / 2 - 27 * e1 ** 3 / 32) * Math.sin(2 * mu) +
      (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * Math.sin(4 * mu) +
      (151 * e1 ** 3 / 96) * Math.sin(6 * mu) +
      (1097 * e1 ** 4 / 512) * Math.sin(8 * mu);
    const n1 =
      WGS84_A /
      Math.sqrt(1 - WGS84_ECC_SQUARED * Math.sin(phi1) ** 2);
    const t1 = Math.tan(phi1) ** 2;
    const c1 = eccentricityPrime * Math.cos(phi1) ** 2;
    const r1 =
      (WGS84_A * (1 - WGS84_ECC_SQUARED)) /
      (1 - WGS84_ECC_SQUARED * Math.sin(phi1) ** 2) ** 1.5;
    const d = x / (n1 * UTM_SCALE);
    const latitude =
      phi1 -
      ((n1 * Math.tan(phi1)) / r1) *
        (d ** 2 / 2 -
          ((5 + 3 * t1 + 10 * c1 - 4 * c1 ** 2 - 9 * eccentricityPrime) *
            d ** 4) /
            24 +
          ((61 + 90 * t1 + 298 * c1 + 45 * t1 ** 2 -
            252 * eccentricityPrime -
            3 * c1 ** 2) *
            d ** 6) /
            720);
    const longitude =
      (d -
        ((1 + 2 * t1 + c1) * d ** 3) / 6 +
        ((5 - 2 * c1 + 28 * t1 - 3 * c1 ** 2 +
          8 * eccentricityPrime +
          24 * t1 ** 2) *
          d ** 5) /
          120) /
      Math.cos(phi1);
    return {
      lon: longitudeOrigin + degrees(longitude),
      lat: degrees(latitude),
    };
  }
}
