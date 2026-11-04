// Tilt-compensated compass heading + magnetometer calibration, and tracker auto-home from its own GPS.
// Pure maths (no I2C), unit tested on a PC.
#pragma once
#include <stdint.h>

#include "nmea.h"

struct Vec3 {
    float x, y, z;
};

// Heading of the sensor's +X axis, degrees clockwise from MAGNETIC north (0..360), or a negative value
// if the vectors are degenerate. `accel` is the accelerometer reading (any unit; +Z reads +1 g when
// the board lies flat, component side up); pass nullptr when there is no accelerometer: the board is
// then assumed level. Works for any tilt because it builds north/east from the gravity and field
// vectors instead of using roll/pitch formulas. `tilt_deg` (optional) gets the angle from level.
float compass_heading(const Vec3 &mag, const Vec3 *accel, float *tilt_deg);

// Hard-iron offsets + per-axis scale (simple soft-iron) from the min/max seen while the tracker is
// turned through all orientations it can take (a full turn flat, then tilted a bit).
struct MagCalibration {
    bool valid;
    float off[3];
    float scale[3];
};
void magcal_identity(MagCalibration *c);
Vec3 magcal_apply(const MagCalibration &c, const Vec3 &raw);

class MagCalibrator {
public:
    void start();
    void add(const Vec3 &raw);
    // Ends the session. Returns false (and leaves `out` untouched) if the data does not cover enough
    // of the sphere: then `why` says what was missing.
    bool finish(MagCalibration *out, const char **why);
    bool active() const { return active_; }
    uint32_t samples() const { return n_; }
    // 0..100: share of the 36 ten-degree sectors of a full horizontal turn seen so far
    uint8_t coverage() const;

private:
    // axis-aligned ellipse fit of the kept horizontal samples: centre and semi-axes
    bool fitXY(float *cx, float *cy, float *ax, float *ay) const;
    static const int KEEP = 360; // horizontal samples kept for the coverage estimate (every 2nd)
    bool active_ = false;
    uint32_t n_ = 0;
    float min_[3], max_[3];
    float kx_[KEEP], ky_[KEEP];
    int kn_ = 0;
};

// Circular low-pass filter for an angle (no jump at 359 -> 0).
class AngleFilter {
public:
    float update(float deg, float alpha); // alpha in (0,1]: weight of the new sample
    bool ready() const { return init_; }
    float value() const;
    void reset() { init_ = false; }

private:
    bool init_ = false;
    float s_ = 0, c_ = 0;
};

// Averages the tracker's own GPS for a while after it gets a good fix, then locks a home position.
class AutoHome {
public:
    enum State : uint8_t { WAITING, AVERAGING, LOCKED };
    static const uint16_t SAMPLES = 20;    // good fixes to average
    static const uint32_t SPACING_MS = 500; // min time between two samples

    void reset();
    // Returns true exactly once, when the position gets locked.
    bool feed(const NmeaFix &fix, uint32_t now_ms, uint8_t min_sats, float max_hdop = 2.5f);
    State state() const { return state_; }
    uint8_t progress() const { return (uint8_t)(n_ * 100 / SAMPLES); }
    double lat() const { return lat_; }
    double lon() const { return lon_; }
    float alt() const { return alt_; }

private:
    State state_ = WAITING;
    uint16_t n_ = 0;
    uint32_t lastMs_ = 0;
    double sLat_ = 0, sLon_ = 0, sAlt_ = 0;
    double lat_ = 0, lon_ = 0;
    float alt_ = 0;
};
