"""A fake flight controller behind a pyserial-like object: MSP v1 + a tiny text CLI."""

import struct
import time

from fleetmanager.msp import (
    MSP_API_VERSION,
    MSP_BOARD_INFO,
    MSP_BUILD_INFO,
    MSP_FC_VARIANT,
    MSP_FC_VERSION,
    MSP_NAME,
    MSP_STATUS,
    MSP_UID,
    MSP_VTX_CONFIG,
)

DIFF_ALL = """# diff all

# version
# Betaflight / STM32G47X (S7X4) 4.5.1 Jan  1 2025 / 10:00:00 (abcdef0) MSP API: 1.46

# start the command batch
batch start

board_name SPEEDYBEEF7V3
set motor_pwm_protocol = DSHOT600
set name = Racer

batch end
"""

STATUS = """System Uptime: 12 seconds
CPU:5%, cycle time: 125, GYRO rate: 8000
I2C Errors: 0, config size: 4286
GYRO=ICM42688P, ACC=ICM42688P, BARO=DPS310, MAG=NONE"""

SETTINGS = {
    "serialrx_provider": "CRSF",
    "motor_pwm_protocol": "DSHOT600",
    "motor_poles": "14",
    "gps_provider": "UBLOX",
    "mag_hardware": "AUTO",
    "opflow_hardware": "NONE",
}


def v1_response(code, payload=b"", direction=b">"):
    body = bytes([len(payload), code]) + payload
    checksum = 0
    for b in body:
        checksum ^= b
    return b"$M" + direction + body + bytes([checksum])


class FakeFC:
    def __init__(self, diff=DIFF_ALL, cli=True, msp=True, uid=bytes(range(1, 13)), vtx=True):
        self.out = bytearray()
        self._in = bytearray()
        self.cli_enabled = cli
        self.msp_enabled = msp
        self.in_cli = False
        self.exited = False
        self.closed = False
        self.diff = diff
        self.replies = {
            MSP_API_VERSION: bytes([0, 1, 46]),
            MSP_FC_VARIANT: b"BTFL",
            MSP_FC_VERSION: bytes([4, 5, 1]),
            MSP_BOARD_INFO: b"S7X4" + struct.pack("<H", 0) + bytes([0, 0, 13]) + b"SPEEDYBEEF7V3",
            MSP_BUILD_INFO: b"Jan  1 2025" + b"10:00:00" + b"abcdef0",
            MSP_NAME: b"Racer",
            MSP_UID: uid,
            # cycle time, i2c errors, sensors: acc + baro + gps
            MSP_STATUS: struct.pack("<HHH", 125, 0, 0b1011) + bytes(8),
        }
        if vtx:
            self.replies[MSP_VTX_CONFIG] = bytes([3, 4, 2, 2, 0]) + struct.pack("<H", 5760) + bytes(2)

    # pyserial-like surface -------------------------------------------------
    @property
    def in_waiting(self):
        return len(self.out)

    def reset_input_buffer(self):
        self.out.clear()

    def close(self):
        self.closed = True

    def read(self, size=1):
        if not self.out:
            time.sleep(0.001)
            return b""
        data = bytes(self.out[:size])
        del self.out[:size]
        return data

    def write(self, data):
        self._in += data
        self._process()

    # behaviour ---------------------------------------------------------------
    def _process(self):
        if self.in_cli:
            while b"\n" in self._in:
                line, _, rest = bytes(self._in).partition(b"\n")
                self._in = bytearray(rest)
                self._cli(line.decode().strip())
            return
        while self._in:
            if self._in[:1] == b"#":
                del self._in[:1]
                if self.cli_enabled:
                    self.in_cli = True
                    self.out += b"\r\nEntering CLI Mode, type 'exit' to return, or 'help'\r\n\r\n# "
                continue
            if self._in[:3] == b"$M<" and len(self._in) >= 4 and len(self._in) >= self._in[3] + 6:
                size, code = self._in[3], self._in[4]
                del self._in[: size + 6]
                if self.msp_enabled:
                    if code in self.replies:
                        self.out += v1_response(code, self.replies[code])
                    else:
                        self.out += v1_response(code, b"", b"!")
                continue
            if self._in[:1] not in (b"$", b"M", b"<"):
                del self._in[:1]
                continue
            break

    def _cli(self, cmd):
        if cmd == "exit":
            self.exited = True
            self.in_cli = False
            return
        body = ""
        if cmd == "status":
            body = STATUS
        elif cmd == "diff all":
            body = self.diff
        elif cmd.startswith("get "):
            name = cmd[4:]
            if name in SETTINGS:
                body = "%s = %s\r\nAllowed values: whatever" % (name, SETTINGS[name])
            else:
                body = "Invalid name"
        self.out += (cmd + "\r\n" + body.replace("\n", "\r\n") + "\r\n\r\n# ").encode()
