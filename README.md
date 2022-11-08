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
 * blheli32 : BlHeli32Suite, flash/configure BLHeli32 ESCs
 * blheli : blheli-configurator, flash/configure blheli ESCs
 * edgetx-sdcard : EdgeTX SDcard, prepare a SD card for user with EdgeTX radios
 * emuflight : emuflight-configurator, flash/configure EMUflight firmware
 * expresslrs : expresslrs-configurator, compile/flash ExpressLRS TX/RXs
 * inav : inav-configurator, flash/configure INAV firmware
 * jesc : jesc-configurator, flash/configure JESC ESCs
 * gyroflow (soon) : video stabilisation with gyro logs
 
