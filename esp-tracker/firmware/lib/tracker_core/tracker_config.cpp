#include "tracker_config.h"

#include <stdio.h>
#include <string.h>

void cfg_default(TrackerConfig *c)
{
    memset(c, 0, sizeof(*c));
    c->magic = CFG_MAGIC;
    c->offset_deg = 0.0f;
    c->hyst_deg = 3.0f;
    c->slew_dps = 120.0f;
    c->pan_min_us = 500;
    c->pan_max_us = 2500;
    c->tilt_min_us = 500;
    c->tilt_max_us = 2500;
    c->min_sats = 6;
    c->lost_ms = 5000;
    c->alt_src = 0;
    c->auto_home = 1;
    c->auto_north = 1;
    c->compass_mount = 0.0f;
    c->declination = 0.0f;
    c->gps_baud = 0;
    magcal_identity(&c->magcal);
}

namespace {

enum Kind : uint8_t { F32, U32, U16, U8 };

struct Param {
    const char *name;
    Kind kind;
    size_t offset;
    double lo, hi;
};

#define P(n, k, field, lo, hi) {n, k, offsetof(TrackerConfig, field), lo, hi}

const Param PARAMS[] = {
    P("offset", F32, offset_deg, 0, 360),
    P("hyst", F32, hyst_deg, 0, 30),
    P("slew", F32, slew_dps, 5, 720),
    P("pan_min_us", U16, pan_min_us, 400, 2600),
    P("pan_max_us", U16, pan_max_us, 400, 2600),
    P("tilt_min_us", U16, tilt_min_us, 400, 2600),
    P("tilt_max_us", U16, tilt_max_us, 400, 2600),
    P("pan_invert", U8, pan_invert, 0, 1),
    P("tilt_invert", U8, tilt_invert, 0, 1),
    P("min_sats", U8, min_sats, 0, 30),
    P("lost_ms", U16, lost_ms, 500, 60000),
    P("alt_src", U8, alt_src, 0, 1),
    P("auto_home", U8, auto_home, 0, 1),
    P("auto_north", U8, auto_north, 0, 1),
    P("compass_mount", F32, compass_mount, -360, 360),
    P("declination", F32, declination, -40, 40),
    P("gps_baud", U32, gps_baud, 0, 921600),
};

} // namespace

bool cfg_set(TrackerConfig *c, const char *key, double value, char *err)
{
    for (const Param &p : PARAMS) {
        if (strcmp(p.name, key) != 0) continue;
        if (value < p.lo || value > p.hi) {
            snprintf(err, 48, "%s out of range [%g..%g]", p.name, p.lo, p.hi);
            return false;
        }
        uint8_t *base = reinterpret_cast<uint8_t *>(c) + p.offset;
        switch (p.kind) {
        case F32: {
            float v = (float)value;
            memcpy(base, &v, sizeof(v));
            break;
        }
        case U32: {
            uint32_t v = (uint32_t)(value + 0.5);
            memcpy(base, &v, sizeof(v));
            break;
        }
        case U16: {
            uint16_t v = (uint16_t)(value + 0.5);
            memcpy(base, &v, sizeof(v));
            break;
        }
        case U8:
            *base = (uint8_t)(value + 0.5);
            break;
        }
        return true;
    }
    snprintf(err, 48, "unknown key '%.20s'", key);
    return false;
}

const char *cfg_keys()
{
    return "offset,hyst,slew,pan_min_us,pan_max_us,tilt_min_us,tilt_max_us,pan_invert,tilt_invert,min_sats,lost_ms,"
           "alt_src,auto_home,auto_north,compass_mount,declination,gps_baud";
}
