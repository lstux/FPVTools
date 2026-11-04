// Persistent tracker configuration (plain data, stored as one blob in NVS by main.cpp).
#pragma once
#include <stddef.h>
#include <stdint.h>

#include "compass.h"

#define CFG_MAGIC 0x45540003u // bump when the layout changes

struct TrackerConfig {
    uint32_t magic;

    // ExpressLRS UID (derived from the bind phrase); ESP-NOW is disabled until it is set.
    uint8_t has_uid;
    uint8_t uid[6];

    // Tracker (ground) position
    uint8_t home_valid;
    double home_lat;
    double home_lon;
    float home_alt;
    uint8_t home_src;  // HOME_SRC_* : where the home position came from

    // Pointing
    float offset_deg;  // azimuth the antenna points at for pan = 0, tilt = 0
    float hyst_deg;    // hysteresis around the pan flip boundary
    float slew_dps;    // max servo speed, degrees per second

    // Servo pulse ranges that correspond to 0 and 180 degrees
    uint16_t pan_min_us, pan_max_us;
    uint16_t tilt_min_us, tilt_max_us;
    uint8_t pan_invert, tilt_invert;

    // GPS quality gate / timeout
    uint8_t min_sats;
    uint16_t lost_ms;  // keep "tracking" status this long after the last usable GPS frame

    // Height used for the elevation angle: 0 = drone GPS altitude - home altitude,
    // 1 = drone baro altitude (relative to where the drone was powered, i.e. next to the tracker)
    uint8_t alt_src;

    // Optional sensors on the tracker
    uint8_t auto_home;    // lock home from the tracker's own GPS (when one is connected)
    uint8_t auto_north;   // set `offset` from the compass (when calibrated)
    float compass_mount;  // azimuth of pan = 0 minus heading of the compass +X axis (degrees)
    float declination;    // magnetic declination, degrees, east positive (true = magnetic + declination)
    uint32_t gps_baud;    // 0 = auto-detect
    MagCalibration magcal;
};

enum HomeSrc : uint8_t { HOME_SRC_NONE = 0, HOME_SRC_MANUAL = 1, HOME_SRC_DRONE = 2, HOME_SRC_GPS = 3 };

void cfg_default(TrackerConfig *c);

// Set a numeric parameter by name (used by the `SET key value` serial command).
// Returns false and fills `err` (>= 48 bytes) on unknown key / out-of-range value.
bool cfg_set(TrackerConfig *c, const char *key, double value, char *err);

// Names of settable keys, comma separated (for help text).
const char *cfg_keys();
