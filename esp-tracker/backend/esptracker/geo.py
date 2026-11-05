"""Geodesy helpers. Same formulas (and tests) as the firmware's geo.cpp; used by the simulator."""

from __future__ import annotations

import math

EARTH_R = 6371000.0


def wrap360(deg: float) -> float:
    return deg % 360.0


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return wrap360(math.degrees(math.atan2(y, x)))


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2.0 * EARTH_R * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def elevation_deg(ground_dist_m: float, delta_alt_m: float) -> float:
    return max(0.0, min(90.0, math.degrees(math.atan2(delta_alt_m, ground_dist_m))))


def offset_position(lat: float, lon: float, east_m: float, north_m: float) -> tuple[float, float]:
    """Flat-earth displacement, good enough for a few km."""
    dlat = math.degrees(north_m / EARTH_R)
    dlon = math.degrees(east_m / (EARTH_R * math.cos(math.radians(lat))))
    return lat + dlat, lon + dlon


class AimMapper:
    """Python twin of the firmware's AimMapper (azimuth/elevation -> pan/tilt with over-the-top flip)."""

    def __init__(self) -> None:
        self.flipped = False

    def map(self, az: float, el: float, offset: float = 0.0, hyst: float = 3.0) -> tuple[float, float, bool]:
        rel = wrap360(az - offset)
        if not self.flipped and rel > 180.0 + hyst:
            self.flipped = True
        elif self.flipped and rel < 180.0 - hyst:
            self.flipped = False
        el = max(0.0, min(90.0, el))
        if not self.flipped:
            return max(0.0, min(180.0, rel)), el, False
        return max(0.0, min(180.0, rel - 180.0)), 180.0 - el, True
