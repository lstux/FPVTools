"""Read the ESCs through the flight controller's BLHeli 4-way interface.

Protocol and memory layouts follow Betaflight's ``src/main/io/serial_4way.c`` and the
`esc-configurator <https://github.com/stylesuxx/esc-configurator>`_ sources (``FourWay.js``,
``sources/*/eeprom.js``, ``Hardware/*.js``). Only read commands are used.

Frames (CRC = CRC16 XMODEM, poly 0x1021, init 0, sent high byte first)::

    request : 0x2F cmd addr_hi addr_lo len [params] crc_hi crc_lo      (len 0 means 256)
    response: 0x2E cmd addr_hi addr_lo len [params] ack crc_hi crc_lo  (CRC also covers ack)

SAFETY: the ESCs only answer when the battery is connected. Take the propellers off. Entering the
interface disables the motor outputs; leaving it gives them back to the FC.
"""

from __future__ import annotations

import re
import time
from collections import Counter
from typing import Any, Dict, List, NamedTuple, Optional

from .msp import MSP_SET_PASSTHROUGH, MspClient, MspError

CMD_TEST_ALIVE = 0x30
CMD_PROTOCOL_VERSION = 0x31
CMD_INTERFACE_NAME = 0x32
CMD_EXIT = 0x34
CMD_DEVICE_RESET = 0x35
CMD_INIT_FLASH = 0x37
CMD_DEVICE_READ = 0x3A

ACK_OK = 0x00
ACK_D_GENERAL_ERROR = 0x0F

MODE_SIL_BLB = 1  # SiLabs EFM8 (BLHeli_S, Bluejay)
MODE_ARM_BLB = 4  # ARM (AM32, BLHeli_32)

# signature -> (name, EEPROM address); from esc-configurator Hardware/Silabs.js and Arm.js
SILABS_MCUS = {0xE8B1: ("EFM8BB10x", 0x1A00), 0xE8B2: ("EFM8BB21x", 0x1A00), 0xE8B5: ("EFM8BB51x", 0x3000)}
ARM_MCUS = {0x1F06: ("STM32F051", 0x7C00), 0x3506: ("ARM64K", 0xF800)}
AM32_BOOT_PINS = (0x02, 0x14, 0x06)  # sources/AM32/eeprom.js BOOT_LOADER_PINS

# SiLabs EEPROM (BLHeli_S and Bluejay share the start of the layout)
SILABS_LAYOUT_SIZE = 0x70
# AM32 EEPROM
AM32_LAYOUT_SIZE = 0xB0


class FourWayError(Exception):
    pass


class FourWayAck(FourWayError):
    def __init__(self, cmd: int, ack: int) -> None:
        super().__init__("4-way command 0x%02X refused (ack 0x%02X)" % (cmd, ack))
        self.cmd, self.ack = cmd, ack


class Response(NamedTuple):
    cmd: int
    address: int
    params: bytes
    ack: int


def crc16_xmodem(data: bytes, crc: int = 0) -> int:
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def encode(cmd: int, params: bytes = b"", address: int = 0) -> bytes:
    if len(params) > 256:
        raise ValueError("too many parameters")
    if not params:
        params = b"\x00"  # the FC always reads at least one parameter byte
    head = bytes([0x2F, cmd, address >> 8 & 0xFF, address & 0xFF, len(params) & 0xFF])
    body = head + params
    return body + crc16_xmodem(body).to_bytes(2, "big")


class FourWay:
    """Request/response over a pyserial-like object already switched to the 4-way interface."""

    def __init__(self, ser, timeout: float = 1.0) -> None:
        self.ser = ser
        self.timeout = timeout

    def _read(self, n: int, deadline: float) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            if time.monotonic() > deadline:
                raise FourWayError("timeout waiting for the 4-way interface")
            buf += self.ser.read(min(n - len(buf), self.ser.in_waiting or 1))
        return bytes(buf)

    def request(self, cmd: int, params: bytes = b"", address: int = 0, timeout: Optional[float] = None) -> Response:
        self.ser.reset_input_buffer()
        self.ser.write(encode(cmd, params, address))
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        while self._read(1, deadline) != b"\x2e":
            pass
        head = self._read(4, deadline)  # cmd, addr_hi, addr_lo, len
        n = head[3] or 256
        rest = self._read(n + 3, deadline)  # params, ack, crc_hi, crc_lo
        body = b"\x2e" + head + rest[: n + 1]
        if crc16_xmodem(body) != int.from_bytes(rest[n + 1 :], "big"):
            raise FourWayError("bad CRC from the 4-way interface")
        if head[0] != cmd:
            raise FourWayError("answer to another command (0x%02X)" % head[0])
        resp = Response(cmd, head[1] << 8 | head[2], rest[:n], rest[n])
        if resp.ack != ACK_OK:
            raise FourWayAck(cmd, resp.ack)
        return resp

    def read(self, address: int, length: int) -> bytes:
        return self.request(CMD_DEVICE_READ, bytes([0 if length == 256 else length]), address).params


# ------------------------------------------------------------------ parsing


def _ascii(b: bytes) -> str:
    return b.split(b"\x00")[0].decode("ascii", "replace").strip()


def read_esc(fw: FourWay, index: int, retries: int = 3) -> Dict[str, Any]:
    """Identify one ESC (0-based ``index``). Raises FourWayError if it does not answer."""
    last: Optional[Exception] = None
    for _ in range(retries):
        try:
            info = fw.request(CMD_INIT_FLASH, bytes([index]), 0, timeout=2.0).params
            break
        except FourWayError as e:  # ESC not (yet) in its bootloader: try again
            last = e
    else:
        raise FourWayError(str(last))
    if len(info) < 4:
        raise FourWayError("short device info")
    signature = info[1] << 8 | info[0]
    pin, mode = info[2], info[3]
    esc: Dict[str, Any] = {
        "index": index + 1,
        "signature": "0x%04X" % signature,
        "interface_mode": mode,
        "firmware": "unknown",
    }

    if mode == MODE_SIL_BLB:
        mcu = SILABS_MCUS.get(signature)
        if mcu is None:
            return esc
        esc["mcu"] = mcu[0]
        data = fw.read(mcu[1], SILABS_LAYOUT_SIZE)
        main, sub = data[0], data[1]
        name = _ascii(data[0x60:0x70])
        esc.update(
            main_revision=main,
            sub_revision=sub,
            version="%d.%d" % (main, sub),
            layout_revision=data[2],
            layout=_ascii(data[0x40:0x50]),
            mcu_tag=_ascii(data[0x50:0x60]),
            name=name,
        )
        if re.search(r"Bluejay", name):
            esc["firmware"] = "Bluejay"
        elif name == "" and main == 16 and sub in (8, 9):
            esc["firmware"] = "BLHeli_M"  # esc-configurator's own guess, by version
        else:
            esc["firmware"] = "BLHeli_S"  # what esc-configurator assumes for any other SiLabs ESC
    elif mode == MODE_ARM_BLB:
        mcu = ARM_MCUS.get(signature)
        if mcu is None:
            return esc
        esc["mcu"] = mcu[0]
        data = fw.read(mcu[1], AM32_LAYOUT_SIZE)
        esc.update(
            main_revision=data[3],
            sub_revision=data[4],
            version="%d.%d" % (data[3], data[4]),
            layout_revision=data[1],
            bootloader_revision=data[2],
            name=_ascii(data[5:17]),
        )
        if pin in AM32_BOOT_PINS:
            esc["firmware"] = "AM32"
            try:  # the build's file name sits just before the settings; absent on old versions
                fname = _ascii(fw.read(mcu[1] - 32, 16))
                if re.fullmatch(r"[A-Z0-9_]+", fname):
                    esc["file_name"] = fname
            except FourWayError:
                pass
        else:
            esc["firmware"] = "not AM32 (probably BLHeli_32, not readable)"
    return esc


def describe(esc: Dict[str, Any]) -> str:
    """One line per ESC, also stored in the configuration snapshot."""
    if esc.get("error"):
        return "esc %d: not read (%s)" % (esc["index"], esc["error"])
    parts = [esc["firmware"]]
    if esc.get("version"):
        parts.append(esc["version"])
    if esc.get("mcu"):
        parts.append("on " + esc["mcu"])
    extra = [
        '%s "%s"' % (k, esc[k]) for k in ("layout", "name", "file_name") if esc.get(k)
    ]
    return "esc %d: %s%s" % (esc["index"], " ".join(parts), (", " + ", ".join(extra)) if extra else "")


def summary(escs: List[Dict[str, Any]]) -> str:
    """Short text for the component hint, e.g. ``4x Bluejay 0.21 (EFM8BB21x)``."""
    ok = Counter(
        (e["firmware"], e.get("version", ""), e.get("mcu", "")) for e in escs if not e.get("error")
    )
    parts = ["%dx %s" % (n, " ".join(x for x in (fw, ver) if x) + (" (%s)" % mcu if mcu else "")) for (fw, ver, mcu), n in ok.items()]
    failed = sum(1 for e in escs if e.get("error"))
    if failed:
        parts.append("%d not read" % failed)
    return ", ".join(parts)


# -------------------------------------------------------------------- driver


def read_escs(ser, msp_timeout: float = 1.0, timeout: float = 1.0) -> Dict[str, Any]:
    """Switch the FC to the 4-way interface, read every ESC, put everything back.

    Returns ``{"escs": [...], "interface": {"protocol": int, "name": str}}``. Raises FourWayError if
    the interface cannot be entered; per-ESC failures are reported inside the list (``error``).
    """
    try:
        payload = MspClient(ser, msp_timeout).request(MSP_SET_PASSTHROUGH)
    except MspError as e:
        raise FourWayError("the FC does not offer the ESC 4-way interface: %s" % e) from e
    count = payload[0] if payload else 0
    if count == 0:
        raise FourWayError("the FC reports no ESC (motor outputs not configured?)")

    fw = FourWay(ser, timeout)
    escs: List[Dict[str, Any]] = []
    interface: Dict[str, Any] = {}
    entered: List[int] = []
    try:
        interface["protocol"] = fw.request(CMD_PROTOCOL_VERSION).params[0]
        interface["name"] = _ascii(fw.request(CMD_INTERFACE_NAME).params)
        for i in range(count):
            try:
                entered.append(i)
                escs.append(read_esc(fw, i))
            except FourWayError as e:
                escs.append({"index": i + 1, "firmware": "unknown", "error": "no answer (battery connected?)" if not isinstance(e, FourWayAck) else str(e)})
    finally:
        for i in entered:  # let each ESC run its firmware again
            try:
                fw.request(CMD_DEVICE_RESET, bytes([i]), 0)
            except FourWayError:
                pass
        try:
            fw.request(CMD_EXIT, timeout=0.5)
        except FourWayError:
            pass
    return {"escs": escs, "interface": interface}
