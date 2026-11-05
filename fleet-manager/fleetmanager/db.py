"""SQLite catalogue: drones, their components and the history of their FC configuration.

What you type (name, notes, specs, component model/specs, photo) and what the FC reports (``detected``,
component ``hint``, snapshots) live in separate columns, so a re-detection never overwrites your input.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS drone (
    id         INTEGER PRIMARY KEY,
    fc_uid     TEXT UNIQUE,
    name       TEXT NOT NULL,
    notes      TEXT NOT NULL DEFAULT '',
    photo      TEXT,
    specs      TEXT NOT NULL DEFAULT '{}',
    detected   TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    last_seen  TEXT
);
CREATE TABLE IF NOT EXISTS component (
    id       INTEGER PRIMARY KEY,
    drone_id INTEGER NOT NULL REFERENCES drone(id) ON DELETE CASCADE,
    type     TEXT NOT NULL,
    model    TEXT NOT NULL DEFAULT '',
    specs    TEXT NOT NULL DEFAULT '{}',
    hint     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS component_drone ON component(drone_id);
CREATE TABLE IF NOT EXISTS snapshot (
    id          INTEGER PRIMARY KEY,
    drone_id    INTEGER NOT NULL REFERENCES drone(id) ON DELETE CASCADE,
    taken_at    TEXT NOT NULL,
    firmware    TEXT,
    version     TEXT,
    board       TEXT,
    craft_name  TEXT,
    hash        TEXT NOT NULL,
    diff_text   TEXT NOT NULL,
    status_text TEXT,
    info        TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS snapshot_drone ON snapshot(drone_id, id);
"""

# Created for every new drone, to be filled in by hand.
BASE_COMPONENTS = [
    "motor",
    "propeller",
    "camera",
    "vtx",
    "antenna",
    "receiver",
    "gps",
    "compass",
    "optical_flow",
]
# Component types whose ``hint`` is maintained by the detection.
HINTED_COMPONENTS = BASE_COMPONENTS + ["gyro", "accelerometer", "barometer"]

DRONE_FIELDS = {"name", "notes", "specs"}
COMPONENT_FIELDS = {"type", "model", "specs"}
JSON_COLUMNS = ("specs", "detected", "info")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_diff(text: str) -> str:
    """Stable form of a ``diff all`` output, so that the hash only changes when the config does."""
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return "\n".join(lines).strip("\n") + "\n"


def hints_from_info(info: Dict[str, Any]) -> Dict[str, str]:
    """What the FC tells about each component type (empty string = nothing known)."""
    sensors = info.get("sensors") or {}
    flags = info.get("sensor_flags") or {}
    settings = info.get("settings") or {}

    def chip(sensor: str) -> str:
        return sensors.get(sensor) or ("detected by the FC" if flags.get(sensor) else "")

    hints = {t: "" for t in HINTED_COMPONENTS}
    hints["gyro"] = sensors.get("gyro", "")
    hints["accelerometer"] = chip("acc")
    hints["barometer"] = chip("baro")
    hints["compass"] = chip("mag")
    if flags.get("gps"):
        hints["gps"] = "detected by the FC" + (
            " (provider %s)" % settings["gps_provider"] if settings.get("gps_provider") else ""
        )
    if settings.get("serialrx_provider"):
        hints["receiver"] = "serial rx: " + settings["serialrx_provider"]
    vtx = info.get("vtx")
    if vtx:
        hints["vtx"] = "MSP: %d MHz (band %d, channel %d, power %d)" % (
            vtx["freq_mhz"],
            vtx["band"],
            vtx["channel"],
            vtx["power"],
        )
    flow = settings.get("opflow_hardware", "")
    if flow and flow.upper() != "NONE":
        hints["optical_flow"] = flow
    motor = [settings[k] for k in ("motor_pwm_protocol",) if settings.get(k)]
    if settings.get("motor_poles"):
        motor.append("%s poles" % settings["motor_poles"])
    hints["motor"] = ", ".join(motor)
    return hints


def _row(r: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    if r is None:
        return None
    d = dict(r)
    for col in JSON_COLUMNS:
        if col in d and isinstance(d[col], str):
            d[col] = json.loads(d[col])
    return d


class Fleet:
    def __init__(self, path) -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ------------------------------------------------------------------ drones

    def list_drones(self) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT d.*, (SELECT COUNT(*) FROM snapshot s WHERE s.drone_id = d.id) AS snapshot_count "
                "FROM drone d ORDER BY d.name COLLATE NOCASE"
            ).fetchall()
        return [_row(r) for r in rows]

    def get_drone(self, drone_id: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            r = self._db.execute("SELECT * FROM drone WHERE id = ?", (drone_id,)).fetchone()
            if r is None:
                return None
            drone = _row(r)
            drone["components"] = [
                _row(c)
                for c in self._db.execute(
                    "SELECT * FROM component WHERE drone_id = ? ORDER BY id", (drone_id,)
                )
            ]
            drone["snapshots"] = self.list_snapshots(drone_id)
        return drone

    def create_drone(self, name: str, fc_uid: Optional[str] = None, skeleton: bool = True) -> int:
        with self._lock, self._db:
            cur = self._db.execute(
                "INSERT INTO drone (name, fc_uid, created_at) VALUES (?, ?, ?)", (name, fc_uid, _now())
            )
            drone_id = cur.lastrowid
            if skeleton:
                self._db.executemany(
                    "INSERT INTO component (drone_id, type) VALUES (?, ?)",
                    [(drone_id, t) for t in BASE_COMPONENTS],
                )
        return drone_id

    def update_drone(self, drone_id: int, fields: Dict[str, Any]) -> bool:
        return self._update("drone", drone_id, fields, DRONE_FIELDS)

    def set_photo(self, drone_id: int, filename: Optional[str]) -> Optional[str]:
        """Store the photo file name; returns the previous one (to delete the file)."""
        with self._lock, self._db:
            r = self._db.execute("SELECT photo FROM drone WHERE id = ?", (drone_id,)).fetchone()
            if r is None:
                raise KeyError(drone_id)
            self._db.execute("UPDATE drone SET photo = ? WHERE id = ?", (filename, drone_id))
        return r["photo"]

    def delete_drone(self, drone_id: int) -> Optional[str]:
        """Delete a drone (components and snapshots follow); returns its photo file name, if any."""
        with self._lock, self._db:
            r = self._db.execute("SELECT photo FROM drone WHERE id = ?", (drone_id,)).fetchone()
            if r is None:
                raise KeyError(drone_id)
            self._db.execute("DELETE FROM drone WHERE id = ?", (drone_id,))
        return r["photo"]

    # -------------------------------------------------------------- components

    def add_component(self, drone_id: int, type_: str, model: str = "", specs: Optional[dict] = None) -> int:
        with self._lock, self._db:
            if self._db.execute("SELECT 1 FROM drone WHERE id = ?", (drone_id,)).fetchone() is None:
                raise KeyError(drone_id)
            cur = self._db.execute(
                "INSERT INTO component (drone_id, type, model, specs) VALUES (?, ?, ?, ?)",
                (drone_id, type_, model, json.dumps(specs or {})),
            )
        return cur.lastrowid

    def update_component(self, component_id: int, fields: Dict[str, Any]) -> bool:
        return self._update("component", component_id, fields, COMPONENT_FIELDS)

    def delete_component(self, component_id: int) -> bool:
        with self._lock, self._db:
            return self._db.execute("DELETE FROM component WHERE id = ?", (component_id,)).rowcount > 0

    def _update(self, table: str, row_id: int, fields: Dict[str, Any], allowed: set) -> bool:
        fields = {k: v for k, v in fields.items() if k in allowed}
        with self._lock, self._db:
            if self._db.execute("SELECT 1 FROM %s WHERE id = ?" % table, (row_id,)).fetchone() is None:
                return False
            if fields:
                cols = ", ".join("%s = ?" % k for k in fields)  # keys come from the whitelist
                vals = [json.dumps(v) if k == "specs" else v for k, v in fields.items()]
                self._db.execute("UPDATE %s SET %s WHERE id = ?" % (table, cols), vals + [row_id])
        return True

    # --------------------------------------------------------------- snapshots

    def list_snapshots(self, drone_id: int) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, drone_id, taken_at, firmware, version, board, craft_name, hash "
                "FROM snapshot WHERE drone_id = ? ORDER BY id DESC",
                (drone_id,),
            ).fetchall()
        return [_row(r) for r in rows]

    def get_snapshot(self, snapshot_id: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            return _row(self._db.execute("SELECT * FROM snapshot WHERE id = ?", (snapshot_id,)).fetchone())

    # ------------------------------------------------------------ registration

    def register(
        self, info: Dict[str, Any], diff_text: Optional[str], status_text: Optional[str]
    ) -> Dict[str, Any]:
        """Record a detection: create the drone (with a skeleton) or refresh it, then snapshot the
        config if it changed since the last snapshot. Manual fields are never touched."""
        uid = info.get("uid") or "noid:%s:%s" % (info.get("board_id", "?"), info.get("craft_name", "?"))
        now = _now()
        with self._lock, self._db:
            r = self._db.execute("SELECT id FROM drone WHERE fc_uid = ?", (uid,)).fetchone()
            created = r is None
            if created:
                name = info.get("craft_name") or "%s %s" % (info.get("firmware", "FC"), info.get("board_id", ""))
                drone_id = self.create_drone(name.strip(), uid)
            else:
                drone_id = r["id"]
            self._db.execute(
                "UPDATE drone SET detected = ?, last_seen = ? WHERE id = ?",
                (json.dumps(info), now, drone_id),
            )
            self._sync_hints(drone_id, hints_from_info(info))

            snapshot_id = None
            if diff_text and diff_text.strip():
                norm = normalize_diff(diff_text)
                digest = hashlib.sha256(norm.encode()).hexdigest()
                last = self._db.execute(
                    "SELECT hash FROM snapshot WHERE drone_id = ? ORDER BY id DESC LIMIT 1", (drone_id,)
                ).fetchone()
                if last is None or last["hash"] != digest:
                    cur = self._db.execute(
                        "INSERT INTO snapshot (drone_id, taken_at, firmware, version, board, craft_name, "
                        "hash, diff_text, status_text, info) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            drone_id,
                            now,
                            info.get("firmware"),
                            info.get("version"),
                            info.get("board_id"),
                            info.get("craft_name"),
                            digest,
                            norm,
                            status_text,
                            json.dumps(info),
                        ),
                    )
                    snapshot_id = cur.lastrowid
        return {
            "drone_id": drone_id,
            "created": created,
            "snapshot_id": snapshot_id,
            "changed": snapshot_id is not None,
        }

    def _sync_hints(self, drone_id: int, hints: Dict[str, str]) -> None:
        for type_, hint in hints.items():
            r = self._db.execute(
                "SELECT id FROM component WHERE drone_id = ? AND type = ? ORDER BY id LIMIT 1",
                (drone_id, type_),
            ).fetchone()
            if r is not None:
                self._db.execute("UPDATE component SET hint = ? WHERE id = ?", (hint, r["id"]))
            elif hint:
                self._db.execute(
                    "INSERT INTO component (drone_id, type, hint) VALUES (?, ?, ?)", (drone_id, type_, hint)
                )


def open_fleet(data_dir) -> Fleet:
    data_dir = Path(data_dir)
    (data_dir / "photos").mkdir(parents=True, exist_ok=True)
    return Fleet(data_dir / "fleet.db")
