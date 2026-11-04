"""Thread-safe live state built from the JSON events sent by the tracker firmware."""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from itertools import islice
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

from . import geo

# firmware event name -> key in the snapshot
EVENT_KEYS = {
    "gps": "gps",
    "bat": "bat",
    "link": "rf",  # RF link statistics (RSSI/LQ/SNR); "link" is also the name of the USB connection block
    "att": "att",
    "mode": "mode",
    "trk": "trk",
    "stat": "stat",
    "hello": "hello",
    "cfg": "cfg",
}

MIN_TRACK_SATS = 4
MIN_TRACK_STEP_M = 2.0


class State:
    def __init__(self, track_max: int = 50000, console_max: int = 300, clock: Callable[[], float] = time.time):
        self._lock = threading.RLock()
        self._clock = clock
        self._data: Dict[str, Dict[str, Any]] = {}
        self._t_rx: Dict[str, float] = {}

        self._conn: Dict[str, Any] = {"source": "", "connected": False, "error": None, "last_rx": None}

        self._console: Deque[Dict[str, Any]] = deque(maxlen=console_max)
        self._console_seq = 0

        self._track: Deque[Tuple[float, float, float]] = deque(maxlen=track_max)
        self._track_total = 0
        self._track_gen = 0
        self._last_pt: Optional[Tuple[float, float]] = None

        self._flight = self._new_flight()
        self._listeners: List[Callable[[Dict[str, Any], float], None]] = []

    @staticmethod
    def _new_flight() -> Dict[str, Any]:
        return {"max_speed_kmh": 0.0, "max_dist_m": 0.0, "max_alt_rel_m": None, "path_m": 0.0}

    # ---- listeners (used for the JSONL logger) -----------------------------------------------------

    def add_listener(self, fn: Callable[[Dict[str, Any], float], None]) -> None:
        self._listeners.append(fn)

    # ---- connection ------------------------------------------------------------------------------

    def set_link(self, source: str, connected: bool, error: Optional[str] = None) -> None:
        with self._lock:
            self._conn.update(source=source, connected=connected, error=error)
            if not connected:
                self._conn["last_rx"] = None

    # ---- ingestion -------------------------------------------------------------------------------

    def ingest_line(self, line: str) -> None:
        """Feed one raw line from the tracker. Non-JSON lines (boot messages...) go to the console."""
        line = line.strip()
        if not line:
            return
        if line.startswith("{"):
            try:
                event = json.loads(line)
            except ValueError:
                event = None
            if isinstance(event, dict) and "e" in event:
                self.ingest(event)
                return
        self.log_console("raw", line)

    def ingest(self, event: Dict[str, Any], t: Optional[float] = None) -> None:
        now = self._clock() if t is None else t
        name = event.get("e")
        with self._lock:
            self._conn["last_rx"] = now
            if name in EVENT_KEYS:
                key = EVENT_KEYS[name]
                body = {k: v for k, v in event.items() if k not in ("e", "ms")}
                self._data[key] = body
                self._t_rx[key] = now
                if name == "gps":
                    self._on_gps(body)
                elif name == "trk":
                    self._on_trk(body)
            elif name == "ack":
                self.log_console("ack", str(event.get("cmd", "")))
            elif name == "err":
                self.log_console("err", str(event.get("msg", "")))
            elif name == "help":
                self.log_console("help", str(event.get("text", "")))
        for fn in self._listeners:
            fn(event, now)

    def _on_gps(self, g: Dict[str, Any]) -> None:
        gs = g.get("gs")
        if isinstance(gs, (int, float)) and gs > self._flight["max_speed_kmh"]:
            self._flight["max_speed_kmh"] = float(gs)
        lat, lon, alt = g.get("lat"), g.get("lon"), g.get("alt")
        sats = g.get("sats", 0)
        if (
            not isinstance(lat, (int, float))
            or not isinstance(lon, (int, float))
            or (lat == 0 and lon == 0)
            or sats < MIN_TRACK_SATS
        ):
            return
        if self._last_pt is not None:
            step = geo.distance_m(self._last_pt[0], self._last_pt[1], lat, lon)
            if step < MIN_TRACK_STEP_M:
                return
            self._flight["path_m"] += step
        self._last_pt = (lat, lon)
        self._track.append((lat, lon, float(alt) if isinstance(alt, (int, float)) else 0.0))
        self._track_total += 1
        trk = self._data.get("trk")
        if trk and trk.get("home") and isinstance(alt, (int, float)) and isinstance(trk.get("halt"), (int, float)):
            rel = float(alt) - float(trk["halt"])
            cur = self._flight["max_alt_rel_m"]
            if cur is None or rel > cur:
                self._flight["max_alt_rel_m"] = rel

    def _on_trk(self, trk: Dict[str, Any]) -> None:
        dist = trk.get("dist")
        if isinstance(dist, (int, float)) and dist > self._flight["max_dist_m"]:
            self._flight["max_dist_m"] = float(dist)

    # ---- console ---------------------------------------------------------------------------------

    def log_console(self, kind: str, text: str) -> None:
        with self._lock:
            self._console_seq += 1
            self._console.append({"seq": self._console_seq, "t": self._clock(), "kind": kind, "text": text})

    def console_since(self, seq: int) -> Tuple[int, List[Dict[str, Any]]]:
        with self._lock:
            items = [c for c in self._console if c["seq"] > seq]
            return self._console_seq, items

    # ---- track -----------------------------------------------------------------------------------

    def track_since(self, gen: int, idx: int) -> Tuple[int, int, bool, List[Tuple[float, float, float]]]:
        """Return (generation, next_index, reset, new_points) for a client that already has `idx` points
        of generation `gen`. `reset` tells the client to drop its trail first."""
        with self._lock:
            reset = gen != self._track_gen
            if reset:
                idx = 0
            offset = self._track_total - len(self._track)
            if idx < offset:
                idx = offset
            pts = list(islice(self._track, idx - offset, None))
            return self._track_gen, self._track_total, reset, pts

    def track_points(self) -> List[Tuple[float, float, float]]:
        with self._lock:
            return list(self._track)

    def clear_track(self) -> None:
        with self._lock:
            self._track.clear()
            self._track_total = 0
            self._track_gen += 1
            self._last_pt = None
            self._flight = self._new_flight()

    # ---- snapshot --------------------------------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        now = self._clock()
        with self._lock:
            out: Dict[str, Any] = {"t": now}
            conn = dict(self._conn)
            last = conn.pop("last_rx")
            conn["last_rx_age"] = None if last is None else round(now - last, 2)
            out["conn"] = conn
            for key in EVENT_KEYS.values():
                body = self._data.get(key)
                if body is None:
                    out[key] = None
                else:
                    item = dict(body)
                    item["age"] = round(now - self._t_rx[key], 2)
                    out[key] = item
            out["flight"] = dict(self._flight)
            out["track_n"] = self._track_total
            return out
