import pytest

from fleetmanager.simulator import DIFF_ALL, FakeFC
from fleetmanager.db import BASE_COMPONENTS, Fleet, hints_from_info, normalize_diff
from fleetmanager.detect import detect


@pytest.fixture
def fleet(tmp_path):
    f = Fleet(tmp_path / "fleet.db")
    yield f
    f.close()


def detection(**kw):
    return detect(FakeFC(**kw), timeout=0.2, cli_timeout=1)


def comp(drone, type_):
    return next(c for c in drone["components"] if c["type"] == type_)


def test_first_detection_creates_a_skeleton(fleet):
    det = detection()
    res = fleet.register(det.info, det.diff_text, det.status_text)
    assert res["created"] and res["changed"] and res["snapshot_id"]
    d = fleet.get_drone(res["drone_id"])
    assert d["name"] == "Racer" and d["fc_uid"] == det.info["uid"]
    assert {c["type"] for c in d["components"]} >= set(BASE_COMPONENTS)
    assert comp(d, "receiver")["hint"] == "serial rx: CRSF"
    assert comp(d, "vtx")["hint"].startswith("MSP: 5760 MHz")
    assert comp(d, "motor")["hint"] == "DSHOT600, 14 poles"
    assert comp(d, "compass")["hint"] == ""  # no magnetometer on this FC
    assert comp(d, "gyro")["hint"] == "ICM42688P"  # extra type added because a chip was seen
    assert comp(d, "optical_flow")["hint"] == ""


def test_same_config_does_not_add_a_snapshot(fleet):
    for _ in range(3):
        det = detection()
        res = fleet.register(det.info, det.diff_text, det.status_text)
    assert not res["created"] and not res["changed"] and res["snapshot_id"] is None
    assert len(fleet.list_snapshots(res["drone_id"])) == 1
    assert len(fleet.list_drones()) == 1


def test_changed_config_adds_a_snapshot_and_whitespace_does_not(fleet):
    det = detection()
    first = fleet.register(det.info, det.diff_text, det.status_text)
    noisy = detection(diff=DIFF_ALL.replace("\n", "  \n") + "\n\n")  # trailing blanks only
    assert not fleet.register(noisy.info, noisy.diff_text, noisy.status_text)["changed"]
    changed = detection(diff=DIFF_ALL.replace("DSHOT600", "DSHOT300"))
    res = fleet.register(changed.info, changed.diff_text, changed.status_text)
    assert res["changed"] and res["drone_id"] == first["drone_id"]
    assert [s["id"] for s in fleet.list_snapshots(first["drone_id"])] == [res["snapshot_id"], first["snapshot_id"]]


def test_redetection_never_overwrites_manual_fields(fleet):
    det = detection()
    did = fleet.register(det.info, det.diff_text, det.status_text)["drone_id"]
    fleet.update_drone(did, {"name": "My 5 inch", "notes": "crashed twice", "specs": {"battery": "6S"}})
    rx = comp(fleet.get_drone(did), "receiver")
    fleet.update_component(rx["id"], {"model": "RadioMaster RP3", "specs": {"elrs_version": "3.5.3"}})

    det = detection()
    fleet.register(det.info, det.diff_text, det.status_text)
    d = fleet.get_drone(did)
    assert (d["name"], d["notes"], d["specs"]) == ("My 5 inch", "crashed twice", {"battery": "6S"})
    rx = comp(d, "receiver")
    assert (rx["model"], rx["specs"], rx["hint"]) == ("RadioMaster RP3", {"elrs_version": "3.5.3"}, "serial rx: CRSF")


def test_msp_only_detection_registers_without_snapshot(fleet):
    det = detect(FakeFC(), with_cli=False, timeout=0.2)
    res = fleet.register(det.info, det.diff_text, det.status_text)
    assert res["created"] and not res["changed"]
    assert fleet.get_drone(res["drone_id"])["snapshots"] == []


def test_two_fcs_are_two_drones(fleet):
    for uid in (bytes(range(1, 13)), bytes(range(2, 14))):
        det = detection(uid=uid)
        fleet.register(det.info, det.diff_text, det.status_text)
    assert len(fleet.list_drones()) == 2


def test_delete_drone_cascades(fleet):
    det = detection()
    did = fleet.register(det.info, det.diff_text, det.status_text)["drone_id"]
    fleet.set_photo(did, "x.jpg")
    assert fleet.delete_drone(did) == "x.jpg"
    assert fleet.get_drone(did) is None
    assert fleet._db.execute("SELECT COUNT(*) FROM component").fetchone()[0] == 0
    assert fleet._db.execute("SELECT COUNT(*) FROM snapshot").fetchone()[0] == 0


def test_update_ignores_unknown_columns(fleet):
    did = fleet.create_drone("a")
    fleet.update_drone(did, {"fc_uid": "hijack", "name": "b"})
    d = fleet.get_drone(did)
    assert d["name"] == "b" and d["fc_uid"] is None


def test_hints_and_normalize_helpers():
    assert hints_from_info({})["receiver"] == ""
    assert normalize_diff("a  \r\nb\r\n\r\n") == "a\nb\n"


def test_a_deleted_component_is_not_recreated_by_a_new_detection(fleet):
    det = detection()
    did = fleet.register(det.info, det.diff_text, det.status_text)["drone_id"]
    gyro = comp(fleet.get_drone(did), "gyro")
    fleet.delete_component(gyro["id"])
    det = detection()
    fleet.register(det.info, det.diff_text, det.status_text)
    assert not any(c["type"] == "gyro" for c in fleet.get_drone(did)["components"])


def test_register_is_one_transaction(fleet, monkeypatch):
    det = detection()
    monkeypatch.setattr(fleet, "_sync_hints", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        fleet.register(det.info, det.diff_text, det.status_text)
    assert fleet.list_drones() == [], "a failed registration must not leave a half-created drone"
