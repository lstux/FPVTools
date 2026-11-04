"""Flying weather from Open-Meteo (https://open-meteo.com): free for non-commercial use, no API key.

We ask for the hourly forecast at the field and turn it into what matters for FPV / long range:
wind and gusts by height above ground (10/80/120/180 m from the model, higher from pressure levels
converted with their geopotential height), visibility, low/mid/high clouds, an estimated cloud base,
rain, CAPE (convection), freezing level and sunrise/sunset.

The last good answer is kept on disk so the panel still shows something at a field without internet.
Weather data by Open-Meteo.com, licensed CC BY 4.0.
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import __version__

log = logging.getLogger("esptracker.weather")

API_URL = "https://api.open-meteo.com/v1/forecast"
CACHE_TTL_S = 15 * 60
HOURS = 24
HEIGHT_LEVELS_M = (10, 80, 120, 180)
PRESSURE_LEVELS_HPA = (1000, 975, 950, 925, 900, 850, 800, 700)
MAX_PROFILE_AGL_M = 3500

SURFACE_VARS = (
    "temperature_2m",
    "dew_point_2m",
    "relative_humidity_2m",
    "precipitation_probability",
    "precipitation",
    "weather_code",
    "cloud_cover",
    "cloud_cover_low",
    "cloud_cover_mid",
    "cloud_cover_high",
    "visibility",
    "wind_gusts_10m",
    "cape",
    "freezing_level_height",
    "pressure_msl",
    "is_day",
)


def build_url(lat: float, lon: float, base: str = API_URL) -> str:
    hourly: List[str] = list(SURFACE_VARS)
    for h in HEIGHT_LEVELS_M:
        hourly += ["wind_speed_%dm" % h, "wind_direction_%dm" % h]
    for p in PRESSURE_LEVELS_HPA:
        hourly += ["wind_speed_%dhPa" % p, "wind_direction_%dhPa" % p, "geopotential_height_%dhPa" % p]
    q = {
        "latitude": "%.4f" % lat,
        "longitude": "%.4f" % lon,
        "hourly": ",".join(hourly),
        "daily": "sunrise,sunset",
        "wind_speed_unit": "kmh",
        "timeformat": "unixtime",
        "timezone": "auto",
        "forecast_days": "2",
    }
    return base + "?" + urllib.parse.urlencode(q, safe=",")


def _num(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def _col(hourly: Dict[str, Any], key: str, i: int) -> Optional[float]:
    arr = hourly.get(key)
    if not isinstance(arr, list) or i >= len(arr):
        return None
    return _num(arr[i])


def cloud_base_agl(temp_c: Optional[float], dew_c: Optional[float]) -> Optional[float]:
    """Cumulus cloud base estimate (Espy): ~125 m per degree of dew point spread."""
    if temp_c is None or dew_c is None:
        return None
    return max(0.0, (temp_c - dew_c) * 125.0)


def wind_profile(hourly: Dict[str, Any], i: int, elevation: Optional[float]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for h in HEIGHT_LEVELS_M:
        spd, d = _col(hourly, "wind_speed_%dm" % h, i), _col(hourly, "wind_direction_%dm" % h, i)
        if spd is not None:
            rows.append({"agl": float(h), "speed": spd, "dir": d, "src": "height"})
    top = max([r["agl"] for r in rows], default=0.0)
    if elevation is not None:
        for p in PRESSURE_LEVELS_HPA:
            gph = _col(hourly, "geopotential_height_%dhPa" % p, i)
            spd, d = _col(hourly, "wind_speed_%dhPa" % p, i), _col(hourly, "wind_direction_%dhPa" % p, i)
            if gph is None or spd is None:
                continue
            agl = gph - elevation
            # below ground, or overlapping the height-level data: skip
            if agl <= top + 50 or agl > MAX_PROFILE_AGL_M:
                continue
            rows.append({"agl": round(agl), "speed": spd, "dir": d, "src": "%d hPa" % p})
    rows.sort(key=lambda r: r["agl"])
    return rows


def normalise(raw: Dict[str, Any], now: float, hours: int = HOURS) -> Dict[str, Any]:
    """Open-Meteo response -> compact structure used by the UI. Tolerates missing variables."""
    if raw.get("error"):
        raise ValueError(str(raw.get("reason") or "Open-Meteo error"))
    hourly = raw.get("hourly")
    if not isinstance(hourly, dict) or not isinstance(hourly.get("time"), list):
        raise ValueError("unexpected Open-Meteo answer (no hourly data)")
    times = hourly["time"]
    elevation = _num(raw.get("elevation"))
    # first hour slot that is not over yet
    start = 0
    for k, t in enumerate(times):
        if isinstance(t, (int, float)) and t + 3600 > now:
            start = k
            break
    else:
        start = max(0, len(times) - 1)

    out_hours: List[Dict[str, Any]] = []
    for i in range(start, min(len(times), start + hours)):
        temp, dew = _col(hourly, "temperature_2m", i), _col(hourly, "dew_point_2m", i)
        out_hours.append(
            {
                "t": times[i],
                "temp": temp,
                "dew": dew,
                "rh": _col(hourly, "relative_humidity_2m", i),
                "pop": _col(hourly, "precipitation_probability", i),
                "precip": _col(hourly, "precipitation", i),
                "code": _col(hourly, "weather_code", i),
                "cloud": _col(hourly, "cloud_cover", i),
                "cloud_low": _col(hourly, "cloud_cover_low", i),
                "cloud_mid": _col(hourly, "cloud_cover_mid", i),
                "cloud_high": _col(hourly, "cloud_cover_high", i),
                "cloud_base": cloud_base_agl(temp, dew),
                "vis": _col(hourly, "visibility", i),
                "gust": _col(hourly, "wind_gusts_10m", i),
                "cape": _col(hourly, "cape", i),
                "freezing": _col(hourly, "freezing_level_height", i),
                "pressure": _col(hourly, "pressure_msl", i),
                "is_day": _col(hourly, "is_day", i),
                "wind": wind_profile(hourly, i, elevation),
            }
        )

    sun: Dict[str, Any] = {"sunrise": None, "sunset": None}
    daily = raw.get("daily")
    if isinstance(daily, dict):
        rises = [t for t in daily.get("sunrise") or [] if isinstance(t, (int, float))]
        sets = [t for t in daily.get("sunset") or [] if isinstance(t, (int, float))]
        # today's, or the next one if it is already past
        sun["sunrise"] = next((t for t in rises if t > now - 12 * 3600), None)
        sun["sunset"] = next((t for t in sets if t > now - 3600), None)

    return {
        "lat": _num(raw.get("latitude")),
        "lon": _num(raw.get("longitude")),
        "elevation": elevation,
        "utc_offset": _num(raw.get("utc_offset_seconds")) or 0,
        "timezone": raw.get("timezone"),
        "hours": out_hours,
        "sun": sun,
    }


def _http_get(url: str, timeout: float = 10.0) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "esptracker/%s" % __version__})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - fixed https URL
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Open-Meteo explains a bad request in a JSON body
        try:
            body = json.loads(exc.read().decode("utf-8"))
        except (ValueError, OSError):
            body = {}
        raise ValueError("Open-Meteo HTTP %s: %s" % (exc.code, body.get("reason", exc.reason)))


class Weather:
    """Fetch + memory cache + on-disk copy of the last good answer."""

    def __init__(
        self,
        cache_file: Optional[Path] = None,
        fetch: Callable[[str], Dict[str, Any]] = _http_get,
        ttl_s: float = CACHE_TTL_S,
        api_url: str = API_URL,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.cache_file = cache_file
        self._fetch = fetch
        self.ttl_s = ttl_s
        self.api_url = api_url
        self._clock = clock
        self._lock = threading.Lock()
        self._mem: Optional[Dict[str, Any]] = None  # {"key":..., "fetched":..., "raw":...}
        if cache_file and cache_file.is_file():
            try:
                self._mem = json.loads(cache_file.read_text())
            except (OSError, ValueError):
                self._mem = None

    @staticmethod
    def key(lat: float, lon: float) -> str:
        # ~1 km grid: no point refetching because the drone moved 50 m
        return "%.2f,%.2f" % (lat, lon)

    def get(self, lat: float, lon: float, force: bool = False) -> Dict[str, Any]:
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("bad coordinates")
        now = self._clock()
        key = self.key(lat, lon)
        with self._lock:
            mem = self._mem
            fresh = mem is not None and mem.get("key") == key and now - mem.get("fetched", 0) < self.ttl_s
            if fresh and not force:
                return self._answer(mem, now, stale=False, error=None)
            try:
                raw = self._fetch(build_url(lat, lon, self.api_url))
                normalise(raw, now)  # validate before keeping it
            except (OSError, ValueError, urllib.error.URLError) as exc:
                err = str(getattr(exc, "reason", None) or exc)
                log.warning("weather: %s", err)
                if mem is not None and mem.get("key") == key:
                    return self._answer(mem, now, stale=True, error=err)
                if mem is not None:
                    # a forecast for another place is still better than nothing at a field with no
                    # network, as long as the UI says so
                    return self._answer(mem, now, stale=True, error=err, other_place=True)
                raise ValueError(err)
            self._mem = {"key": key, "fetched": now, "raw": raw}
            self._save()
            return self._answer(self._mem, now, stale=False, error=None)

    def _answer(
        self, mem: Dict[str, Any], now: float, stale: bool, error: Optional[str], other_place: bool = False
    ) -> Dict[str, Any]:
        out = normalise(mem["raw"], now)
        out.update(
            source="Open-Meteo.com (CC BY 4.0)",
            fetched=mem["fetched"],
            age_s=round(now - mem["fetched"]),
            stale=stale,
            error=error,
            other_place=other_place,
        )
        return out

    def _save(self) -> None:
        if not self.cache_file:
            return
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._mem))
            tmp.replace(self.cache_file)
        except OSError as exc:
            log.warning("weather: cannot write cache %s: %s", self.cache_file, exc)
