"""A simulated flight controller (MSP v1, text CLI, ESC 4-way interface) behind a pyserial-like object.

Used by the tests and by ``fleetmanager serve --simulate`` to try the app without hardware.
"""

import struct
import time

from fleetmanager.esc import crc16_xmodem
from fleetmanager.msp import (
    MSP_API_VERSION,
    MSP_BOARD_INFO,
    MSP_BUILD_INFO,
    MSP_FC_VARIANT,
    MSP_FC_VERSION,
    MSP_NAME,
    MSP_SET_PASSTHROUGH,
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


def _pad(text, n):
    return text.encode().ljust(n, b" ")[:n]


def bluejay_esc(name="Bluejay (BETA)", main=0, sub=21, signature=0xE8B2, responds=True):
    """A SiLabs EFM8BB21 ESC as the bootloader shows it (layout from esc-configurator)."""
    mem = bytearray(b"\xff" * 0x10000)
    data = bytearray(0x70)
    data[0], data[1], data[2] = main, sub, 0x21
    data[0x40:0x50] = _pad("#S_H_90#", 16)
    data[0x50:0x60] = _pad("#BLHELI$EFM8B21#", 16)
    data[0x60:0x70] = _pad(name, 16)
    mem[0x1A00:0x1A70] = data
    return {"sig": signature, "mode": 1, "pin": 0, "mem": mem, "responds": responds}


def am32_esc(main=2, sub=16, name="AM32", filename=b"TEKKO32_F051", pin=0x02):
    mem = bytearray(b"\xff" * 0x10000)
    base = 0x7C00
    data = bytearray(0xB0)
    data[1], data[2], data[3], data[4] = 2, 6, main, sub
    data[5:17] = _pad(name, 12)
    mem[base : base + 0xB0] = data
    mem[base - 32 : base - 16] = filename.ljust(16, b"\x00")
    return {"sig": 0x1F06, "mode": 4, "pin": pin, "mem": mem, "responds": True}


class FakeFC:
    def __init__(self, diff=DIFF_ALL, cli=True, msp=True, uid=bytes(range(1, 13)), vtx=True, escs=None):
        self.out = bytearray()
        self._in = bytearray()
        self.cli_enabled = cli
        self.msp_enabled = msp
        self.in_cli = False
        self.exited = False
        self.closed = False
        self.escs = escs
        self.in_4way = False
        self.left_4way = False
        self.reset_log = []
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
        if self.in_4way:
            self._fourway()
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
                    if code == MSP_SET_PASSTHROUGH and self.escs is not None:
                        self.out += v1_response(code, bytes([len(self.escs)]))
                        self.in_4way = True
                        self._fourway()  # bytes may already follow
                        return
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

    # ESC 4-way interface ------------------------------------------------------
    def _fourway_reply(self, cmd, address, params, ack=0):
        params = params or b"\x00"
        body = bytes([0x2E, cmd, address >> 8, address & 0xFF, len(params) & 0xFF]) + params + bytes([ack])
        self.out += body + crc16_xmodem(body).to_bytes(2, "big")

    def _fourway(self):
        while self.in_4way:
            buf = self._in
            while buf and buf[0] != 0x2F:
                del buf[0]
            if len(buf) < 5:
                return
            plen = buf[4] or 256
            if len(buf) < 5 + plen + 2:
                return
            frame = bytes(buf[: 5 + plen + 2])
            del buf[: 5 + plen + 2]
            if crc16_xmodem(frame[:-2]) != int.from_bytes(frame[-2:], "big"):
                self._fourway_reply(frame[1], 0, b"", 0x03)
                continue
            cmd, address, params = frame[1], frame[2] << 8 | frame[3], frame[5:-2]
            if cmd == 0x31:
                self._fourway_reply(cmd, address, bytes([108]))
            elif cmd == 0x32:
                self._fourway_reply(cmd, address, b"m4wFCIntf")
            elif cmd == 0x37:
                idx = params[0]
                if idx >= len(self.escs):
                    self._fourway_reply(cmd, address, b"", 0x08)
                    continue
                esc = self.escs[idx]
                self.selected = idx
                if esc["responds"]:
                    self._fourway_reply(cmd, address, bytes([esc["sig"] & 0xFF, esc["sig"] >> 8, esc["pin"], esc["mode"]]))
                else:
                    self._fourway_reply(cmd, address, bytes([0, 0, 100, 1]), 0x0F)
            elif cmd == 0x3A:
                n = params[0] or 256
                mem = self.escs[self.selected]["mem"]
                self._fourway_reply(cmd, address, bytes(mem[address : address + n]))
            elif cmd == 0x35:
                self.reset_log.append(params[0])
                self._fourway_reply(cmd, address, b"")
            elif cmd == 0x34:
                self._fourway_reply(cmd, address, b"")
                self.in_4way = False
                self.left_4way = True
            else:
                self._fourway_reply(cmd, address, b"", 0x02)


# --------------------------------------------------------------------- demo fleet

DEMO_DIFF = """# diff all

# version
# {fw} / {board} ({bid}) {ver} {date} / 10:00:00 (abcdef0) MSP API: 1.46

# start the command batch
batch start

board_name {board}

# feature
feature GPS
feature TELEMETRY

# serial
serial 20 1 115200 57600 0 115200
serial 1 64 115200 57600 0 115200
serial 2 2 115200 57600 0 115200

# master
set gyro_lpf1_static_hz = {lpf}
set dyn_notch_count = {notch}
set motor_pwm_protocol = DSHOT{dshot}
set dshot_bidir = ON
set motor_poles = 14
set vbat_min_cell_voltage = {vmin}
set gps_provider = UBLOX
set gps_sbas_mode = EGNOS
set osd_displayport_device = MSP
set name = {name}

profile 0
set p_pitch = {p}
set i_pitch = 80
set d_pitch = {d}

rateprofile 0
set roll_srate = 70
set pitch_srate = 70

batch end
"""

DEMO_FLEET = [
    dict(name="Chimera7", fw=b"BTFL", ver=(4, 5, 1), bid=b"S7X4", board="SPEEDYBEEF7V3", uid=bytes(range(10, 22)),
         escs=lambda rev: [bluejay_esc(sub=21 if rev < 3 else 22) for _ in range(4)]),
    dict(name="Lumenier5", fw=b"INAV", ver=(7, 1, 2), bid=b"MKF4", board="MATEKF405", uid=bytes(range(40, 52)),
         escs=lambda rev: [am32_esc(main=2, sub=16) for _ in range(4)]),
    dict(name="Whoop65", fw=b"BTFL", ver=(4, 4, 3), bid=b"S411", board="CRAZYBEEF4SX1280", uid=bytes(range(70, 82)),
         escs=lambda rev: [bluejay_esc(sub=19) for _ in range(4)]),
]


def demo_fc(profile, revision=0):
    """A simulated FC for one of the demo drones; ``revision`` changes its tune over time."""
    fw_name = "Betaflight" if profile["fw"] == b"BTFL" else "INAV"
    ver = "%d.%d.%d" % profile["ver"]
    diff = DEMO_DIFF.format(
        fw=fw_name, board=profile["board"], bid=profile["bid"].decode(), ver=ver, date="Mar 12 2025",
        name=profile["name"], lpf=250 - 25 * min(revision, 3), notch=1 + min(revision, 2) // 2,
        dshot=600 if revision % 4 < 2 else 300, vmin=330 + 5 * (revision // 2 % 2),
        p=47 + revision, d=38 + 2 * (revision // 2),
    )
    fc = FakeFC(diff=diff, uid=profile["uid"], escs=profile["escs"](revision))
    name = profile["board"].encode()
    fc.replies.update({
        MSP_FC_VARIANT: profile["fw"],
        MSP_FC_VERSION: bytes(profile["ver"]),
        MSP_BOARD_INFO: profile["bid"] + struct.pack("<H", 0) + bytes([0, 0, len(name)]) + name,
        MSP_NAME: profile["name"].encode(),
    })
    return fc


class DemoScanner:
    """Each call plugs the next demo drone in; every drone's tune evolves a little between visits."""

    def __init__(self):
        self.calls = 0

    def __call__(self, port, cli, esc):
        from .detect import detect

        profile = DEMO_FLEET[self.calls % len(DEMO_FLEET)]
        revision = self.calls // len(DEMO_FLEET)
        self.calls += 1
        det = detect(demo_fc(profile, revision), with_cli=cli, with_esc=esc, timeout=0.3, cli_timeout=1.0)
        det.info["port"] = "simulated"
        return det
