// Tracker engine: turns drone GPS fixes into smoothed pan/tilt servo commands.
// Pure logic, no hardware access, so it can be unit tested on a PC.
#pragma once
#include <stdint.h>

#include "tracker_config.h"
#include "crsf.h"
#include "geo.h"

class Tracker {
public:
    enum Mode : uint8_t { AUTO, MANUAL };

    TrackerConfig cfg;

    void begin();

    // --- inputs -----------------------------------------------------------------------------
    void onGps(const CrsfGps &gps, uint32_t now_ms);
    // Drone barometric altitude (m above where it was powered), used when cfg.alt_src == 1.
    void onDroneBaro(float alt_m, uint32_t now_ms);
    // Use the drone's current position as the tracker position (drone sitting next to the tracker).
    bool setHomeFromDrone(uint32_t now_ms);
    void setHome(double lat, double lon, float alt_m, uint8_t src = HOME_SRC_MANUAL);
    void clearHome();
    void setAuto();
    void setManual(float pan_deg, float tilt_deg);
    // Call after changing cfg (offset, ...) so the target is recomputed.
    void recompute();
    // Advance the servo slew limiter. Call at a steady rate (e.g. 50 Hz).
    void update(uint32_t now_ms);

    // --- outputs ----------------------------------------------------------------------------
    Mode mode() const { return mode_; }
    bool hasGps() const { return hasGps_; }
    const CrsfGps &gps() const { return gps_; }
    bool geoValid() const { return geoValid_; }
    bool tracking(uint32_t now_ms) const; // auto mode, home set, recent usable GPS
    uint32_t gpsAgeMs(uint32_t now_ms) const { return hasGps_ ? now_ms - gpsMs_ : 0xFFFFFFFFu; }
    double azimuth() const { return az_; }
    double elevation() const { return el_; }
    double groundDistance() const { return dist_; }
    double distance3d() const { return d3_; }
    float pan() const { return curPan_; }
    float tilt() const { return curTilt_; }
    float targetPan() const { return tgtPan_; }
    float targetTilt() const { return tgtTilt_; }
    bool flipped() const { return flipped_; }
    // true when the last elevation used the drone baro instead of GPS altitudes
    bool usedBaro() const { return usedBaro_; }
    double heightAboveHome() const { return dalt_; }
    uint16_t panUs() const;
    uint16_t tiltUs() const;

private:
    bool gpsQualityOk() const;

    Mode mode_ = AUTO;
    CrsfGps gps_ = {};
    bool hasGps_ = false;
    uint32_t gpsMs_ = 0;

    bool geoValid_ = false;
    double az_ = 0, el_ = 0, dist_ = 0, d3_ = 0, dalt_ = 0;
    bool usedBaro_ = false;
    bool hasBaro_ = false;
    float baroAlt_ = 0;
    uint32_t baroMs_ = 0;

    AimMapper mapper_;
    bool flipped_ = false;
    float tgtPan_ = 90, tgtTilt_ = 0;
    float curPan_ = 90, curTilt_ = 0;
    uint32_t lastUpdateMs_ = 0;
    bool firstUpdate_ = true;
};
