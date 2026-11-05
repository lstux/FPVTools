"""FastAPI application: REST + WebSocket API and the static web UI."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Response, WebSocket
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__
from .sources import Source, validate_command
from .state import State
from .tiles import MBTiles
from .video import VideoSource, list_devices
from .weather import Weather

log = logging.getLogger("esptracker.server")

STATIC_DIR = Path(__file__).parent / "static"
OSM_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
WS_PERIOD_S = 0.1
MJPEG_BOUNDARY = "esptrackerframe"


class CommandIn(BaseModel):
    line: str


def _display(line: str) -> str:
    """What gets echoed in the console: never show a bind phrase."""
    if line.split(None, 1)[0].upper() == "BIND":
        return "BIND ********"
    return line


def create_app(
    state: State,
    source: Source,
    tiles: Optional[MBTiles] = None,
    tile_url: str = OSM_TILE_URL,
    video: Optional[VideoSource] = None,
    weather: Optional[Weather] = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        source.start()
        try:
            yield
        finally:
            source.stop()
            if video is not None:
                video.close()

    app = FastAPI(title="esptracker", version=__version__, lifespan=lifespan)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/api/config")
    def config() -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "version": __version__,
            "source": source.name,
            "read_only": source.read_only,
            "tile_url": tile_url,
            "local_tiles": None,
            "video": video.info() if video is not None else None,
            "weather": weather is not None,
        }
        if tiles is not None:
            out["local_tiles"] = tiles.info()
        return out

    @app.get("/api/state")
    def get_state() -> Dict[str, Any]:
        return state.snapshot()

    @app.post("/api/cmd")
    def post_cmd(cmd: CommandIn) -> Dict[str, Any]:
        try:
            line = validate_command(cmd.line)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        # echo first: a simulator/replay answers synchronously and its ack must come after the command
        state.log_console("tx", _display(line))
        try:
            source.send(line)
        except (ConnectionError, PermissionError, OSError) as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return {"ok": True}

    @app.post("/api/track/clear")
    def clear_track() -> Dict[str, Any]:
        state.clear_track()
        return {"ok": True}

    @app.get("/api/track.gpx")
    def track_gpx() -> Response:
        pts = state.track_points()
        rows = "".join(
            '<trkpt lat="%.7f" lon="%.7f"><ele>%.0f</ele></trkpt>' % (lat, lon, alt) for lat, lon, alt in pts
        )
        gpx = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<gpx version="1.1" creator="esptracker" xmlns="http://www.topografix.com/GPX/1/1">'
            "<trk><name>flight</name><trkseg>%s</trkseg></trk></gpx>" % rows
        )
        return Response(
            gpx, media_type="application/gpx+xml", headers={"Content-Disposition": 'attachment; filename="flight.gpx"'}
        )

    # ---- video -------------------------------------------------------------------------------

    @app.get("/api/video")
    def video_info() -> Dict[str, Any]:
        out: Dict[str, Any] = video.info() if video is not None else {"enabled": False}
        out["devices"] = list_devices()
        return out

    if video is not None:

        @app.get("/video.mjpg", include_in_schema=False)
        async def video_stream() -> StreamingResponse:
            async def frames():
                video.acquire()
                seq = 0
                try:
                    while True:
                        new_seq, frame = video.latest()
                        if frame is None or new_seq == seq:
                            await asyncio.sleep(0.008)
                            continue
                        seq = new_seq
                        yield (
                            b"--" + MJPEG_BOUNDARY.encode() + b"\r\nContent-Type: image/jpeg\r\nContent-Length: "
                            + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n"
                        )
                finally:
                    video.release()

            return StreamingResponse(
                frames(),
                media_type="multipart/x-mixed-replace; boundary=" + MJPEG_BOUNDARY,
                headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"},
            )

        @app.get("/video.jpg", include_in_schema=False)
        def video_snapshot() -> Response:
            video.acquire()
            try:
                _seq, frame = video.wait_frame(0, timeout=5.0)
            finally:
                video.release()
            if frame is None:
                raise HTTPException(status_code=503, detail=video.info().get("error") or "no video frame yet")
            return Response(frame, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    # ---- weather -----------------------------------------------------------------------------

    @app.get("/api/weather")
    def get_weather(lat: Optional[float] = None, lon: Optional[float] = None, refresh: bool = False) -> Dict[str, Any]:
        if weather is None:
            raise HTTPException(status_code=404, detail="weather disabled (--no-weather)")
        place = "query"
        if lat is None or lon is None:
            snap = state.snapshot()
            trk, gps = snap.get("trk"), snap.get("gps")
            if trk and trk.get("home"):
                lat, lon, place = trk["hlat"], trk["hlon"], "home"
            elif gps and gps.get("sats", 0) >= 4 and not (gps.get("lat") == 0 and gps.get("lon") == 0):
                lat, lon, place = gps["lat"], gps["lon"], "drone"
            else:
                raise HTTPException(status_code=400, detail="no position yet: set the tracker home or wait for a GPS fix")
        try:
            out = weather.get(float(lat), float(lon), force=refresh)
        except ValueError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
        out["place"] = place
        return out

    if tiles is not None:

        @app.get("/tiles/{z}/{x}/{y}", include_in_schema=False)
        def tile(z: int, x: int, y: int) -> Response:
            data = tiles.tile(z, x, y)
            if data is None:
                raise HTTPException(status_code=404)
            return Response(data, media_type=tiles.content_type, headers={"Cache-Control": "public, max-age=86400"})

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        await websocket.accept()
        gen, idx, cseq = -1, 0, 0
        try:
            while True:
                gen, idx, reset, pts = state.track_since(gen, idx)
                cseq_new, items = state.console_since(cseq)
                cseq = cseq_new
                await websocket.send_json(
                    {
                        "state": state.snapshot(),
                        "track": {"gen": gen, "next": idx, "reset": reset, "pts": pts},
                        "console": items,
                    }
                )
                await asyncio.sleep(WS_PERIOD_S)
        except Exception as exc:  # noqa: BLE001 - client went away; nothing to clean up
            log.debug("websocket closed: %r", exc)

    return app
