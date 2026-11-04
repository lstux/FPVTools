#include "tracker.h"

#include <math.h>

void Tracker::begin()
{
    cfg_default(&cfg);
    mode_ = AUTO;
    hasGps_ = false;
    geoValid_ = false;
    mapper_.reset();
    flipped_ = false;
    tgtPan_ = curPan_ = 90;
    tgtTilt_ = curTilt_ = 0;
    firstUpdate_ = true;
}

bool Tracker::gpsQualityOk() const
{
    return hasGps_ && gps_.sats >= cfg.min_sats && !(gps_.lat_e7 == 0 && gps_.lon_e7 == 0);
}

void Tracker::onGps(const CrsfGps &gps, uint32_t now_ms)
{
    gps_ = gps;
    gpsMs_ = now_ms;
    hasGps_ = true;
    recompute();
}

void Tracker::recompute()
{
    if (!cfg.home_valid || !gpsQualityOk()) {
        // Keep the last target (hold position) but flag the geometry as unavailable
        // when there is no home at all.
        if (!cfg.home_valid) geoValid_ = false;
        return;
    }
    const double lat = gps_.lat_e7 / 1e7, lon = gps_.lon_e7 / 1e7;
    az_ = geo_bearing_deg(cfg.home_lat, cfg.home_lon, lat, lon);
    dist_ = geo_distance_m(cfg.home_lat, cfg.home_lon, lat, lon);
    const double dalt = (double)gps_.alt_m - (double)cfg.home_alt;
    el_ = geo_elevation_deg(dist_, dalt);
    d3_ = sqrt(dist_ * dist_ + dalt * dalt);
    geoValid_ = true;

    if (mode_ == AUTO) {
        PanTilt pt = mapper_.map(az_, el_, cfg.offset_deg, cfg.hyst_deg);
        tgtPan_ = pt.pan;
        tgtTilt_ = pt.tilt;
        flipped_ = pt.flipped;
    }
}

bool Tracker::setHomeFromDrone(uint32_t now_ms)
{
    if (!gpsQualityOk() || (now_ms - gpsMs_) > cfg.lost_ms) return false;
    setHome(gps_.lat_e7 / 1e7, gps_.lon_e7 / 1e7, (float)gps_.alt_m);
    return true;
}

void Tracker::setHome(double lat, double lon, float alt_m)
{
    cfg.home_valid = 1;
    cfg.home_lat = lat;
    cfg.home_lon = lon;
    cfg.home_alt = alt_m;
    recompute();
}

void Tracker::clearHome()
{
    cfg.home_valid = 0;
    geoValid_ = false;
}

void Tracker::setAuto()
{
    mode_ = AUTO;
    recompute();
}

void Tracker::setManual(float pan_deg, float tilt_deg)
{
    mode_ = MANUAL;
    tgtPan_ = pan_deg < 0 ? 0 : (pan_deg > 180 ? 180 : pan_deg);
    tgtTilt_ = tilt_deg < 0 ? 0 : (tilt_deg > 180 ? 180 : tilt_deg);
}

bool Tracker::tracking(uint32_t now_ms) const
{
    return mode_ == AUTO && cfg.home_valid && geoValid_ && gpsQualityOk() && (now_ms - gpsMs_) <= cfg.lost_ms;
}

void Tracker::update(uint32_t now_ms)
{
    if (firstUpdate_) {
        firstUpdate_ = false;
        lastUpdateMs_ = now_ms;
        return;
    }
    uint32_t dt = now_ms - lastUpdateMs_;
    lastUpdateMs_ = now_ms;
    if (dt > 200) dt = 200;
    const float step = cfg.slew_dps * (float)dt / 1000.0f;
    curPan_ = slew_toward(curPan_, tgtPan_, step);
    curTilt_ = slew_toward(curTilt_, tgtTilt_, step);
}

uint16_t Tracker::panUs() const { return angle_to_us(curPan_, cfg.pan_min_us, cfg.pan_max_us, cfg.pan_invert); }
uint16_t Tracker::tiltUs() const { return angle_to_us(curTilt_, cfg.tilt_min_us, cfg.tilt_max_us, cfg.tilt_invert); }
