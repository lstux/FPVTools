"""Command line entry point:  esptracker --port auto  |  esptracker --simulate"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import List, Optional

import uvicorn

from . import __version__
from .server import OSM_TILE_URL, create_app
from .sources import EventLogger, ReplaySource, SerialSource, SimulatorSource, make_on_connect
from .state import State
from .tiles import MBTiles


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="esptracker", description="Ground station for the ESP-NOW ELRS antenna tracker")
    src = p.add_argument_group("data source (default: --port auto)")
    src.add_argument("--port", default=None, help="serial port of the tracker, e.g. /dev/ttyACM0 or COM5; 'auto' picks an ESP32 USB device")
    src.add_argument("--baud", type=int, default=115200, help="serial speed (ignored on native USB boards) [115200]")
    src.add_argument("--simulate", action="store_true", help="fake tracker and flight, no hardware needed")
    src.add_argument("--replay", metavar="FILE", help="replay a log written with --log")
    src.add_argument("--speed", type=float, default=1.0, help="replay speed factor, or simulator time scale [1]")
    src.add_argument("--loop", action="store_true", help="loop the replay")
    src.add_argument("--home", metavar="LAT,LON,ALT", help="send 'HOME lat lon alt' to the tracker every time it connects")

    p.add_argument("--log", metavar="FILE", help="append every tracker event to FILE (JSON lines) for later --replay")

    web = p.add_argument_group("web server")
    web.add_argument("--host", default="127.0.0.1", help="listen address; use 0.0.0.0 to reach it from other devices (no authentication!) [127.0.0.1]")
    web.add_argument("--http-port", type=int, default=8080, help="HTTP port [8080]")
    web.add_argument("--mbtiles", metavar="FILE", help="offline map tiles (raster MBTiles)")
    web.add_argument("--tile-url", default=OSM_TILE_URL, help="online tile URL template [OpenStreetMap]")

    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--version", action="version", version="esptracker " + __version__)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    chosen = [bool(args.simulate), bool(args.replay), args.port is not None]
    if sum(chosen) > 1:
        print("error: choose only one of --port, --simulate, --replay", file=sys.stderr)
        return 2

    state = State()
    try:
        on_connect = make_on_connect(args.home)  # validated whatever the source
        if args.simulate:
            source = SimulatorSource(state, time_scale=args.speed)
        elif args.replay:
            source = ReplaySource(state, args.replay, speed=args.speed, loop=args.loop)
        else:
            source = SerialSource(state, port=args.port or "auto", baud=args.baud, on_connect=on_connect)
        tiles = MBTiles(args.mbtiles) if args.mbtiles else None
        logger = EventLogger(args.log) if args.log else None
    except (ValueError, OSError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    if args.home and (args.simulate or args.replay):
        logging.getLogger("esptracker").warning("--home is only sent to a real tracker (ignored with --simulate/--replay)")
    if logger:
        state.add_listener(logger)

    app = create_app(state, source, tiles=tiles, tile_url=args.tile_url)
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        logging.getLogger("esptracker").warning(
            "listening on %s: anyone on the network can move the tracker and change its settings", args.host
        )
    try:
        uvicorn.run(app, host=args.host, port=args.http_port, log_level="debug" if args.verbose else "info")
    finally:
        if logger:
            logger.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
