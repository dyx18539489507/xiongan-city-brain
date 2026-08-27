export type GeographicPoint = {lon: number; lat: number};

const PI = Math.PI;
const EARTH_RADIUS = 6_378_245;
const ECCENTRICITY_SQUARED = 0.006693421622965943;

function outsideChina(lon: number, lat: number): boolean {
  return lon < 72.004 || lon > 137.8347 || lat < .8293 || lat > 55.8271;
}

function transformLatitude(lon: number, lat: number): number {
  let value = -100 + 2 * lon + 3 * lat + .2 * lat * lat + .1 * lon * lat + .2 * Math.sqrt(Math.abs(lon));
  value += (20 * Math.sin(6 * lon * PI) + 20 * Math.sin(2 * lon * PI)) * 2 / 3;
  value += (20 * Math.sin(lat * PI) + 40 * Math.sin(lat / 3 * PI)) * 2 / 3;
  value += (160 * Math.sin(lat / 12 * PI) + 320 * Math.sin(lat * PI / 30)) * 2 / 3;
  return value;
}

function transformLongitude(lon: number, lat: number): number {
  let value = 300 + lon + 2 * lat + .1 * lon * lon + .1 * lon * lat + .1 * Math.sqrt(Math.abs(lon));
  value += (20 * Math.sin(6 * lon * PI) + 20 * Math.sin(2 * lon * PI)) * 2 / 3;
  value += (20 * Math.sin(lon * PI) + 40 * Math.sin(lon / 3 * PI)) * 2 / 3;
  value += (150 * Math.sin(lon / 12 * PI) + 300 * Math.sin(lon / 30 * PI)) * 2 / 3;
  return value;
}

export function wgs84ToGcj02(lon: number, lat: number): GeographicPoint {
  if (outsideChina(lon, lat)) return {lon, lat};
  let deltaLat = transformLatitude(lon - 105, lat - 35);
  let deltaLon = transformLongitude(lon - 105, lat - 35);
  const radians = lat / 180 * PI;
  let magic = Math.sin(radians);
  magic = 1 - ECCENTRICITY_SQUARED * magic * magic;
  const sqrtMagic = Math.sqrt(magic);
  deltaLat = deltaLat * 180 / ((EARTH_RADIUS * (1 - ECCENTRICITY_SQUARED)) / (magic * sqrtMagic) * PI);
  deltaLon = deltaLon * 180 / (EARTH_RADIUS / sqrtMagic * Math.cos(radians) * PI);
  return {lon: lon + deltaLon, lat: lat + deltaLat};
}

export function gcj02ToWgs84(lon: number, lat: number): GeographicPoint {
  if (outsideChina(lon, lat)) return {lon, lat};
  let estimate = {lon, lat};
  for (let attempt = 0; attempt < 8; attempt += 1) {
    const converted = wgs84ToGcj02(estimate.lon, estimate.lat);
    const lonError = converted.lon - lon;
    const latError = converted.lat - lat;
    estimate = {lon: estimate.lon - lonError, lat: estimate.lat - latError};
    if (Math.abs(lonError) < 1e-8 && Math.abs(latError) < 1e-8) break;
  }
  return estimate;
}
