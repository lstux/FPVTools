import pytest
from fastapi.testclient import TestClient

from fakefc import DIFF_ALL, FakeFC
from fleetmanager.db import Fleet
from fleetmanager.detect import DetectError, detect
from fleetmanager.server import create_app

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


@pytest.fixture
def env(tmp_path):
    fleet = Fleet(tmp_path / "fleet.db")
    state = {"diff": DIFF_ALL, "error": None}

    def scanner(port, cli):
        if state["error"]:
            raise state["error"]
        return detect(FakeFC(diff=state["diff"]), with_cli=cli, timeout=0.2, cli_timeout=1)

    client = TestClient(create_app(fleet, tmp_path / "photos", scanner))
    yield client, state, tmp_path
    fleet.close()


def scan(client):
    r = client.post("/api/scan", json={"port": "auto"})
    assert r.status_code == 200, r.text
    return r.json()


def test_scan_flow_and_history(env):
    client, state, _ = env
    first = scan(client)
    assert first["created"] and first["changed"]
    again = scan(client)
    assert not again["created"] and not again["changed"]
    state["diff"] = DIFF_ALL.replace("DSHOT600", "DSHOT300")
    third = scan(client)
    assert third["changed"]

    d = client.get("/api/drones/%d" % first["drone_id"]).json()
    assert len(d["snapshots"]) == 2 and d["detected"]["firmware"] == "Betaflight"

    diff = client.get("/api/snapshots/diff", params={"a": first["snapshot_id"], "b": third["snapshot_id"]}).json()
    assert diff["stats"]["chg"] == 1 and not diff["identical"]
    assert diff["a"]["id"] == first["snapshot_id"]
    snap = client.get("/api/snapshots/%d" % third["snapshot_id"]).json()
    assert "DSHOT300" in snap["diff_text"]


def test_scan_errors_are_reported(env):
    client, state, _ = env
    state["error"] = DetectError("no flight controller found")
    r = client.post("/api/scan", json={})
    assert r.status_code == 400 and "no flight controller" in r.json()["detail"]
    state["error"] = PermissionError()
    r = client.post("/api/scan", json={})
    assert r.status_code == 400 and "dialout" in r.json()["detail"]


def test_edit_drone_and_components(env):
    client, _, _ = env
    did = scan(client)["drone_id"]
    r = client.patch("/api/drones/%d" % did, json={"name": "  Bando  ", "specs": {"frame": "5in"}})
    assert r.json()["name"] == "Bando" and r.json()["specs"] == {"frame": "5in"}
    assert client.patch("/api/drones/%d" % did, json={"name": "  "}).status_code == 400
    assert client.patch("/api/drones/999", json={"name": "x"}).status_code == 404

    comps = client.get("/api/drones/%d" % did).json()["components"]
    motor = next(c for c in comps if c["type"] == "motor")
    assert client.patch("/api/components/%d" % motor["id"], json={"model": "2306 1900KV"}).status_code == 200
    new = client.post("/api/drones/%d/components" % did, json={"type": "battery", "model": "6S 1300"})
    assert new.status_code == 201
    assert client.delete("/api/components/%d" % new.json()["id"]).status_code == 204
    assert client.delete("/api/components/%d" % new.json()["id"]).status_code == 404
    after = client.get("/api/drones/%d" % did).json()["components"]
    assert next(c for c in after if c["id"] == motor["id"])["model"] == "2306 1900KV"


def test_manual_drone_and_delete(env):
    client, _, _ = env
    assert client.post("/api/drones", json={}).status_code == 400
    did = client.post("/api/drones", json={"name": "Tinywhoop"}).json()["id"]
    assert [d["name"] for d in client.get("/api/drones").json()] == ["Tinywhoop"]
    assert client.delete("/api/drones/%d" % did).status_code == 204
    assert client.get("/api/drones/%d" % did).status_code == 404


def test_photo_upload_replace_and_delete(env):
    client, _, tmp = env
    did = scan(client)["drone_id"]
    url = "/api/drones/%d/photo" % did
    assert client.put(url, content=b"x", headers={"content-type": "text/plain"}).status_code == 415
    assert client.put(url, content=b"not a png", headers={"content-type": "image/png"}).status_code == 415
    name = client.put(url, content=PNG, headers={"content-type": "image/png"}).json()["photo"]
    assert (tmp / "photos" / name).exists()
    assert client.get("/photos/" + name).content == PNG
    assert client.get("/api/drones/%d" % did).json()["photo"] == name
    assert client.delete(url).status_code == 204
    assert not (tmp / "photos" / name).exists()
    assert client.get("/api/drones/%d" % did).json()["photo"] is None


def test_index_and_static(env):
    client, _, _ = env
    assert "Fleet manager" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/api/snapshots/999").status_code == 404
