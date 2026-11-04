"""Event sources: the real tracker on a serial port, a built-in flight simulator, and log replay."""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

import serial
import serial.tools.list_ports

from . import geo
from .state import State

log = logging.getLogger("esptracker.sources")

ALLOWED_VERBS = {"HELP", "PING", "STATUS", "BIND", "UID", "HOME", "MODE", "AIM", "SET", "SAVE", "FACTORY", "REBOOT"}
MAX_COMMAND_LEN = 100


def validate_command(line: str) -> str:
    """Return a cleaned command line or raise ValueError. Commands are sent verbatim to the tracker."""
    if not isinstance(line, str):
        raise ValueError("command must be a string")
    if "\n" in line or "\r" in line or "\x00" in line:
        raise ValueError("command must be a single line")
    line = line.strip()
    if not line:
        raise ValueError("empty command")
    if len(line) > MAX_COMMAND_LEN:
        raise ValueError("command too long")
    verb = line.split(None, 1)[0].upper()
    if verb not in ALLOWED_VERBS:
        raise ValueError("unknown command '%s'" % verb[:20])
    return line


class Source:
    """Base class. Subclasses push events into `state` from their own thread."""

    name = "source"
    read_only = False

    def __init__(self, state: State) -> None:
        self.state = state
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name=self.name, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def send(self, line: str) -> None:
        """Send a (validated) command line to the tracker."""
        raise NotImplementedError

    def _run(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError


# ---------------------------------------------------------------------------------------------------
# Serial
# ---------------------------------------------------------------------------------------------------

# USB vendor ids of the usual ESP32 boards: Espressif native USB, Silabs CP210x, WCH CH34x, FTDI
KNOWN_VIDS = {0x303A, 0x10C4, 0x1A86, 0x0403}


def find_port() -> Optional[str]:
    candidates = [p for p in serial.tools.list_ports.comports() if p.vid in KNOWN_VIDS]
    candidates.sort(key=lambda p: p.device)
    if not candidates:
        return None
    if len(candidates) > 1:
        log.warning("several candidate serial ports: %s - using %s", [p.device for p in candidates], candidates[0].device)
    return candidates[0].device


def open_serial(port: str, baud: int) -> serial.Serial:
    ser = serial.serial_for_url(port, baudrate=baud, timeout=0.2, do_not_open=True)
    # Do not pulse DTR/RTS on open: on classic ESP32 boards that resets the chip, on native-USB boards
    # it can drop it into the bootloader.
    ser.dtr = False
    ser.rts = False
    ser.open()
    return ser


class SerialSource(Source):
    name = "serial"

    def __init__(
        self,
        state: State,
        port: str = "auto",
        baud: int = 115200,
        on_connect: Sequence[str] = (),
        retry_s: float = 2.0,
    ) -> None:
        super().__init__(state)
        self.port = port
        self.baud = baud
        self.on_connect = list(on_connect)
        self.retry_s = retry_s
        self._ser: Optional[serial.Serial] = None
        self._wlock = threading.Lock()

    def send(self, line: str) -> None:
        with self._wlock:
            ser = self._ser
            if ser is None:
                raise ConnectionError("tracker is not connected")
            ser.write((line + "\n").encode("ascii", "replace"))
            ser.flush()

    def _run(self) -> None:
        while not self._stop.is_set():
            port = find_port() if self.port == "auto" else self.port
            label = "serial:%s" % (port or "auto")
            if port is None:
                self.state.set_link(label, False, "no tracker found (plug it in or pass --port)")
                self._stop.wait(self.retry_s)
                continue
            try:
                ser = open_serial(port, self.baud)
            except (serial.SerialException, OSError, ValueError) as exc:
                self.state.set_link(label, False, str(exc))
                self._stop.wait(self.retry_s)
                continue

            log.info("connected to %s @ %d", port, self.baud)
            with self._wlock:
                self._ser = ser
            self.state.set_link(label, True)
            error = None
            try:
                for cmd in ["STATUS"] + self.on_connect:
                    self.send(cmd)
                self._read_loop(ser)
            except (serial.SerialException, OSError) as exc:
                error = str(exc)
                log.warning("serial error: %s", exc)
            finally:
                with self._wlock:
                    self._ser = None
                try:
                    ser.close()
                except Exception:  # noqa: BLE001
                    pass
                self.state.set_link(label, False, error or "disconnected")
            self._stop.wait(self.retry_s)

    def _read_loop(self, ser: serial.Serial) -> None:
        buf = bytearray()
        while not self._stop.is_set():
            chunk = ser.read(ser.in_waiting or 1)
            if not chunk:
                continue
            buf.extend(chunk)
            while True:
                nl = buf.find(b"\n")
                if nl < 0:
                    break
                line = bytes(buf[:nl]).decode("utf-8", "replace")
                del buf[: nl + 1]
                self.state.ingest_line(line)
            if len(buf) > 4096:  # runaway garbage without newline
                del buf[:]


# ---------------------------------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------------------------------


class SimulatorSource(Source):
    """Fake tracker + drone: a lap on a circle with realistic telemetry. Implements the same command
    set as the firmware so the whole UI can be exercised without hardware."""

    name = "simulator"

    def __init__(
        self,
        state: State,
        center: Sequence[float] = (48.8566, 2.3522),
        radius_m: float = 400.0,
        speed_ms: float = 14.0,
        time_scale: float = 1.0,
        on_connect: Sequence[str] = (),
    ) -> None:
        super().__init__(state)
        self.on_connect = list(on_connect)
        self.center = (float(center[0]), float(center[1]))
        self.radius = radius_m
        self.speed = speed_ms
        self.time_scale = time_scale
        self._lock = threading.Lock()
        self._t0 = time.monotonic()
        self._mapper = geo.AimMapper()
        self.cfg: Dict[str, Any] = {
            "uid": None,
            "home": False,
            "hlat": 0.0,
            "hlon": 0.0,
            "halt": 0.0,
            "offset": 0.0,
            "hyst": 3.0,
            "slew": 120,
            "pan_min_us": 500,
            "pan_max_us": 2500,
            "tilt_min_us": 500,
            "tilt_max_us": 2500,
            "pan_invert": 0,
            "tilt_invert": 0,
            "min_sats": 6,
            "lost_ms": 5000,
        }
        self.mode = "auto"
        self.manual = (90.0, 0.0)
        self.counters = {"espnow": 0, "msp_ok": 0, "msp_bad": 0, "crsf_ok": 0, "crsf_bad": 0, "crsf_other": 0}
        self._drone: Dict[str, float] = {}

    # -- drone model ------------------------------------------------------------------------------

    def _sim_time(self) -> float:
        return (time.monotonic() - self._t0) * self.time_scale

    def drone_at(self, t: float) -> Dict[str, float]:
        omega = self.speed / self.radius
        ang = omega * t
        east, north = self.radius * math.sin(ang), self.radius * math.cos(ang)
        lat, lon = geo.offset_position(self.center[0], self.center[1], east, north)
        heading = geo.wrap360(math.degrees(ang) + 90.0)
        alt = 120.0 + 45.0 * math.sin(t / 18.0)
        vs = 45.0 / 18.0 * math.cos(t / 18.0)
        return {
            "t": t,
            "lat": lat,
            "lon": lon,
            "alt": alt,
            "vs": vs,
            "speed_kmh": self.speed * 3.6,
            "heading": heading,
            "roll": 25.0 * math.sin(t / 5.0),
            "pitch": 8.0 * math.sin(t / 3.0),
        }

    # -- commands (same behaviour as the firmware) -------------------------------------------------

    def send(self, line: str) -> None:
        parts = line.split()
        verb = parts[0].upper()
        ev = self.state.ingest
        try:
            with self._lock:
                if verb == "HOME" and len(parts) == 4:
                    self.cfg.update(home=True, hlat=float(parts[1]), hlon=float(parts[2]), halt=float(parts[3]))
                elif verb == "HOME" and len(parts) == 2 and parts[1].upper() == "DRONE":
                    d = self._drone or self.drone_at(self._sim_time())
                    self.cfg.update(home=True, hlat=d["lat"], hlon=d["lon"], halt=float(round(d["alt"])))
                elif verb == "HOME" and len(parts) == 2 and parts[1].upper() == "CLEAR":
                    self.cfg["home"] = False
                elif verb == "MODE" and len(parts) == 2:
                    self.mode = parts[1].lower()
                elif verb == "AIM" and len(parts) == 3:
                    self.mode = "manual"
                    self.manual = (float(parts[1]), float(parts[2]))
                elif verb == "SET" and len(parts) == 3:
                    key = parts[1].lower()
                    if key not in self.cfg or key in ("uid", "home", "hlat", "hlon", "halt"):
                        ev({"e": "err", "msg": "unknown key '%s'" % key[:20]})
                        return
                    self.cfg[key] = float(parts[2])
                elif verb in ("BIND", "UID"):
                    self.cfg["uid"] = "3b933b37b1e4"
        except ValueError:
            ev({"e": "err", "msg": "bad arguments"})
            return
        if verb == "STATUS":
            self._emit_status()
            return
        if verb == "HELP":
            ev({"e": "help", "text": "simulator: commands are accepted like on the real tracker"})
            return
        name = verb
        if verb in ("HOME", "MODE") and len(parts) == 2:
            name = "%s %s" % (verb, parts[1].upper())
        ev({"e": "ack", "cmd": name})

    # -- event generation -------------------------------------------------------------------------

    def _emit_status(self) -> None:
        self._emit_hello()
        self.state.ingest(dict(e="cfg", **self.cfg))
        self._emit_trk(self._drone)
        self._emit_stat()

    def _emit_hello(self) -> None:
        self.state.ingest(
            {"e": "hello", "fw": "sim", "chip": "SIMULATOR", "uid": self.cfg["uid"], "espnow": True}
        )

    def _emit_stat(self) -> None:
        self.state.ingest(dict(e="stat", **self.counters, dropped=0))

    def _emit_trk(self, d: Dict[str, float]) -> None:
        cfg = self.cfg
        trk: Dict[str, Any] = {
            "e": "trk",
            "mode": self.mode,
            "home": bool(cfg["home"]),
            "hlat": cfg["hlat"],
            "hlon": cfg["hlon"],
            "halt": cfg["halt"],
            "gps_age": 0 if d else -1,
            "az": None,
            "el": None,
            "dist": None,
            "dist3d": None,
        }
        pan, tilt, flipped = 90.0, 0.0, False
        if cfg["home"] and d:
            az = geo.bearing_deg(cfg["hlat"], cfg["hlon"], d["lat"], d["lon"])
            dist = geo.distance_m(cfg["hlat"], cfg["hlon"], d["lat"], d["lon"])
            dalt = d["alt"] - cfg["halt"]
            el = geo.elevation_deg(dist, dalt)
            trk.update(az=round(az, 1), el=round(el, 1), dist=round(dist, 1), dist3d=round(math.hypot(dist, dalt), 1))
            if self.mode == "auto":
                pan, tilt, flipped = self._mapper.map(az, el, cfg["offset"], cfg["hyst"])
        if self.mode == "manual":
            pan, tilt = self.manual
        trk.update(
            tracking=bool(cfg["home"] and d and self.mode == "auto"),
            pan=round(pan, 1),
            tilt=round(tilt, 1),
            tpan=round(pan, 1),
            ttilt=round(tilt, 1),
            flip=flipped,
        )
        self.state.ingest(trk)

    def _run(self) -> None:
        tick = 0.1
        step = 0
        self.state.set_link("simulator", True)
        self._emit_status()
        for cmd in self.on_connect:
            self.send(cmd)
        while not self._stop.is_set():
            t = self._sim_time()
            d = self.drone_at(t)
            self._drone = d
            ev = self.state.ingest
            sats = 14 if t > 3 else 7

            # 10 Hz attitude, 5 Hz GPS ... emitted on a shared tick
            ev({"e": "att", "pitch": round(d["pitch"], 1), "roll": round(d["roll"], 1), "yaw": round((d["heading"] + 180.0) % 360.0 - 180.0, 1)})
            if step % 2 == 0:
                ev(
                    {
                        "e": "gps",
                        "lat": round(d["lat"], 7),
                        "lon": round(d["lon"], 7),
                        "alt": int(round(d["alt"])),
                        "gs": round(d["speed_kmh"], 1),
                        "hdg": round(d["heading"], 1),
                        "sats": sats,
                    }
                )
                self.counters["crsf_ok"] += 1
                self.counters["msp_ok"] += 1
                self.counters["espnow"] += 1
            if step % 5 == 0:
                dist = 0.0
                if self.cfg["home"]:
                    dist = geo.distance_m(self.cfg["hlat"], self.cfg["hlon"], d["lat"], d["lon"])
                rssi = int(min(115, 45 + dist / 25.0 + 4 * math.sin(t)))
                ev(
                    {
                        "e": "link",
                        "rssi1": -rssi,
                        "rssi2": -(rssi + 3),
                        "lq": int(max(0, 100 - max(0.0, dist - 1500) / 20.0)),
                        "snr": int(12 - dist / 200.0),
                        "ant": int(t // 7) % 2,
                        "rfmode": 6,
                        "txpwr": 250,
                        "drssi": -(rssi + 5),
                        "dlq": 100,
                        "dsnr": 9,
                    }
                )
                self._emit_trk(d)
            if step % 10 == 0:
                frac = max(0.0, 1.0 - t / 900.0)
                ev(
                    {
                        "e": "bat",
                        "v": round(21.0 + 4.2 * frac, 1),
                        "a": round(14.0 + 4.0 * math.sin(t / 2.0), 1),
                        "mah": int(t * 4.2),
                        "pct": int(100 * frac),
                    }
                )
            if step % 2 == 1:
                # baro altitude is relative to where the FC was powered (ground level here)
                ev({"e": "baro", "alt": round(d["alt"] - 75.0, 1), "vs": round(d["vs"], 2)})
            if step % 10 == 0:
                if t < 5:
                    m = "ACRO*"  # disarmed on the ground
                else:
                    m = "ACRO" if int(t // 30) % 2 == 0 else "ANGL"
                ev({"e": "mode", "m": m})
            if step % 50 == 0:
                self._emit_stat()
            if step % 100 == 0:
                self._emit_hello()
            step += 1
            self._stop.wait(tick / max(self.time_scale, 0.01))


# ---------------------------------------------------------------------------------------------------
# Replay + logging
# ---------------------------------------------------------------------------------------------------


class ReplaySource(Source):
    """Replays a JSONL log written by `esptracker --log`. Read-only."""

    name = "replay"
    read_only = True

    def __init__(self, state: State, path: str, speed: float = 1.0, loop: bool = False) -> None:
        super().__init__(state)
        self.path = path
        self.speed = max(speed, 0.01)
        self.loop = loop
        self.records = list(read_log(path))
        if not self.records:
            raise ValueError("no events found in %s" % path)

    def send(self, line: str) -> None:
        raise PermissionError("replay mode is read-only")

    def _run(self) -> None:
        self.state.set_link("replay:%s" % self.path, True)
        while not self._stop.is_set():
            prev = self.records[0][0]
            for t, ev in self.records:
                if self._stop.wait(max(0.0, (t - prev) / self.speed)):
                    return
                prev = t
                self.state.ingest(ev)
            if not self.loop:
                break
            self.state.clear_track()
        self.state.set_link("replay:%s" % self.path, False, "end of log")


def read_log(path: str) -> Iterable[Any]:
    with open(path, "r", encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
                yield float(rec["t"]), dict(rec["ev"])
            except (ValueError, KeyError, TypeError):
                continue


class EventLogger:
    """State listener writing every event as {"t": host_epoch, "ev": {...}} lines."""

    def __init__(self, path: str) -> None:
        self._fh = open(path, "a", encoding="utf-8", buffering=1)
        self._lock = threading.Lock()

    def __call__(self, event: Dict[str, Any], t: float) -> None:
        with self._lock:
            self._fh.write(json.dumps({"t": t, "ev": event}, separators=(",", ":")) + "\n")

    def close(self) -> None:
        with self._lock:
            self._fh.close()


def make_on_connect(home: Optional[str]) -> List[str]:
    """`--home lat,lon,alt` -> the HOME command to (re)send each time the tracker connects."""
    if not home:
        return []
    parts = [p.strip() for p in home.split(",")]
    if len(parts) != 3:
        raise ValueError("--home expects lat,lon,alt")
    float(parts[0]), float(parts[1]), float(parts[2])
    return [validate_command("HOME %s %s %s" % tuple(parts))]
