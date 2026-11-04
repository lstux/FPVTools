# FPVTools

> **🚧 Work in progress: this repository is being completely redone.**
> Nothing here should be considered working for now. The new code (starting with
> [`esp-tracker/`](esp-tracker)) is written and unit-tested on a PC but has **not been run on real
> hardware yet**, and the older scripts below have not been re-checked. Expect breaking changes.

Install/Update easily Linux tools for configuring your UAV (expresslrs,inav,emufilght,betaflight-configurator...)


# Use

First clone this repository.

To install a tool, just run

    fpvtools.sh -i toolname

To update a tool, run

    fpvtools.sh -u toolname

Check fpvtools.sh usage with :

    fpvtools.sh -h


# Supported tools :

 * betaflight : betaflight-configurator, flash/configure betaflight firmware
 * betaflight-bboxviewer : betaflight blackbox logs explorer, view your flights logs
 * blheli32 : BlHeli32Suite, flash/configure BLHeli32 ESCs
 * blheli : blheli-configurator, flash/configure blheli ESCs
 * edgetx-sdcard : EdgeTX SDcard, prepare a SD card for user with EdgeTX radios (TODO, include sound packs)
 * emuflight : emuflight-configurator, flash/configure EMUflight firmware
 * expresslrs : expresslrs-configurator, compile/flash ExpressLRS TX/RXs
 * inav : inav-configurator, flash/configure INAV firmware
 * jesc : jesc-configurator, flash/configure JESC ESCs
 * gyroflow : video stabilisation with gyro logs
 

# ESP-NOW antenna tracker / ground station

[`esp-tracker/`](esp-tracker) is not an installable configurator but a small project of its own: an ESP32 receives
the ExpressLRS Backpack telemetry (GPS included), drives a pan/tilt antenna tracker (optionally with its own GPS,
compass and barometer, and a status screen on the LilyGO TTGO TS), and a Python web application shows a cockpit-style
ground station: goggles/VRX video with a head-up display, map, telemetry, flying weather. See [`esp-tracker/README.md`](esp-tracker/README.md) and
[`esp-tracker/docs/usage.md`](esp-tracker/docs/usage.md).
