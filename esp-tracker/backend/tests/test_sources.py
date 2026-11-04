import json
import time
from pathlib import Path

import pytest

from esptracker import sources
from esptracker.sources import (
    EventLogger,
    ReplaySource,
    SerialSource,
    SimulatorSource,
    make_on_connect,
    validate_command,
)
from esptracker.state import State


def wait_for(cond, timeout=5.0, step=0.02):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(step)
    return False


# ---- command validation -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    ["PING", "status", "HOME 48.1 -1.6 52", "HOME DRONE", "MODE AUTO", "AIM 90 45", "SET offset 90", "BIND my phrase", "  SAVE  "],
)
def test_validate_accepts(line):
    assert validate_command(line) == line.strip()


@pytest.mark.parametrize("line", ["", "   ", "FLY", "HOME 1 2 3\nREBOOT", "SET a 1\r", "x" * 200, "rm -rf /", 42])
def test_validate_rejects(line):
    with pytest.raises(ValueError):
        validate_command(line)


def test_make_on_connect():
    assert make_on_connect(None) == []
    assert make_on_connect("48.1,-1.6,52") == ["HOME 48.1 -1.6 52"]
    with pytest.raises(ValueError):
        make_on_connect("48.1,-1.6")
    with pytest.raises(ValueError):
        make_on_connect("a,b,c")


# ---- simulator ---------------------------------------------------------------------------------------


def test_simulator_emits_everything_and_obeys_commands():
    st = State()
    sim = SimulatorSource(st, time_scale=20)
    sim.start()
    try:
        assert wait_for(lambda: all(st.snapshot()[k] for k in ("gps", "bat", "rf", "att", "mode", "trk", "stat", "hello", "cfg")))
        snap = st.snapshot()
        assert snap["conn"]["connected"] is True and snap["conn"]["source"] == "simulator"
        assert snap["trk"]["home"] is False and snap["trk"]["az"] is None

        sim.send("HOME DRONE")
        assert wait_for(lambda: st.snapshot()["trk"]["home"] is True)
        sim.send("SET offset 45")
        sim.send("STATUS")
        assert wait_for(lambda: st.snapshot()["cfg"]["offset"] == 45.0)
        assert wait_for(lambda: st.snapshot()["trk"]["dist"] is not None)

        sim.send("AIM 10 20")
        assert wait_for(lambda: st.snapshot()["trk"]["mode"] == "manual")
        assert wait_for(lambda: st.snapshot()["trk"]["pan"] == 10.0 and st.snapshot()["trk"]["tilt"] == 20.0)

        sim.send("SET bogus 1")
        sim.send("HOME x y z")
        _, items = st.console_since(0)
        errs = [i["text"] for i in items if i["kind"] == "err"]
        assert any("unknown key" in e for e in errs) and any("bad arguments" in e for e in errs)

        assert wait_for(lambda: st.snapshot()["track_n"] > 2)
    finally:
        sim.stop()


def test_simulator_fixes_are_plausible():
    sim = SimulatorSource(State())
    pts = [sim.drone_at(t) for t in range(0, 120, 5)]
    for p in pts:
        assert 70 <= p["alt"] <= 170
        assert 0 <= p["heading"] < 360


# ---- serial (pyserial loop:// echoes what is written) --------------------------------------------------


def test_serial_source_roundtrip_over_loopback():
    st = State()
    src = SerialSource(st, port="loop://", on_connect=["HOME 48.1 -1.6 52"], retry_s=0.1)
    src.start()
    try:
        assert wait_for(lambda: st.snapshot()["conn"]["connected"])
        # the loopback echoes our commands back: STATUS + the on_connect command show up as raw lines
        assert wait_for(lambda: len(st.console_since(0)[1]) >= 2)
        raw = [i["text"] for i in st.console_since(0)[1]]
        assert "STATUS" in raw and "HOME 48.1 -1.6 52" in raw

        # inject firmware-style JSON as if the tracker had sent it
        ser = src._ser
        ser.write(b'{"e":"gps","ms":1,"lat":48.5,"lon":2.5,"alt":99,"gs":10.0,"hdg":90.0,"sats":11}\n')
        ser.write(b"partial line, ")  # a line arriving in several chunks is reassembled
        assert wait_for(lambda: st.snapshot()["gps"] is not None)
        assert st.snapshot()["gps"]["alt"] == 99
        ser.write(b"rest of it\n")
        assert wait_for(lambda: "partial line, rest of it" in [i["text"] for i in st.console_since(0)[1]])

        src.send("PING")
        assert wait_for(lambda: "PING" in [i["text"] for i in st.console_since(0)[1]])
    finally:
        src.stop()
    assert st.snapshot()["conn"]["connected"] is False
    with pytest.raises(ConnectionError):
        src.send("PING")


def test_serial_source_reports_missing_port_and_keeps_retrying():
    st = State()
    src = SerialSource(st, port="/dev/does-not-exist", retry_s=0.05)
    src.start()
    try:
        assert wait_for(lambda: st.snapshot()["conn"]["error"] is not None)
        assert st.snapshot()["conn"]["connected"] is False
    finally:
        src.stop()


def test_find_port_returns_none_without_devices(monkeypatch):
    monkeypatch.setattr(sources.serial.tools.list_ports, "comports", lambda: [])
    assert sources.find_port() is None


# ---- log + replay ---------------------------------------------------------------------------------------


def test_logger_and_replay_roundtrip(tmp_path: Path):
    log = tmp_path / "flight.jsonl"
    st = State()
    logger = EventLogger(str(log))
    st.add_listener(logger)
    st.ingest({"e": "gps", "lat": 48.0, "lon": 2.0, "alt": 10, "gs": 5.0, "hdg": 0.0, "sats": 10}, t=100.0)
    st.ingest({"e": "gps", "lat": 48.001, "lon": 2.0, "alt": 20, "gs": 9.0, "hdg": 0.0, "sats": 10}, t=100.2)
    st.ingest({"e": "bat", "v": 16.0, "a": 1.0, "mah": 1, "pct": 99}, t=100.3)
    logger.close()

    lines = [json.loads(l) for l in log.read_text().splitlines()]
    assert [l["ev"]["e"] for l in lines] == ["gps", "gps", "bat"] and lines[0]["t"] == 100.0

    st2 = State()
    rep = ReplaySource(st2, str(log), speed=100.0)
    rep.start()
    try:
        assert wait_for(lambda: st2.snapshot()["bat"] is not None)
        assert st2.snapshot()["gps"]["alt"] == 20
        assert st2.snapshot()["track_n"] == 2
    finally:
        rep.stop()
    with pytest.raises(PermissionError):
        rep.send("PING")


def test_replay_rejects_empty_log(tmp_path: Path):
    p = tmp_path / "empty.jsonl"
    p.write_text("not json\n\n")
    with pytest.raises(ValueError):
        ReplaySource(State(), str(p))


def test_validate_accepts_calibration_commands():
    assert validate_command("CAL MAG START") == "CAL MAG START"
    assert validate_command("home gps") == "home gps"


def test_simulator_tracker_sensors_and_calibration():
    st = State()
    sim = SimulatorSource(st, time_scale=20)
    sim.start()
    try:
        assert wait_for(lambda: st.snapshot()["sens"] and st.snapshot()["tgps"])
        snap = st.snapshot()
        assert snap["sens"]["mag"] == "HMC5883L" and snap["sens"]["cal"] == "none" and snap["sens"]["north"] is False
        sim.send("HOME GPS")
        assert wait_for(lambda: st.snapshot()["trk"]["hsrc"] == "gps" and st.snapshot()["trk"]["home"] is True)
        assert wait_for(lambda: st.snapshot()["tgps"]["ahome"] == "locked")

        sim.send("CAL MAG STOP")  # nothing running
        sim.send("CAL MAG START")
        assert wait_for(lambda: st.snapshot()["sens"]["cal"] == "running")
        assert wait_for(lambda: st.snapshot()["sens"]["cal_cov"] >= 100, timeout=8)
        sim.send("CAL MAG STOP")
        assert wait_for(lambda: st.snapshot()["sens"]["cal"] == "ok" and st.snapshot()["sens"]["north"] is True)
        sim.send("STATUS")
        # auto north: the pan offset follows the (simulated) compass, 215 deg + 1.5 deg declination
        assert wait_for(lambda: abs(st.snapshot()["trk"]["offset"] - 216.5) < 2)
        _, items = st.console_since(0)
        texts = [(i["kind"], i["text"]) for i in items]
        assert ("err", "no calibration running (CAL MAG START)") in texts
        assert ("ack", "CAL MAG START") in texts and ("ack", "CAL MAG STOP") in texts
    finally:
        sim.stop()
