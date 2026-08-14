"""One authoritative SUMO, WGS84 and Three.js coordinate service."""

from __future__ import annotations

import math
from dataclasses import dataclass

from pyproj import CRS, Transformer


@dataclass(frozen=True, slots=True)
class CoordinateDefinition:
    """Immutable projection and floating-origin definition."""

    projection: str
    net_offset_x: float
    net_offset_y: float
    world_origin_sumo_x: float
    world_origin_sumo_y: float


class CoordinateService:
    """Convert all scene actors through the same meter-based transform."""

    def __init__(self, definition: CoordinateDefinition) -> None:
        self.definition = definition
        projected = CRS.from_user_input(definition.projection)
        wgs84 = CRS.from_epsg(4326)
        self._to_lon_lat = Transformer.from_crs(projected, wgs84, always_xy=True)
        self._from_lon_lat = Transformer.from_crs(wgs84, projected, always_xy=True)

    def sumo_to_world(
        self,
        x_m: float,
        y_m: float,
        height_m: float = 0.0,
    ) -> tuple[float, float, float]:
        """Map SUMO east/north into Three X/up/-Z using meters."""

        return (
            float(x_m) - self.definition.world_origin_sumo_x,
            float(height_m),
            self.definition.world_origin_sumo_y - float(y_m),
        )

    def world_to_sumo(self, x_m: float, z_m: float) -> tuple[float, float]:
        """Invert a Three X/Z point back to SUMO local coordinates."""

        return (
            float(x_m) + self.definition.world_origin_sumo_x,
            self.definition.world_origin_sumo_y - float(z_m),
        )

    @staticmethod
    def sumo_angle_to_three(angle_deg: float) -> float:
        """Convert SUMO clockwise-from-north degrees to Three yaw radians."""

        value = math.radians(-float(angle_deg))
        return (value + math.pi) % (2.0 * math.pi) - math.pi

    @staticmethod
    def world_angle_to_sumo(yaw_rad: float) -> float:
        """Invert Three yaw into SUMO's [0, 360) heading convention."""

        return math.degrees(-float(yaw_rad)) % 360.0

    def sumo_to_lon_lat(self, x_m: float, y_m: float) -> tuple[float, float]:
        """Convert SUMO local meters through netOffset and the network CRS."""

        projected_x = float(x_m) - self.definition.net_offset_x
        projected_y = float(y_m) - self.definition.net_offset_y
        lon, lat = self._to_lon_lat.transform(projected_x, projected_y)
        return float(lon), float(lat)

    def lon_lat_to_sumo(self, lon: float, lat: float) -> tuple[float, float]:
        """Convert WGS84 into SUMO local meters."""

        projected_x, projected_y = self._from_lon_lat.transform(float(lon), float(lat))
        return (
            float(projected_x) + self.definition.net_offset_x,
            float(projected_y) + self.definition.net_offset_y,
        )
