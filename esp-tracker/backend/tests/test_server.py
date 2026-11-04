import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from esptracker.server import create_app
from esptracker.sources import Source
from esptracker.state import State
from esptracker.tiles import MBTiles

FIXTURE = Path(__file__).parent / "fixtures" / "firmware_events.jsonl"


class FakeSource(Source):
    name = "fake"

    def __init__(self, state, read_only=False, fail_with=None):
        super().__init__(state)
        self.sent = []
        self.read_only = read_only
        self.fail_with = fail_with
        self.started = self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def send(self, line):
        if self.fail_with:
            raise self.fail_with
        self.sent.append(line)


@pytest.fixture
def env():
    st = State()
    src = FakeSource(st)
    with TestClient(create_app(st, src)) as client:
        yield st, src, client
    assert src.started and src.stopped


def load_fixture(st):
    for line in FIXTURE.read_text().splitlines():
        st.ingest_line(line)


def test_index_and_static(env):
    _, _, client = env
    r = client.get("/")
    assert r.status_code == 200 and "ESP Tracker" in r.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200
    assert client.get("/static/vendor/leaflet/leaflet.js").status_code == 200
    assert client.get("/static/vendor/leaflet/images/marker-icon.png").status_code == 200


def test_config_and_state(env):
    st, _, client = env
    cfg = client.get("/api/config").json()
    assert cfg["source"] == "fake" and cfg["local_tiles"] is None and "openstreetmap" in cfg["tile_url"]
    assert client.get("/api/state").json()["gps"] is None
    load_fixture(st)
    snap = client.get("/api/state").json()
    assert snap["gps"]["sats"] == 12 and snap["hello"]["uid"] == "3b933b37b1e4"


def test_commands(env):
    st, src, client = env
    r = client.post("/api/cmd", json={"line": "HOME 48.1 -1.6 52"})
    assert r.status_code == 200 and src.sent == ["HOME 48.1 -1.6 52"]

    assert client.post("/api/cmd", json={"line": "FLY"}).status_code == 400
    assert client.post("/api/cmd", json={"line": "SAVE\nREBOOT"}).status_code == 400
    assert client.post("/api/cmd", json={}).status_code == 422
    assert src.sent == ["HOME 48.1 -1.6 52"]

    # the bind phrase must never be echoed in the console
    client.post("/api/cmd", json={"line": "BIND super secret phrase"})
    assert src.sent[-1] == "BIND super secret phrase"
    texts = [i["text"] for i in st.console_since(0)[1]]
    assert "BIND ********" in texts and not any("secret" in t for t in texts)


def test_command_errors_map_to_http_status():
    st = State()
    for exc in (ConnectionError("tracker is not connected"), PermissionError("replay mode is read-only")):
        with TestClient(create_app(st, FakeSource(st, fail_with=exc))) as client:
            r = client.post("/api/cmd", json={"line": "PING"})
            assert r.status_code == 409 and str(exc) in r.json()["detail"]


def test_track_clear_and_gpx(env):
    st, _, client = env
    st.ingest({"e": "gps", "lat": 48.0, "lon": 2.0, "alt": 10, "gs": 1.0, "hdg": 0.0, "sats": 10})
    st.ingest({"e": "gps", "lat": 48.001, "lon": 2.0, "alt": 20, "gs": 1.0, "hdg": 0.0, "sats": 10})
    gpx = client.get("/api/track.gpx")
    assert gpx.status_code == 200 and gpx.headers["content-type"].startswith("application/gpx+xml")
    assert gpx.text.count("<trkpt") == 2 and 'lat="48.0010000"' in gpx.text
    assert client.post("/api/track/clear").json() == {"ok": True}
    assert client.get("/api/track.gpx").text.count("<trkpt") == 0


def test_websocket_streams_state_track_and_console(env):
    st, src, client = env
    load_fixture(st)
    with client.websocket_connect("/ws") as ws:
        first = ws.receive_json()
        assert first["state"]["gps"]["lat"] == pytest.approx(48.1234567)
        assert first["track"]["reset"] is True and len(first["track"]["pts"]) == 1
        assert any(i["kind"] == "ack" for i in first["console"])

        st.ingest({"e": "gps", "lat": 48.2, "lon": -1.6, "alt": 130, "gs": 1.0, "hdg": 0.0, "sats": 12})
        for _ in range(5):  # the next tick (~0.2 s) carries the new point
            msg = ws.receive_json()
            if msg["track"]["pts"]:
                break
        assert msg["track"]["reset"] is False and msg["track"]["pts"][0][0] == pytest.approx(48.2)
        assert msg["console"] == []

        client.post("/api/track/clear")
        for _ in range(5):
            msg = ws.receive_json()
            if msg["track"]["reset"]:
                break
        assert msg["track"]["reset"] is True and msg["track"]["pts"] == []


# ---- offline tiles -------------------------------------------------------------------------------------


def make_mbtiles(path: Path, fmt="png"):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE metadata (name text, value text)")
    con.execute("CREATE TABLE tiles (zoom_level integer, tile_column integer, tile_row integer, tile_data blob)")
    con.executemany(
        "INSERT INTO metadata VALUES (?, ?)",
        [("name", "test"), ("format", fmt), ("minzoom", "0"), ("maxzoom", "5"), ("bounds", "-1,47,3,49"), ("center", "2,48,3")],
    )
    # XYZ tile z=2,x=1,y=0 is stored in TMS row (2^2 - 1 - 0) = 3
    con.execute("INSERT INTO tiles VALUES (2, 1, 3, ?)", (b"\x89PNG-fake-tile",))
    con.commit()
    con.close()


def test_local_tiles(tmp_path: Path):
    db = tmp_path / "map.mbtiles"
    make_mbtiles(db)
    tiles = MBTiles(str(db))
    st = State()
    with TestClient(create_app(st, FakeSource(st), tiles=tiles)) as client:
        cfg = client.get("/api/config").json()
        assert cfg["local_tiles"]["maxzoom"] == 5 and cfg["local_tiles"]["center"] == [2.0, 48.0, 3.0]
        r = client.get("/tiles/2/1/0")
        assert r.status_code == 200 and r.content == b"\x89PNG-fake-tile" and r.headers["content-type"] == "image/png"
        assert client.get("/tiles/2/1/1").status_code == 404
        assert client.get("/tiles/2/9/9").status_code == 404
    tiles.close()


def test_mbtiles_validation(tmp_path: Path):
    bad = tmp_path / "bad.mbtiles"
    bad.write_bytes(b"not sqlite")
    with pytest.raises(ValueError):
        MBTiles(str(bad))
    vec = tmp_path / "vec.mbtiles"
    make_mbtiles(vec, fmt="pbf")
    with pytest.raises(ValueError, match="vector"):
        MBTiles(str(vec))
