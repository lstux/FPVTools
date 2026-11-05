# fleet-manager

A catalogue of your FPV drones. Plug a flight controller in: the app reads what the FC knows (firmware,
version, board, sensors, receiver protocol, VTX, settings…), creates a skeleton sheet, and you complete it by
hand (motors, props, camera, antenna, GPS model, photo…). Every connection also saves the FC configuration
(`diff all`) when it changed since the last time, so you can compare two dates side by side.

> **Status:** unit-tested against a simulated flight controller only, **not run on real hardware yet**. The
> text parsers (`status`, `get`) follow Betaflight/INAV output from memory; the raw `status` and `diff all`
> text is always stored, so nothing is lost if a parser misses something.

## Run

```sh
cd fleet-manager
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[test]'
fleetmanager serve                # web interface on http://127.0.0.1:8090
fleetmanager scan                 # same detection from the terminal, no browser
fleetmanager scan --no-cli        # MSP only: no config snapshot and no FC reboot
```

Run `../udevrules.sh` once (or join the `dialout` group) to get access to the USB serial port. Close
Betaflight/INAV Configurator first: only one program can use the port.

The catalogue lives in `~/.local/share/fpvtools/fleet-manager/` (`fleet.db` + `photos/`); change it with
`--data-dir` or `$FLEET_DATA`. Back that directory up, it is your data.

## What is read automatically

| Source | Data |
|---|---|
| MSP | firmware variant and version, MSP API, board id/name, build date and git revision, craft name, FC unique id, sensors present (acc/baro/mag/GPS), VTX config (Betaflight) |
| CLI `status` | gyro / accelerometer / barometer / magnetometer chip names |
| CLI `get …` | receiver protocol (`serialrx_provider`), motor protocol and poles, GPS provider, optical flow / rangefinder hardware, blackbox device |
| CLI `diff all` | the whole non-default configuration, saved as a snapshot |

The FC unique id recognises a drone when you plug it again: automatic fields are refreshed, **what you typed is
never overwritten**. Automatic values appear in green next to the matching component ("seen by the FC").

Not readable from the FC, to type in by hand: ELRS version (read it from the radio's Lua script), GPS module
model, motor/prop/camera/antenna models, ESC firmware (planned, via the 4-way interface).

## Warning: the FC reboots

Leaving the CLI makes Betaflight/INAV reboot. Detect on the bench, never while armed or flying. Untick
"full config" (or use `--no-cli`) to read through MSP only, without a reboot or a snapshot.

## Layout

```
fleetmanager/msp.py       MSP v1/v2 framing and client
fleetmanager/detect.py    port discovery, MSP identity, CLI session
fleetmanager/db.py        SQLite schema, skeleton, hints, snapshots with de-duplication
fleetmanager/diffview.py  side-by-side diff for the UI
fleetmanager/server.py    FastAPI JSON API + static UI (fleetmanager/static/)
tests/                    pytest, with a fake FC (tests/fakefc.py)
```

Tests: `pytest` (no hardware needed).

## Roadmap

ESC firmware/version through the 4-way passthrough (BLHeli_32, AM32, Bluejay); ArduPilot (MAVLink).
