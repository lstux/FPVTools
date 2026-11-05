"""Offline map tiles from an MBTiles file (SQLite), served to Leaflet."""

from __future__ import annotations

import pathlib
import sqlite3
import threading
from typing import Any, Dict, Optional

CONTENT_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}


class MBTiles:
    def __init__(self, path: str) -> None:
        file = pathlib.Path(path)
        if not file.is_file():
            raise ValueError("%s: no such file" % path)
        try:
            self._conn = sqlite3.connect(file.resolve().as_uri() + "?mode=ro", uri=True, check_same_thread=False)
        except sqlite3.Error as exc:
            raise ValueError("cannot open %s: %s" % (path, exc))
        self._lock = threading.Lock()
        try:
            self._conn.execute("SELECT 1 FROM tiles LIMIT 1")
            meta = dict(self._conn.execute("SELECT name, value FROM metadata"))
        except sqlite3.Error as exc:
            self._conn.close()
            raise ValueError("%s is not a valid MBTiles file: %s" % (path, exc))
        self.format = str(meta.get("format", "png")).lower()
        if self.format not in CONTENT_TYPES:
            self._conn.close()
            raise ValueError("unsupported tile format '%s' (vector tiles are not supported)" % self.format)
        self.meta = meta

    @property
    def content_type(self) -> str:
        return CONTENT_TYPES[self.format]

    def info(self) -> Dict[str, Any]:
        def num(key: str, default: int) -> int:
            try:
                return int(self.meta.get(key, default))
            except (TypeError, ValueError):
                return default

        out: Dict[str, Any] = {"minzoom": num("minzoom", 0), "maxzoom": num("maxzoom", 18)}
        for key in ("bounds", "center"):
            raw = self.meta.get(key)
            if raw:
                try:
                    out[key] = [float(v) for v in str(raw).split(",")]
                except ValueError:
                    pass
        if self.meta.get("name"):
            out["name"] = str(self.meta["name"])
        return out

    def tile(self, z: int, x: int, y: int) -> Optional[bytes]:
        """XYZ (Leaflet) coordinates in, tile bytes out. MBTiles stores rows in TMS order."""
        if z < 0 or z > 30 or x < 0 or y < 0:
            return None
        tms_y = (1 << z) - 1 - y
        with self._lock:
            row = self._conn.execute(
                "SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?", (z, x, tms_y)
            ).fetchone()
        return bytes(row[0]) if row else None

    def close(self) -> None:
        with self._lock:
            self._conn.close()
