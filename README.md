# FPVTools

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
the ExpressLRS Backpack telemetry (GPS included), drives a pan/tilt antenna tracker, and a Python web application shows
the drone live on a map. See [`esp-tracker/README.md`](esp-tracker/README.md) and
[`esp-tracker/docs/usage.md`](esp-tracker/docs/usage.md).
