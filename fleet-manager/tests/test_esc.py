import pytest

from fleetmanager.simulator import FakeFC, am32_esc, bluejay_esc
from fleetmanager.db import Fleet
from fleetmanager.detect import detect
from fleetmanager.esc import (
    FourWay,
    FourWayAck,
    FourWayError,
    crc16_xmodem,
    describe,
    encode,
    read_escs,
    summary,
)


def test_crc16_xmodem_check_value():
    assert crc16_xmodem(b"123456789") == 0x31C3


def test_encode_matches_the_frame_layout():
    frame = encode(0x37, bytes([2]), 0)
    assert frame[:5] == bytes([0x2F, 0x37, 0, 0, 1]) and frame[5] == 2
    assert crc16_xmodem(frame[:-2]) == int.from_bytes(frame[-2:], "big")
    # no parameter at all still sends one zero byte: the FC always reads at least one
    assert encode(0x30)[:6] == bytes([0x2F, 0x30, 0, 0, 1, 0])
    # 256 bytes are announced by a length of 0
    assert encode(0x3B, bytes(256), 0x1234)[2:5] == bytes([0x12, 0x34, 0])


def fc_with(*escs):
    return FakeFC(escs=list(escs))


def test_read_escs_identifies_each_firmware_and_restores_the_fc():
    fc = fc_with(bluejay_esc(), bluejay_esc(sub=19), am32_esc(), bluejay_esc(responds=False))
    res = read_escs(fc, 0.2, 0.2)
    assert res["interface"] == {"protocol": 108, "name": "m4wFCIntf"}
    e1, e2, e3, e4 = res["escs"]
    assert (e1["firmware"], e1["version"], e1["mcu"]) == ("Bluejay", "0.21", "EFM8BB21x")
    assert (e1["layout"], e1["mcu_tag"], e1["name"]) == ("#S_H_90#", "#BLHELI$EFM8B21#", "Bluejay (BETA)")
    assert e2["version"] == "0.19"
    assert (e3["firmware"], e3["version"], e3["mcu"], e3["file_name"]) == ("AM32", "2.16", "STM32F051", "TEKKO32_F051")
    assert e4["error"] and "battery" in e4["error"]
    assert fc.left_4way and not fc.in_4way, "the 4-way interface must be left"
    assert fc.reset_log == [0, 1, 2, 3], "every ESC is told to run its firmware again"


def test_blheli_s_and_unknown_arm_are_labelled_honestly():
    res = read_escs(fc_with(bluejay_esc(name="BLHeli_S", main=16, sub=7), am32_esc(pin=0x55)), 0.2, 0.2)
    s, arm = res["escs"]
    assert (s["firmware"], s["version"]) == ("BLHeli_S", "16.7")
    assert arm["firmware"].startswith("not AM32") and "file_name" not in arm


def test_unknown_signature_is_reported_not_guessed():
    esc = bluejay_esc(signature=0x1234)
    res = read_escs(fc_with(esc), 0.2, 0.2)
    assert res["escs"][0] == {"index": 1, "signature": "0x1234", "interface_mode": 1, "firmware": "unknown"}


def test_fc_without_4way_support_or_without_escs():
    with pytest.raises(FourWayError, match="4-way"):
        read_escs(FakeFC(), 0.05, 0.05)
    with pytest.raises(FourWayError, match="no ESC"):
        read_escs(FakeFC(escs=[]), 0.05, 0.05)


def test_ack_error_and_bad_crc_are_detected():
    fc = fc_with(bluejay_esc())
    read = FourWay(fc, 0.2)
    read.ser.in_4way = True
    with pytest.raises(FourWayAck) as e:
        read.request(0x37, bytes([9]))  # no such channel
    assert e.value.ack == 0x08

    class Corrupt:
        in_waiting = 0

        def __init__(self):
            body = bytes([0x2E, 0x31, 0, 0, 1, 108, 0])
            self.data = bytearray(body + crc16_xmodem(body).to_bytes(2, "big"))
            self.data[5] ^= 0xFF  # flip a parameter bit

        def reset_input_buffer(self):
            pass

        def write(self, d):
            pass

        def read(self, n=1):
            out, self.data = bytes(self.data[:n]), self.data[n:]
            return out

    with pytest.raises(FourWayError, match="CRC"):
        FourWay(Corrupt(), 0.2).request(0x31)


def test_describe_and_summary():
    ok = {"index": 1, "firmware": "Bluejay", "version": "0.21", "mcu": "EFM8BB21x", "layout": "#S_H_90#", "name": "Bluejay (BETA)"}
    assert describe(ok) == 'esc 1: Bluejay 0.21 on EFM8BB21x, layout "#S_H_90#", name "Bluejay (BETA)"'
    bad = {"index": 4, "firmware": "unknown", "error": "no answer"}
    assert describe(bad) == "esc 4: not read (no answer)"
    assert summary([ok, dict(ok, index=2), dict(ok, index=3), bad]) == "3x Bluejay 0.21 (EFM8BB21x), 1 not read"


def test_detect_reads_escs_before_the_cli_and_stores_them_in_the_snapshot_text(tmp_path):
    fc = fc_with(bluejay_esc(), bluejay_esc(sub=9))
    det = detect(fc, with_esc=True, timeout=0.2, cli_timeout=1)
    assert [e["version"] for e in det.info["escs"]] == ["0.21", "0.09"]
    assert det.info["esc_interface"]["protocol"] == 108
    assert det.info["sensors"] and fc.exited and not fc.in_4way  # the CLI still worked afterwards
    fleet = Fleet(tmp_path / "f.db")
    sid = fleet.register(det.info, det.diff_text, det.status_text)["snapshot_id"]
    assert "# esc 2: Bluejay 0.09 on EFM8BB21x" in fleet.get_snapshot(sid)["diff_text"]
    fleet.close()


def test_toggling_the_esc_reading_never_creates_a_snapshot(tmp_path):
    fleet = Fleet(tmp_path / "f.db")
    with_esc = detect(fc_with(bluejay_esc()), with_esc=True, timeout=0.2, cli_timeout=1)
    first = fleet.register(with_esc.info, with_esc.diff_text, with_esc.status_text)
    without = detect(fc_with(bluejay_esc()), timeout=0.2, cli_timeout=1)
    assert not fleet.register(without.info, without.diff_text, without.status_text)["changed"]
    d = fleet.get_drone(first["drone_id"])
    assert d["detected"]["escs"][0]["firmware"] == "Bluejay" and d["detected"]["escs_read_at"]
    assert next(c for c in d["components"] if c["type"] == "esc")["hint"] == "1x Bluejay 0.21 (EFM8BB21x)"
    again = detect(fc_with(bluejay_esc()), with_esc=True, timeout=0.2, cli_timeout=1)
    assert not fleet.register(again.info, again.diff_text, again.status_text)["changed"]
    fleet.close()


def test_esc_failure_is_only_a_warning():
    det = detect(FakeFC(), with_esc=True, timeout=0.2, cli_timeout=1)
    assert "escs" not in det.info and det.diff_text
    assert any("ESCs not read" in w for w in det.info["warnings"])
    det = detect(FakeFC(escs=[bluejay_esc(responds=False)]), with_esc=True, timeout=0.2, cli_timeout=1)
    assert any("battery" in w for w in det.info["warnings"])


def test_flashing_an_esc_creates_a_new_snapshot_and_updates_the_hint(tmp_path):
    fleet = Fleet(tmp_path / "f.db")
    det = detect(fc_with(bluejay_esc(), bluejay_esc()), with_esc=True, timeout=0.2, cli_timeout=1)
    first = fleet.register(det.info, det.diff_text, det.status_text)
    esc = next(c for c in fleet.get_drone(first["drone_id"])["components"] if c["type"] == "esc")
    assert esc["hint"] == "2x Bluejay 0.21 (EFM8BB21x)"

    same = detect(fc_with(bluejay_esc(), bluejay_esc()), with_esc=True, timeout=0.2, cli_timeout=1)
    assert not fleet.register(same.info, same.diff_text, same.status_text)["changed"]

    new = detect(fc_with(bluejay_esc(sub=22), bluejay_esc(sub=22)), with_esc=True, timeout=0.2, cli_timeout=1)
    res = fleet.register(new.info, new.diff_text, new.status_text)
    assert res["changed"]
    esc = next(c for c in fleet.get_drone(first["drone_id"])["components"] if c["type"] == "esc")
    assert esc["hint"] == "2x Bluejay 0.22 (EFM8BB21x)"
    fleet.close()
