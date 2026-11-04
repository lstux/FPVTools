import json
from pathlib import Path

import pytest

from esptracker import geo
from esptracker.state import State

FIXTURE = Path(__file__).parent / "fixtures" / "firmware_events.jsonl"


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def firmware_lines():
    return [l for l in FIXTURE.read_text().splitlines() if l.strip()]


def test_fixture_is_real_firmware_output():
    kinds = {json.loads(l)["e"] for l in firmware_lines()}
    assert {"hello", "gps", "bat", "link", "att", "mode", "trk", "stat", "cfg", "ack", "err", "help"} <= kinds


def test_ingest_firmware_events():
    clock = Clock()
    st = State(clock=clock)
    for line in firmware_lines():
        st.ingest_line(line)
    snap = st.snapshot()

    assert snap["gps"]["lat"] == pytest.approx(48.1234567)
    assert snap["gps"]["lon"] == pytest.approx(-1.6543210)
    assert snap["gps"]["alt"] == 120 and snap["gps"]["sats"] == 12
    assert "e" not in snap["gps"] and "ms" not in snap["gps"]
    assert snap["bat"]["v"] == pytest.approx(16.4) and snap["bat"]["pct"] == 70
    assert snap["rf"]["lq"] == 99 and snap["rf"]["rssi1"] == -60 and snap["rf"]["txpwr"] == 100
    assert snap["att"]["pitch"] == pytest.approx(30.0) and snap["att"]["roll"] == pytest.approx(-10.0)
    assert snap["mode"]["m"] == "ACRO*"
    assert snap["hello"]["uid"] == "3b933b37b1e4" and snap["hello"]["espnow"] is True
    assert snap["cfg"]["offset"] == 0 and snap["cfg"]["min_sats"] == 6
    assert snap["stat"]["espnow"] == 120
    # the last "trk" fixture is the "no home" one, which has nulls
    assert snap["trk"]["home"] is False and snap["trk"]["az"] is None
    assert snap["gps"]["age"] == 0


def test_trk_with_home_and_flight_stats():
    st = State(clock=Clock())
    lines = firmware_lines()
    trk_home = [json.loads(l) for l in lines if json.loads(l)["e"] == "trk"][0]
    assert trk_home["home"] is True and trk_home["tracking"] is True
    st.ingest(trk_home)
    for line in lines:
        e = json.loads(line)
        if e["e"] == "gps":
            st.ingest(e)
    snap = st.snapshot()
    assert snap["trk"]["dist"] == pytest.approx(trk_home["dist"])
    assert snap["flight"]["max_dist_m"] == pytest.approx(trk_home["dist"])
    assert snap["flight"]["max_speed_kmh"] == pytest.approx(45.3)
    # alt 120 - home alt 100 = 20 m above home
    assert snap["flight"]["max_alt_rel_m"] == pytest.approx(20.0)


def test_console_entries_and_raw_lines():
    st = State(clock=Clock())
    for line in firmware_lines():
        st.ingest_line(line)
    st.ingest_line("ESP-ROM:esp32c3-api1-20210207")  # boot noise
    st.ingest_line("{broken json")
    st.ingest_line("")
    seq, items = st.console_since(0)
    kinds = [i["kind"] for i in items]
    assert kinds.count("ack") == 1 and kinds.count("err") == 1 and kinds.count("help") == 1
    assert kinds.count("raw") == 2
    assert any("x\"y" in i["text"] for i in items if i["kind"] == "err")  # JSON escaping round trip
    assert st.console_since(seq)[1] == []


def test_ages_and_connection():
    clock = Clock()
    st = State(clock=clock)
    assert st.snapshot()["gps"] is None
    assert st.snapshot()["conn"]["connected"] is False

    st.set_link("serial:/dev/ttyACM0", True)
    st.ingest({"e": "gps", "lat": 48.0, "lon": 2.0, "alt": 10, "gs": 1.0, "hdg": 0.0, "sats": 9})
    clock.t += 2.5
    snap = st.snapshot()
    assert snap["gps"]["age"] == 2.5
    assert snap["conn"]["last_rx_age"] == 2.5 and snap["conn"]["connected"] is True

    st.set_link("serial:/dev/ttyACM0", False, "gone")
    snap = st.snapshot()
    assert snap["conn"]["connected"] is False and snap["conn"]["error"] == "gone"
    assert snap["conn"]["last_rx_age"] is None


def _gps(lat, lon, sats=10, alt=50):
    return {"e": "gps", "lat": lat, "lon": lon, "alt": alt, "gs": 10.0, "hdg": 0.0, "sats": sats}


def test_track_filtering_and_incremental_reads():
    st = State(clock=Clock())
    st.ingest(_gps(0.0, 0.0))  # no fix
    st.ingest(_gps(48.0, 2.0, sats=2))  # too few satellites
    assert st.snapshot()["track_n"] == 0

    st.ingest(_gps(48.0, 2.0))
    st.ingest(_gps(48.0, 2.0000001))  # < 2 m: ignored
    st.ingest(_gps(48.0, 2.001))  # ~74 m
    st.ingest(_gps(48.0, 2.002))
    gen, nxt, reset, pts = st.track_since(-1, 0)
    assert reset and nxt == 3 and len(pts) == 3
    assert st.snapshot()["flight"]["path_m"] == pytest.approx(2 * geo.distance_m(48.0, 2.001, 48.0, 2.0), rel=0.02)

    st.ingest(_gps(48.0, 2.003))
    gen2, nxt2, reset2, pts2 = st.track_since(gen, nxt)
    assert not reset2 and nxt2 == 4 and len(pts2) == 1 and pts2[0][1] == pytest.approx(2.003)

    st.clear_track()
    gen3, nxt3, reset3, pts3 = st.track_since(gen2, nxt2)
    assert reset3 and gen3 != gen2 and nxt3 == 0 and pts3 == []
    assert st.snapshot()["flight"]["path_m"] == 0


def test_track_ring_buffer_never_loses_sync():
    st = State(track_max=5, clock=Clock())
    for i in range(12):
        st.ingest(_gps(48.0, 2.0 + i * 0.001))
    gen, nxt, reset, pts = st.track_since(-1, 0)
    assert nxt == 12 and len(pts) == 5 and pts[-1][1] == pytest.approx(2.011)
    # a client that was at index 9 gets exactly the 3 newest points
    gen, nxt, reset, pts = st.track_since(gen, 9)
    assert len(pts) == 3
    # a client far behind (index 0) gets what is still buffered, not an error
    gen, nxt, reset, pts = st.track_since(gen, 0)
    assert len(pts) == 5


def test_listener_receives_events():
    st = State(clock=Clock())
    seen = []
    st.add_listener(lambda ev, t: seen.append((ev["e"], t)))
    st.ingest({"e": "mode", "m": "ACRO"})
    assert seen == [("mode", 1000.0)]


def test_geo_matches_firmware_reference_values():
    # same expectations as firmware/tests/test_core.cpp
    assert geo.bearing_deg(0, 0, 0, 1) == pytest.approx(90.0)
    assert geo.bearing_deg(0, 0, -1, 0) == pytest.approx(180.0)
    assert geo.distance_m(0, 0, 1, 0) == pytest.approx(111194.93, abs=1.0)
    assert geo.elevation_deg(1000, 1000) == pytest.approx(45.0)
    m = geo.AimMapper()
    assert m.map(90, 30) == (90.0, 30.0, False)
    pan, tilt, flipped = m.map(270, 30)
    assert (pan, tilt, flipped) == (90.0, 150.0, True)
