"""Command line: ``fleetmanager serve`` (web UI) and ``fleetmanager scan`` (detect + register)."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Optional, Sequence

from . import __version__


def default_data_dir() -> Path:
    if os.environ.get("FLEET_DATA"):
        return Path(os.environ["FLEET_DATA"])
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "fpvtools" / "fleet-manager"


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="fleetmanager", description="Catalogue of your FPV drones.")
    p.add_argument("--version", action="version", version="%(prog)s " + __version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument(
            "--data-dir",
            type=Path,
            default=default_data_dir(),
            help="where fleet.db and photos/ live (default: %(default)s, or $FLEET_DATA)",
        )

    s = sub.add_parser("serve", help="run the web interface")
    common(s)
    s.add_argument("--host", default="127.0.0.1", help="listen address (default: %(default)s)")
    s.add_argument("--http-port", type=int, default=8090, help="listen port (default: %(default)s)")
    s.add_argument(
        "--simulate",
        action="store_true",
        help="no hardware: 'Detect drone' plugs simulated FCs in (uses a throw-away catalogue "
        "unless --data-dir is given)",
    )

    c = sub.add_parser("scan", help="read the connected flight controller and register it")
    common(c)
    c.add_argument("--port", default="auto", help="serial port, e.g. /dev/ttyACM0 (default: auto)")
    c.add_argument("--no-cli", action="store_true", help="MSP only: no config snapshot, no FC reboot")
    c.add_argument(
        "--esc",
        action="store_true",
        help="also read the ESCs (battery connected, PROPELLERS OFF): firmware, version, MCU",
    )

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    from .db import open_fleet

    if args.cmd == "serve" and args.simulate and args.data_dir == default_data_dir():
        import tempfile

        args.data_dir = Path(tempfile.mkdtemp(prefix="fleetmanager-sim-"))
        print("simulation: throw-away catalogue in %s" % args.data_dir)
    fleet = open_fleet(args.data_dir)

    if args.cmd == "serve":
        import uvicorn

        from .server import create_app

        if args.simulate:
            from .simulator import DemoScanner

            app = create_app(fleet, args.data_dir / "photos", DemoScanner(), simulated=True)
        else:
            app = create_app(fleet, args.data_dir / "photos")
        uvicorn.run(app, host=args.host, port=args.http_port)
        return 0

    from .detect import DetectError, scan_port

    try:
        det = scan_port(args.port, with_cli=not args.no_cli, with_esc=args.esc)
    except DetectError as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
    res = fleet.register(det.info, det.diff_text, det.status_text)
    i = det.info
    print("%s %s on %s (%s)" % (i["firmware"], i["version"], i.get("board_id", "?"), i.get("craft_name", "")))
    from .esc import describe

    for e in i.get("escs", []):
        print(describe(e))
    for w in i.get("warnings", []):
        print("warning: " + w, file=sys.stderr)
    print(
        "drone #%d %s; configuration %s"
        % (
            res["drone_id"],
            "created" if res["created"] else "updated",
            "saved as snapshot #%d" % res["snapshot_id"] if res["changed"] else "unchanged (no new snapshot)",
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
