"""Minimal MSP (MultiWii Serial Protocol) client: v1/v2 framing and request/response.

Frames (little endian):

    v1: '$' 'M' dir size cmd payload checksum          checksum = xor(size, cmd, payload)
    v2: '$' 'X' dir flags cmd(2) size(2) payload crc8  crc8 = DVB-S2 (poly 0xD5) over flags..payload

``dir`` is '<' for a request, '>' for a response and '!' when the FC does not support the command.
"""

from __future__ import annotations

import struct
import time
from typing import NamedTuple, Optional

MSP_API_VERSION = 1
MSP_FC_VARIANT = 2
MSP_FC_VERSION = 3
MSP_BOARD_INFO = 4
MSP_BUILD_INFO = 5
MSP_NAME = 10
MSP_STATUS = 101
MSP_VTX_CONFIG = 88
MSP_UID = 160


class MspError(Exception):
    pass


class MspTimeout(MspError):
    pass


class MspUnsupported(MspError):
    """The FC answered '!' : the command is not implemented by this firmware."""


def crc8_dvb_s2(data: bytes, crc: int = 0) -> int:
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ 0xD5) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def encode_v1(code: int, payload: bytes = b"") -> bytes:
    if not 0 <= code <= 255 or len(payload) > 255:
        raise ValueError("code/payload too large for MSP v1")
    body = bytes([len(payload), code]) + payload
    checksum = 0
    for b in body:
        checksum ^= b
    return b"$M<" + body + bytes([checksum])


def encode_v2(code: int, payload: bytes = b"") -> bytes:
    body = struct.pack("<BHH", 0, code, len(payload)) + payload
    return b"$X<" + body + bytes([crc8_dvb_s2(body)])


class Frame(NamedTuple):
    direction: str  # '<', '>' or '!'
    code: int
    payload: bytes
    version: int  # 1 or 2


class Parser:
    """Streaming parser: feed bytes one at a time, get a Frame when one is complete and valid."""

    def __init__(self) -> None:
        self.crc_errors = 0
        self._restart()

    def _restart(self) -> None:
        self._state = "idle"
        self._buf = bytearray()
        self._version = 0
        self._dir = ""

    def _resync(self, c: int) -> None:
        """Drop a broken header; a '$' may already be the start of the next frame."""
        self._restart()
        if c == 0x24:
            self._state = "proto"

    def feed(self, c: int) -> Optional[Frame]:
        st = self._state
        if st == "idle":
            if c == 0x24:  # '$'
                self._state = "proto"
            return None
        if st == "proto":
            if c in (ord("M"), ord("X")):
                self._version = 1 if c == ord("M") else 2
                self._state = "dir"
            else:
                self._resync(c)
            return None
        if st == "dir":
            if c in (ord("<"), ord(">"), ord("!")):
                self._dir = chr(c)
                self._buf = bytearray()
                self._state = "body"
            else:
                self._resync(c)
            return None
        # body
        buf = self._buf
        buf.append(c)
        if self._version == 1:
            if len(buf) < buf[0] + 3:
                return None
            checksum = 0
            for b in buf[:-1]:
                checksum ^= b
            ok = checksum == buf[-1]
            frame = Frame(self._dir, buf[1], bytes(buf[2:-1]), 1)
        else:
            if len(buf) < 5 or len(buf) < 5 + struct.unpack_from("<H", buf, 3)[0] + 1:
                return None
            ok = crc8_dvb_s2(bytes(buf[:-1])) == buf[-1]
            frame = Frame(self._dir, struct.unpack_from("<H", buf, 1)[0], bytes(buf[5:-1]), 2)
        self._restart()
        if not ok:
            self.crc_errors += 1
            return None
        return frame


class MspClient:
    """Synchronous request/response over a pyserial-like object (write/read/in_waiting)."""

    def __init__(self, ser, timeout: float = 1.0) -> None:
        self.ser = ser
        self.timeout = timeout

    def request(self, code: int, payload: bytes = b"", timeout: Optional[float] = None) -> bytes:
        self.ser.reset_input_buffer()
        self.ser.write(encode_v1(code, payload))
        parser = Parser()
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        while time.monotonic() < deadline:
            for b in self.ser.read(self.ser.in_waiting or 1):
                frame = parser.feed(b)
                if frame and frame.direction in (">", "!") and frame.code == code:
                    if frame.direction == "!":
                        raise MspUnsupported("MSP command %d not supported" % code)
                    return frame.payload
        raise MspTimeout("no answer to MSP command %d" % code)
