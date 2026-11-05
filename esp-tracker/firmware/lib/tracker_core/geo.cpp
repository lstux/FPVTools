#include "geo.h"

#include <math.h>

namespace {
const double PI_D = 3.14159265358979323846;
const double D2R = PI_D / 180.0;
const double R2D = 180.0 / PI_D;
const double EARTH_R = 6371000.0;

inline double clampd(double v, double lo, double hi) { return v < lo ? lo : (v > hi ? hi : v); }
} // namespace

double geo_wrap360(double deg)
{
    deg = fmod(deg, 360.0);
    if (deg < 0) deg += 360.0;
    return deg;
}

double geo_bearing_deg(double lat1, double lon1, double lat2, double lon2)
{
    double p1 = lat1 * D2R, p2 = lat2 * D2R, dl = (lon2 - lon1) * D2R;
    double y = sin(dl) * cos(p2);
    double x = cos(p1) * sin(p2) - sin(p1) * cos(p2) * cos(dl);
    return geo_wrap360(atan2(y, x) * R2D);
}

double geo_distance_m(double lat1, double lon1, double lat2, double lon2)
{
    double p1 = lat1 * D2R, p2 = lat2 * D2R;
    double dp = p2 - p1, dl = (lon2 - lon1) * D2R;
    double a = sin(dp / 2) * sin(dp / 2) + cos(p1) * cos(p2) * sin(dl / 2) * sin(dl / 2);
    return 2.0 * EARTH_R * atan2(sqrt(a), sqrt(1.0 - a));
}

double geo_elevation_deg(double ground_dist_m, double delta_alt_m)
{
    return clampd(atan2(delta_alt_m, ground_dist_m) * R2D, 0.0, 90.0);
}

PanTilt AimMapper::map(double azimuth_deg, double elevation_deg, double offset_deg, double hyst_deg)
{
    double rel = geo_wrap360(azimuth_deg - offset_deg);
    if (!flipped_ && rel > 180.0 + hyst_deg)
        flipped_ = true;
    else if (flipped_ && rel < 180.0 - hyst_deg)
        flipped_ = false;

    double el = clampd(elevation_deg, 0.0, 90.0);
    PanTilt r;
    r.flipped = flipped_;
    if (!flipped_) {
        r.pan = (float)clampd(rel, 0.0, 180.0);
        r.tilt = (float)el;
    } else {
        r.pan = (float)clampd(rel - 180.0, 0.0, 180.0);
        r.tilt = (float)(180.0 - el);
    }
    return r;
}

float slew_toward(float cur, float target, float max_step)
{
    float d = target - cur;
    if (d > max_step) return cur + max_step;
    if (d < -max_step) return cur - max_step;
    return target;
}

uint16_t angle_to_us(float angle_deg, uint16_t min_us, uint16_t max_us, bool invert)
{
    if (angle_deg < 0) angle_deg = 0;
    if (angle_deg > 180) angle_deg = 180;
    if (invert) angle_deg = 180.0f - angle_deg;
    return (uint16_t)(min_us + (angle_deg / 180.0f) * (float)(max_us - min_us) + 0.5f);
}
