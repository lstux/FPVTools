import pytest

from fakefc import DIFF_ALL, FakeFC
from fleetmanager.detect import DetectError, detect, parse_get, parse_status


def test_detect_reads_identity_sensors_settings_and_config():
    fc = FakeFC()
    det = detect(fc, timeout=0.2, cli_timeout=1)
    i = det.info
    assert (i["firmware"], i["variant"], i["version"], i["msp_api"]) == ("Betaflight", "BTFL", "4.5.1", "1.46")
    assert (i["board_id"], i["board_name"], i["craft_name"]) == ("S7X4", "SPEEDYBEEF7V3", "Racer")
    assert i["build_date"] == "Jan  1 2025" and i["git_revision"] == "abcdef0"
    assert i["uid"] == "0102030405060708090a0b0c"
    assert i["sensor_flags"] == {"acc": True, "baro": True, "mag": False, "gps": True}
    assert i["vtx"]["freq_mhz"] == 5760
    assert i["sensors"] == {"gyro": "ICM42688P", "acc": "ICM42688P", "baro": "DPS310"}
    assert i["settings"]["serialrx_provider"] == "CRSF"
    assert "mag_hardware" in i["settings"] and "dshot_bidir" not in i["settings"]
    assert det.diff_text.startswith("# diff all") and "set name = Racer" in det.diff_text
    assert "\r" not in det.diff_text
    assert fc.exited, "the CLI must be left (the FC reboots, it must not stay in CLI mode)"


def test_no_msp_answer_is_a_detect_error():
    with pytest.raises(DetectError, match="MSP"):
        detect(FakeFC(msp=False), timeout=0.05)


def test_cli_failure_keeps_msp_info_with_a_warning():
    det = detect(FakeFC(cli=False), timeout=0.2, cli_timeout=0.1)
    assert det.info["firmware"] == "Betaflight"
    assert det.diff_text is None
    assert det.info["warnings"] and "CLI" in det.info["warnings"][0]


def test_msp_only_never_touches_the_cli():
    fc = FakeFC()
    det = detect(fc, with_cli=False, timeout=0.2)
    assert det.diff_text is None and not fc.in_cli and not fc.exited


def test_all_zero_uid_is_ignored():
    det = detect(FakeFC(uid=bytes(12)), with_cli=False, timeout=0.2)
    assert "uid" not in det.info


def test_parsers():
    assert parse_status("GYRO=NONE, ACC=MPU6000") == {"acc": "MPU6000"}
    assert parse_get("noise\nmotor_poles = 14\nAllowed values: 2-64", "motor_poles") == {"motor_poles": "14"}
    assert parse_get("Invalid name", "motor_poles") == {}
    assert DIFF_ALL  # fixture sanity
