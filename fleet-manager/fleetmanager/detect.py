"""Read a flight controller over USB: MSP for its identity, the CLI for its settings.

Only Betaflight/INAV-style firmwares are handled (MSP + text CLI). Everything the FC reports is kept
as text too (``status`` and ``diff all`` output) so that nothing is lost if a parser is wrong.

WARNING: leaving the CLI with ``exit`` makes the FC reboot. Detect on the bench, not while armed.
"""

from __future__ import annotations

import re
import struct
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .msp import (
    MSP_API_VERSION,
    MSP_BOARD_INFO,
    MSP_BUILD_INFO,
    MSP_FC_VARIANT,
    MSP_FC_VERSION,
    MSP_NAME,
    MSP_STATUS,
    MSP_UID,
    MSP_VTX_CONFIG,
    MspClient,
    MspError,
    MspTimeout,
)

FIRMWARES = {"BTFL": "Betaflight", "INAV": "INAV", "EMUF": "EmuFlight", "CLFL": "Cleanflight"}

# Settings read one by one with ``get`` (``diff all`` only lists values that differ from the defaults).
# Unknown names (not every firmware has them) are simply absent from the result.
CLI_SETTINGS = [
    "serialrx_provider",
    "motor_pwm_protocol",
    "dshot_bidir",
    "motor_poles",
    "gps_provider",
    "acc_hardware",
    "baro_hardware",
    "mag_hardware",
    "opflow_hardware",
    "rangefinder_hardware",
    "blackbox_device",
]

# MSP_STATUS sensor flags common to Betaflight and INAV (legacy MultiWii bits).
SENSOR_BITS = (("acc", 0), ("baro", 1), ("mag", 2), ("gps", 3))


class DetectError(Exception):
    pass


class CliError(Exception):
    pass


@dataclass
class Detection:
    info: Dict[str, Any]
    diff_text: Optional[str] = None
    status_text: Optional[str] = None


# --------------------------------------------------------------------------- ports


def candidate_ports() -> List[Dict[str, Any]]:
    """USB serial ports that look like a flight controller (CDC-ACM or STM32 vendor id)."""
    from serial.tools import list_ports

    out = []
    for p in list_ports.comports():
        if p.device.startswith("/dev/ttyACM") or p.vid == 0x0483:
            out.append(
                {"device": p.device, "description": p.description or "", "vid": p.vid, "pid": p.pid}
            )
    return sorted(out, key=lambda d: d["device"])


def resolve_port(port: Optional[str]) -> str:
    if port and port != "auto":
        return port
    cands = candidate_ports()
    if len(cands) == 1:
        return cands[0]["device"]
    if not cands:
        raise DetectError(
            "no flight controller found on USB (plugged in? member of the dialout group? "
            "Betaflight/INAV Configurator closed?)"
        )
    raise DetectError("several candidate ports, pick one: " + ", ".join(c["device"] for c in cands))


def scan_port(port: Optional[str] = "auto", with_cli: bool = True) -> Detection:
    """Open the port (``auto`` = the only FC-looking one) and run :func:`detect`."""
    import serial

    dev = resolve_port(port)
    try:
        ser = serial.Serial(dev, 115200, timeout=0.1, write_timeout=2)
    except (serial.SerialException, OSError) as e:
        raise DetectError("cannot open %s: %s" % (dev, e)) from e
    try:
        det = detect(ser, with_cli=with_cli)
        det.info["port"] = dev
        return det
    except serial.SerialException as e:
        raise DetectError("serial error on %s: %s" % (dev, e)) from e
    finally:
        try:
            ser.close()
        except Exception:
            pass


# --------------------------------------------------------------------------- MSP


def _text(b: bytes) -> str:
    return b.decode("ascii", "replace").strip("\x00 ").strip()


def read_msp_info(msp: MspClient) -> Dict[str, Any]:
    try:
        api = msp.request(MSP_API_VERSION)
        variant = _text(msp.request(MSP_FC_VARIANT))
        ver = msp.request(MSP_FC_VERSION)
    except MspTimeout as e:
        raise DetectError(
            "the FC does not answer MSP (wrong port? a configurator or another program using it?)"
        ) from e
    except MspError as e:
        raise DetectError("unexpected MSP answer: %s" % e) from e
    if len(api) < 3 or len(ver) < 3:
        raise DetectError("truncated MSP answer")

    info: Dict[str, Any] = {
        "variant": variant,
        "firmware": FIRMWARES.get(variant, variant),
        "version": "%d.%d.%d" % (ver[0], ver[1], ver[2]),
        "msp_api": "%d.%d" % (api[1], api[2]),
    }

    def optional(code: int) -> Optional[bytes]:
        try:
            return msp.request(code)
        except MspError:
            return None

    p = optional(MSP_BOARD_INFO)
    if p and len(p) >= 4:
        info["board_id"] = _text(p[:4])
        if len(p) >= 6:
            info["hw_revision"] = struct.unpack_from("<H", p, 4)[0]
        if len(p) >= 9 and len(p) >= 9 + p[8]:
            info["board_name"] = _text(p[9 : 9 + p[8]])
    p = optional(MSP_BUILD_INFO)
    if p and len(p) >= 19:
        info["build_date"] = _text(p[:11])
        info["build_time"] = _text(p[11:19])
        if len(p) >= 26:
            info["git_revision"] = _text(p[19:26])
    p = optional(MSP_NAME)
    if p is not None:
        info["craft_name"] = _text(p)
    p = optional(MSP_UID)
    if p and len(p) >= 12 and any(p[:12]):
        info["uid"] = p[:12].hex()
    p = optional(MSP_STATUS)
    if p and len(p) >= 6:
        flags = struct.unpack_from("<H", p, 4)[0]
        info["sensor_flags"] = {name: bool(flags >> bit & 1) for name, bit in SENSOR_BITS}
    p = optional(MSP_VTX_CONFIG)
    if p and len(p) >= 7:
        freq = struct.unpack_from("<H", p, 5)[0]
        if freq or p[1]:
            info["vtx"] = {
                "type": p[0],
                "band": p[1],
                "channel": p[2],
                "power": p[3],
                "pit_mode": p[4],
                "freq_mhz": freq,
            }
    return info


# --------------------------------------------------------------------------- CLI

_PROMPT_TAIL = (b"\n# ",)


class Cli:
    """The text CLI of Betaflight/INAV. ``enter`` with '#', ``exit`` reboots the FC."""

    def __init__(self, ser, timeout: float = 4.0) -> None:
        self.ser = ser
        self.timeout = timeout

    def _read_until_prompt(self, timeout: float) -> str:
        buf = bytearray()
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            chunk = self.ser.read(self.ser.in_waiting or 1)
            if chunk:
                buf += chunk
            elif buf.endswith(_PROMPT_TAIL) or bytes(buf) == b"# ":
                return bytes(buf).decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")
        raise CliError("no CLI prompt within %.0fs" % timeout)

    def enter(self) -> None:
        self.ser.reset_input_buffer()
        self.ser.write(b"#")
        self._read_until_prompt(self.timeout)

    def run(self, cmd: str, timeout: Optional[float] = None) -> str:
        self.ser.write(cmd.encode() + b"\n")
        lines = self._read_until_prompt(self.timeout if timeout is None else timeout).split("\n")
        if lines and lines[0].strip() == cmd:  # local echo
            lines.pop(0)
        if lines and lines[-1].strip() == "#":  # the prompt
            lines.pop()
        return "\n".join(lines).strip("\n")

    def exit(self) -> None:
        self.ser.write(b"exit\n")


_HW_RE = re.compile(r"\b(GYRO|ACC|BARO|MAG|OPFLOW|RANGEFINDER|PITOT)\s*=\s*([A-Za-z0-9_\-]+)")


def parse_status(text: str) -> Dict[str, str]:
    """Sensor chips reported by ``status`` (``GYRO=ICM42688P, ACC=..., BARO=...``)."""
    out: Dict[str, str] = {}
    for key, value in _HW_RE.findall(text):
        if value.upper() != "NONE":
            out[key.lower()] = value
    return out


def parse_get(text: str, name: str) -> Dict[str, str]:
    m = re.search(r"^%s\s*=\s*(.+?)\s*$" % re.escape(name), text, re.MULTILINE)
    return {name: m.group(1)} if m else {}


def read_cli(ser, info: Dict[str, Any], timeout: float) -> "tuple[str, str]":
    """Fill ``info['sensors']``/``info['settings']`` and return (diff_text, status_text)."""
    cli = Cli(ser, timeout)
    cli.enter()
    try:
        status = cli.run("status")
        info["sensors"] = parse_status(status)
        settings: Dict[str, str] = {}
        for name in CLI_SETTINGS:
            settings.update(parse_get(cli.run("get " + name), name))
        info["settings"] = settings
        diff = cli.run("diff all", timeout * 5)
    finally:
        try:
            cli.exit()
        except Exception:
            pass
    return diff, status


def detect(ser, with_cli: bool = True, timeout: float = 1.0, cli_timeout: float = 4.0) -> Detection:
    """Identify the FC behind ``ser`` (a pyserial-like object)."""
    info = read_msp_info(MspClient(ser, timeout))
    info["warnings"] = []
    diff_text = status_text = None
    if with_cli:
        try:
            diff_text, status_text = read_cli(ser, info, cli_timeout)
        except CliError as e:
            info["warnings"].append("CLI not available, no configuration snapshot: %s" % e)
    return Detection(info, diff_text, status_text)
