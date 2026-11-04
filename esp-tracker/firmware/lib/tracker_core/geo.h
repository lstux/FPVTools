// Geodesy helpers and the azimuth/elevation -> pan/tilt servo mapping.
#pragma once
#include <stdint.h>

// Initial great-circle bearing from point 1 to point 2, degrees clockwise from true north [0, 360).
double geo_bearing_deg(double lat1, double lon1, double lat2, double lon2);
// Great-circle (haversine) ground distance in metres.
double geo_distance_m(double lat1, double lon1, double lat2, double lon2);
// Elevation angle of the target seen from the tracker, degrees, clamped to [0, 90].
double geo_elevation_deg(double ground_dist_m, double delta_alt_m);

double geo_wrap360(double deg);

struct PanTilt {
    float pan;   // 0..180
    float tilt;  // 0..180 (0 = horizon on the pan side, 90 = zenith, 180 = horizon on the opposite side)
    bool flipped;
};

// Maps (azimuth, elevation) to the two hobby-servo angles.
//
// Two 180-degree servos cannot cover a full circle by panning alone, so the tilt servo is allowed to
// go past vertical ("over the top"): for targets in the half-plane behind the pan range we pan to
// azimuth-180 and tilt to 180-elevation. `offset` is the azimuth the antenna points at when
// pan = 0 and tilt = 0. A hysteresis band around the 180-degree boundary avoids flip-flopping.
class AimMapper {
public:
    PanTilt map(double azimuth_deg, double elevation_deg, double offset_deg, double hyst_deg);
    void reset() { flipped_ = false; }

private:
    bool flipped_ = false;
};

// Move `cur` toward `target` by at most `max_step`.
float slew_toward(float cur, float target, float max_step);

// Convert a 0..180 degree servo angle to a pulse width in microseconds.
uint16_t angle_to_us(float angle_deg, uint16_t min_us, uint16_t max_us, bool invert);
