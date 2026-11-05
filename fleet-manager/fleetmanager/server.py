"""FastAPI application: JSON API + the static web UI."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__
from .db import Fleet
from .detect import DetectError, Detection, candidate_ports, scan_port
from .diffview import side_by_side

log = logging.getLogger("fleetmanager.server")

STATIC_DIR = Path(__file__).parent / "static"
MAX_PHOTO_BYTES = 10 * 1024 * 1024
PHOTO_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}

Scanner = Callable[[Optional[str], bool, bool], Detection]


class DroneIn(BaseModel):
    name: Optional[str] = None
    notes: Optional[str] = None
    specs: Optional[Dict[str, str]] = None


class ComponentIn(BaseModel):
    type: Optional[str] = None
    model: Optional[str] = None
    specs: Optional[Dict[str, str]] = None


class ScanIn(BaseModel):
    port: Optional[str] = "auto"
    cli: bool = True
    esc: bool = False


def _looks_like(kind: str, data: bytes) -> bool:
    if kind == "jpg":
        return data[:3] == b"\xff\xd8\xff"
    if kind == "png":
        return data[:8] == b"\x89PNG\r\n\x1a\n"
    return data[:4] == b"RIFF" and data[8:12] == b"WEBP"


def create_app(fleet: Fleet, photos_dir: Path, scanner: Scanner = scan_port) -> FastAPI:
    photos_dir = Path(photos_dir)
    photos_dir.mkdir(parents=True, exist_ok=True)
    scan_lock = threading.Lock()
    app = FastAPI(title="fleetmanager", version=__version__)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.mount("/photos", StaticFiles(directory=photos_dir), name="photos")

    def drone_or_404(drone_id: int) -> Dict[str, Any]:
        d = fleet.get_drone(drone_id)
        if d is None:
            raise HTTPException(404, "unknown drone")
        return d

    # ------------------------------------------------------------- detection

    @app.get("/api/ports")
    def ports() -> Any:
        return candidate_ports()

    @app.post("/api/scan")
    def scan(body: ScanIn = ScanIn()) -> Dict[str, Any]:
        if not scan_lock.acquire(blocking=False):
            raise HTTPException(409, "a detection is already running")
        try:
            det = scanner(body.port, body.cli, body.esc)
        except DetectError as e:
            raise HTTPException(400, str(e)) from e
        except PermissionError as e:
            raise HTTPException(400, "permission denied on the serial port (dialout group / udev rules?)") from e
        finally:
            scan_lock.release()
        result = fleet.register(det.info, det.diff_text, det.status_text)
        result["warnings"] = det.info.get("warnings", [])
        return result

    # ---------------------------------------------------------------- drones

    @app.get("/api/drones")
    def list_drones() -> Any:
        return fleet.list_drones()

    @app.post("/api/drones", status_code=201)
    def create_drone(body: DroneIn) -> Dict[str, Any]:
        name = (body.name or "").strip()
        if not name:
            raise HTTPException(400, "a name is required")
        return {"id": fleet.create_drone(name)}

    @app.get("/api/drones/{drone_id}")
    def get_drone(drone_id: int) -> Dict[str, Any]:
        return drone_or_404(drone_id)

    @app.patch("/api/drones/{drone_id}")
    def patch_drone(drone_id: int, body: DroneIn) -> Dict[str, Any]:
        fields = body.model_dump(exclude_unset=True)
        if "name" in fields:
            fields["name"] = (fields["name"] or "").strip()
            if not fields["name"]:
                raise HTTPException(400, "the name cannot be empty")
        if not fleet.update_drone(drone_id, fields):
            raise HTTPException(404, "unknown drone")
        return drone_or_404(drone_id)

    @app.delete("/api/drones/{drone_id}", status_code=204)
    def delete_drone(drone_id: int) -> None:
        try:
            photo = fleet.delete_drone(drone_id)
        except KeyError:
            raise HTTPException(404, "unknown drone")
        if photo:
            (photos_dir / photo).unlink(missing_ok=True)

    @app.put("/api/drones/{drone_id}/photo")
    async def put_photo(drone_id: int, request: Request) -> Dict[str, Any]:
        kind = PHOTO_TYPES.get((request.headers.get("content-type") or "").split(";")[0].strip())
        if kind is None:
            raise HTTPException(415, "send a jpeg, png or webp image as the request body")
        data = await request.body()
        if not data or len(data) > MAX_PHOTO_BYTES:
            raise HTTPException(413, "empty image or larger than 10 MB")
        if not _looks_like(kind, data):
            raise HTTPException(415, "the file is not a valid %s image" % kind)
        drone_or_404(drone_id)
        name = "drone-%d-%d.%s" % (drone_id, int(time.time()), kind)
        (photos_dir / name).write_bytes(data)
        old = fleet.set_photo(drone_id, name)
        if old and old != name:
            (photos_dir / old).unlink(missing_ok=True)
        return {"photo": name}

    @app.delete("/api/drones/{drone_id}/photo", status_code=204)
    def delete_photo(drone_id: int) -> None:
        drone_or_404(drone_id)
        old = fleet.set_photo(drone_id, None)
        if old:
            (photos_dir / old).unlink(missing_ok=True)

    # ------------------------------------------------------------ components

    @app.post("/api/drones/{drone_id}/components", status_code=201)
    def add_component(drone_id: int, body: ComponentIn) -> Dict[str, Any]:
        type_ = (body.type or "").strip()
        if not type_:
            raise HTTPException(400, "a type is required")
        try:
            return {"id": fleet.add_component(drone_id, type_, body.model or "", body.specs)}
        except KeyError:
            raise HTTPException(404, "unknown drone")

    @app.patch("/api/components/{component_id}")
    def patch_component(component_id: int, body: ComponentIn) -> Dict[str, str]:
        fields = body.model_dump(exclude_unset=True)
        if "type" in fields and not (fields["type"] or "").strip():
            raise HTTPException(400, "the type cannot be empty")
        if not fleet.update_component(component_id, fields):
            raise HTTPException(404, "unknown component")
        return {"status": "ok"}

    @app.delete("/api/components/{component_id}", status_code=204)
    def delete_component(component_id: int) -> None:
        if not fleet.delete_component(component_id):
            raise HTTPException(404, "unknown component")

    # ------------------------------------------------------------- snapshots
    # (declared before /api/snapshots/{id} so that "diff" is not taken for an id)

    @app.get("/api/snapshots/diff")
    def snapshot_diff(a: int, b: int, context: int = 3) -> Dict[str, Any]:
        sa, sb = fleet.get_snapshot(a), fleet.get_snapshot(b)
        if sa is None or sb is None:
            raise HTTPException(404, "unknown snapshot")
        meta = lambda s: {k: s[k] for k in ("id", "drone_id", "taken_at", "firmware", "version", "board")}  # noqa: E731
        out = side_by_side(sa["diff_text"], sb["diff_text"], context)
        out.update(a=meta(sa), b=meta(sb))
        return out

    @app.get("/api/snapshots/{snapshot_id}")
    def get_snapshot(snapshot_id: int) -> Dict[str, Any]:
        s = fleet.get_snapshot(snapshot_id)
        if s is None:
            raise HTTPException(404, "unknown snapshot")
        return s

    return app
