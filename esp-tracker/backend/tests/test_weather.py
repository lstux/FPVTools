import json
import urllib.parse
from pathlib import Path

import pytest

from esptracker import weather as wx

FIXTURE = Path(__file__).parent / "fixtures" / "openmeteo_sample.json"
T0 = 1793750400  # first hour in the fixture
RAW = json.loads(FIXTURE.read_text())


def test_url_asks_for_everything_we_use():
    url = wx.build_url(48.8566, 2.3522)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    hourly = q["hourly"][0].split(",")
    assert q["latitude"] == ["48.8566"] and q["timeformat"] == ["unixtime"]
    for v in wx.SURFACE_VARS:
        assert v in hourly
    assert "wind_speed_180m" in hourly and "geopotential_height_850hPa" in hourly
    assert q["wind_speed_unit"] == ["kmh"]


def test_normalise_picks_current_hour_and_builds_profile():
    now = T0 + 10 * 3600 + 1200  # 10:20 -> the 10:00 slot is the current one
    out = wx.normalise(RAW, now)
    assert out["elevation"] == 43.0 and out["timezone"] == "Europe/Paris"
    assert len(out["hours"]) == wx.HOURS
    h0 = out["hours"][0]
    assert h0["t"] == T0 + 10 * 3600
    assert h0["cloud_base"] == pytest.approx((h0["temp"] - h0["dew"]) * 125.0)
    agl = [r["agl"] for r in h0["wind"]]
    assert agl[:4] == [10.0, 80.0, 120.0, 180.0]
    assert agl == sorted(agl)
    # 1000 hPa (~150 m MSL -> ~107 m AGL) overlaps the height data and is dropped,
    # 700 hPa (~3010 m MSL -> ~2967 m AGL) is kept, nothing above the cap
    srcs = [r["src"] for r in h0["wind"]]
    assert "1000 hPa" not in srcs and "700 hPa" in srcs
    assert all(r["agl"] <= wx.MAX_PROFILE_AGL_M for r in h0["wind"])
    assert out["sun"]["sunrise"] == T0 + 6 * 3600 + 48 * 60


def test_normalise_tolerates_missing_and_null_values():
    raw = json.loads(json.dumps(RAW))
    del raw["hourly"]["visibility"]
    raw["hourly"]["wind_speed_80m"] = [None] * len(raw["hourly"]["time"])
    del raw["daily"]
    out = wx.normalise(raw, T0)
    assert out["hours"][0]["vis"] is None
    assert 80.0 not in [r["agl"] for r in out["hours"][0]["wind"]]
    assert out["sun"] == {"sunrise": None, "sunset": None}


def test_normalise_rejects_error_answers():
    with pytest.raises(ValueError, match="Cannot initialize"):
        wx.normalise({"error": True, "reason": "Cannot initialize WeatherVariable from invalid String value"}, T0)
    with pytest.raises(ValueError):
        wx.normalise({"latitude": 1}, T0)


class FakeFetch:
    def __init__(self):
        self.calls = 0
        self.fail = False

    def __call__(self, url):
        self.calls += 1
        if self.fail:
            raise OSError("network is unreachable")
        return RAW


def test_cache_ttl_and_offline_fallback(tmp_path):
    clock = [T0 + 3600.0]
    fetch = FakeFetch()
    cache = tmp_path / "wx" / "weather.json"
    w = wx.Weather(cache, fetch=fetch, clock=lambda: clock[0])

    a = w.get(48.8566, 2.3522)
    assert fetch.calls == 1 and a["stale"] is False and a["error"] is None
    assert cache.is_file()
    w.get(48.8571, 2.3519)  # same ~1 km cell, still fresh
    assert fetch.calls == 1
    w.get(48.8566, 2.3522, force=True)
    assert fetch.calls == 2

    # network gone, cache expired: last answer, flagged stale
    clock[0] += wx.CACHE_TTL_S + 1
    fetch.fail = True
    b = w.get(48.8566, 2.3522)
    assert b["stale"] is True and "unreachable" in b["error"] and not b["other_place"]

    # restart with no network: the on-disk copy is used
    w2 = wx.Weather(cache, fetch=fetch, clock=lambda: clock[0])
    c = w2.get(48.8566, 2.3522)
    assert c["stale"] is True and c["hours"]
    d = w2.get(45.0, 6.0)
    assert d["other_place"] is True


def test_no_cache_no_network_raises(tmp_path):
    fetch = FakeFetch()
    fetch.fail = True
    w = wx.Weather(tmp_path / "none.json", fetch=fetch, clock=lambda: T0)
    with pytest.raises(ValueError, match="unreachable"):
        w.get(48.0, 2.0)
    with pytest.raises(ValueError, match="bad coordinates"):
        w.get(95.0, 2.0)
