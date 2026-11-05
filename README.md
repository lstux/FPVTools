# FPVTools

> **🚧 Work in progress: this repository is being completely redone.**
> [`esp-tracker/`](esp-tracker) is written and unit-tested on a PC but has **not been run on real hardware yet**.
> The installer (`fpvtools.sh` + `ghrelease-install`) is unit-tested against a fake GitHub API but the per-tool
> asset detection has not been checked against every real release yet. Expect breaking changes.

Install/Update easily Linux tools for configuring your UAV (Betaflight, INAV, EmuFlight, ExpressLRS, EdgeTX, Gyroflow...).

Tools are fetched from their **GitHub releases** with [`ghrelease-install`](ghrelease-install), a standalone script
usable for any `owner/repo`. `fpvtools.sh` is a thin wrapper with one small config file per tool in [`tools/`](tools).

Requirements : `bash`, `curl`, `jq`, `unzip`, `tar` (AppImages such as Betaflight need `libfuse2`).


# Use

First clone this repository, then :

    ./fpvtools.sh ls                 # list tools
    ./fpvtools.sh betaflight inav    # install or update
    ./fpvtools.sh -c all             # check every tool against its latest release
    ./fpvtools.sh -s betaflight      # show release assets and the one that would be installed
    ./fpvtools.sh -h                 # all options

Tools are installed in `/opt/FPVTools` (override with `FPV_INSTALLDIR`; the directory is created once with sudo and
owned by you), as `/opt/FPVTools/<Tool>-<version>` plus a `/opt/FPVTools/<Tool>` symlink to the active version.
Launchers are linked in `~/.local/bin` (override with `FPV_LINKDIR`). Run `./udevrules.sh` once to get USB/DFU access.

Set `GITHUB_TOKEN` if you hit the GitHub API rate limit.


# ghrelease-install

    ghrelease-install [-v version] [-d installdir] [-a asset_regex] [-n name] [-b bin] [-B linkname]
                      [-l linkdir] [-k keep] [-P] [-S] [-f] [-c] [-L] [-s] [-R] [-q] owner/repo

Without `-a`, the Linux asset matching your CPU is chosen automatically (zip/tar preferred over AppImage, Windows/macOS/
checksum/deb/rpm assets ignored); the sha256 digest published by GitHub is verified. Several versions are kept side by
side (`-k`), the active one being switched atomically. `-c` returns 0 (up to date), 1 (outdated), 2 (not installed).
Run `tests/test-ghrelease-install.sh` for the offline test-suite.


# Supported tools

 * betaflight : Betaflight Configurator
 * inav : INAV Configurator
 * emuflight : EmuFlight Configurator
 * expresslrs : ExpressLRS Configurator
 * edgetx-sdcard : EdgeTX SD card content for your radio (interactive menu, or `EDGETX_SDCARD=c480x272`)
 * edgetx-buddy : EdgeTX Buddy *(asset layout not verified)*
 * blheli32 : BLHeliSuite32 *(asset layout not verified)*
 * gyroflow : video stabilisation with gyro logs

Removed: `blheli` and `jesc` configurators (unmaintained since 2021) and the Betaflight blackbox explorer (no desktop
release anymore, use the web app). Adding a tool = adding a `tools/<name>.conf` (`REPO`, `NAME`, `BIN`, optional `ASSET`).


# ESP-NOW antenna tracker / ground station

[`esp-tracker/`](esp-tracker) is not an installable configurator but a small project of its own: an ESP32 receives
the ExpressLRS Backpack telemetry (GPS included), drives a pan/tilt antenna tracker (optionally with its own GPS,
compass and barometer, and a status screen on the LilyGO TTGO TS), and a Python web application shows a cockpit-style
ground station: goggles/VRX video with a head-up display, map, telemetry, flying weather. See [`esp-tracker/README.md`](esp-tracker/README.md) and
[`esp-tracker/docs/usage.md`](esp-tracker/docs/usage.md).


# Fleet manager

[`fleet-manager/`](fleet-manager) is a catalogue of your drones: plug a Betaflight/INAV flight controller in and it
pre-fills a sheet (firmware, board, sensors, receiver, VTX…) that you complete by hand, and keeps the history of
the FC configuration with a side-by-side comparison. See [`fleet-manager/README.md`](fleet-manager/README.md).
