#include "compass.h"

#include <math.h>

namespace {

const float RAD2DEG = 57.29577951308232f;

Vec3 cross(const Vec3 &a, const Vec3 &b) { return {a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x}; }
float norm(const Vec3 &a) { return sqrtf(a.x * a.x + a.y * a.y + a.z * a.z); }

} // namespace

float compass_heading(const Vec3 &mag, const Vec3 *accel, float *tilt_deg)
{
    Vec3 up = accel ? *accel : Vec3{0, 0, 1};
    float nu = norm(up);
    if (nu < 1e-6f || norm(mag) < 1e-9f) return -1.0f;
    up = {up.x / nu, up.y / nu, up.z / nu};
    if (tilt_deg) {
        float c = up.z > 1.0f ? 1.0f : (up.z < -1.0f ? -1.0f : up.z);
        *tilt_deg = acosf(c) * RAD2DEG;
    }
    const Vec3 down = {-up.x, -up.y, -up.z};
    Vec3 east = cross(down, mag);
    float ne = norm(east);
    if (ne < 1e-9f) return -1.0f; // field parallel to gravity (magnetic pole...)
    east = {east.x / ne, east.y / ne, east.z / ne};
    const Vec3 north = cross(east, down);
    // heading of the sensor X axis = angle of (1,0,0) in the north/east plane
    float h = atan2f(east.x, north.x) * RAD2DEG;
    if (h < 0) h += 360.0f;
    if (h >= 360.0f) h -= 360.0f;
    return h;
}

// ---- calibration ---------------------------------------------------------------------------------

void magcal_identity(MagCalibration *c)
{
    c->valid = false;
    for (int i = 0; i < 3; ++i) {
        c->off[i] = 0;
        c->scale[i] = 1;
    }
}

Vec3 magcal_apply(const MagCalibration &c, const Vec3 &r)
{
    return {(r.x - c.off[0]) * c.scale[0], (r.y - c.off[1]) * c.scale[1], (r.z - c.off[2]) * c.scale[2]};
}

void MagCalibrator::start()
{
    active_ = true;
    n_ = 0;
    kn_ = 0;
    for (int i = 0; i < 3; ++i) {
        min_[i] = 1e30f;
        max_[i] = -1e30f;
    }
}

void MagCalibrator::add(const Vec3 &r)
{
    if (!active_) return;
    const float v[3] = {r.x, r.y, r.z};
    for (int i = 0; i < 3; ++i) {
        if (v[i] < min_[i]) min_[i] = v[i];
        if (v[i] > max_[i]) max_[i] = v[i];
    }
    if ((n_ & 1) == 0) {
        int k = kn_ < KEEP ? kn_ : (int)((n_ / 2) % KEEP);
        kx_[k] = r.x;
        ky_[k] = r.y;
        if (kn_ < KEEP) ++kn_;
    }
    ++n_;
}

bool MagCalibrator::fitXY(float *cx, float *cy, float *ax, float *ay) const
{
    // A x^2 + y^2 + D x + E y + F = 0, least squares on (A, D, E, F). Work relative to the mean
    // to keep the normal equations well conditioned (float, values in the hundreds).
    if (kn_ < 8) return false;
    double mx = 0, my = 0;
    for (int i = 0; i < kn_; ++i) { mx += kx_[i]; my += ky_[i]; }
    mx /= kn_;
    my /= kn_;
    double M[4][5] = {{0}};
    for (int i = 0; i < kn_; ++i) {
        const double x = kx_[i] - mx, y = ky_[i] - my;
        const double row[4] = {x * x, x, y, 1.0};
        const double rhs = -y * y;
        for (int r = 0; r < 4; ++r) {
            for (int c = 0; c < 4; ++c) M[r][c] += row[r] * row[c];
            M[r][4] += row[r] * rhs;
        }
    }
    for (int col = 0; col < 4; ++col) { // Gaussian elimination with partial pivoting
        int piv = col;
        for (int r = col + 1; r < 4; ++r)
            if (fabs(M[r][col]) > fabs(M[piv][col])) piv = r;
        if (fabs(M[piv][col]) < 1e-12) return false;
        if (piv != col)
            for (int c = 0; c < 5; ++c) { double t = M[col][c]; M[col][c] = M[piv][c]; M[piv][c] = t; }
        for (int r = 0; r < 4; ++r) {
            if (r == col) continue;
            const double f = M[r][col] / M[col][col];
            for (int c = col; c < 5; ++c) M[r][c] -= f * M[col][c];
        }
    }
    const double A = M[0][4] / M[0][0], D = M[1][4] / M[1][1], E = M[2][4] / M[2][2], F = M[3][4] / M[3][3];
    if (A <= 0) return false; // not an ellipse (e.g. all samples on a line)
    const double x0 = -D / (2 * A), y0 = -E / 2;
    const double k = A * x0 * x0 + y0 * y0 - F; // A (x-x0)^2 + (y-y0)^2 = k
    if (k <= 0) return false;
    *cx = (float)(x0 + mx);
    *cy = (float)(y0 + my);
    *ax = (float)sqrt(k / A);
    *ay = (float)sqrt(k);
    return true;
}

uint8_t MagCalibrator::coverage() const
{
    if (kn_ < 8) return 0;
    float cx, cy, rx, ry;
    if (!fitXY(&cx, &cy, &rx, &ry)) return 0;
    uint64_t bins = 0;
    for (int i = 0; i < kn_; ++i) {
        float a = atan2f((ky_[i] - cy) / ry, (kx_[i] - cx) / rx) * RAD2DEG + 180.0f; // 0..360
        int b = (int)(a / 10.0f);
        if (b >= 36) b = 35;
        if (b < 0) b = 0;
        bins |= (uint64_t)1 << b;
    }
    int seen = 0;
    for (int b = 0; b < 36; ++b) seen += (bins >> b) & 1;
    return (uint8_t)(seen * 100 / 36);
}

bool MagCalibrator::finish(MagCalibration *out, const char **why)
{
    const uint8_t cov = coverage();
    active_ = false;
    if (n_ < 50) {
        *why = "not enough samples (turn the tracker slowly for ~20 s)";
        return false;
    }
    if (cov < 80) {
        *why = "incomplete turn: rotate the tracker a full 360 deg, flat";
        return false;
    }
    float range[3], centre[3];
    for (int i = 0; i < 3; ++i) {
        range[i] = max_[i] - min_[i];
        centre[i] = (max_[i] + min_[i]) / 2.0f;
    }
    // A tracker turned flat only sees the vertical field, so min/max on Z says nothing about its
    // offset: calibrate Z only when the sensor was really tumbled (Z swung about as much as X/Y).
    const bool doZ = range[2] >= 0.6f * (range[0] + range[1]) / 2.0f;
    if (!doZ) {
        // flat turn: X/Y from an ellipse fit, less sensitive than min/max to the odd spike
        float cx, cy, ax, ay;
        if (!fitXY(&cx, &cy, &ax, &ay)) {
            *why = "could not fit the data (is the compass connected?)";
            return false;
        }
        centre[0] = cx;
        centre[1] = cy;
        range[0] = 2 * ax;
        range[1] = 2 * ay;
    }
    const float avg = doZ ? (range[0] + range[1] + range[2]) / 3.0f : (range[0] + range[1]) / 2.0f;
    for (int i = 0; i < 3; ++i) {
        if (i < 2 || doZ) {
            out->off[i] = centre[i];
            out->scale[i] = avg / range[i];
        } else {
            out->off[i] = 0;
            out->scale[i] = 1;
        }
    }
    out->valid = true;
    return true;
}

// ---- angle filter --------------------------------------------------------------------------------

float AngleFilter::update(float deg, float alpha)
{
    const float r = deg / RAD2DEG;
    if (!init_) {
        s_ = sinf(r);
        c_ = cosf(r);
        init_ = true;
    } else {
        s_ += alpha * (sinf(r) - s_);
        c_ += alpha * (cosf(r) - c_);
    }
    return value();
}

float AngleFilter::value() const
{
    float h = atan2f(s_, c_) * RAD2DEG;
    return h < 0 ? h + 360.0f : h;
}

// ---- auto home -----------------------------------------------------------------------------------

void AutoHome::reset()
{
    state_ = WAITING;
    n_ = 0;
    sLat_ = sLon_ = sAlt_ = 0;
}

bool AutoHome::feed(const NmeaFix &f, uint32_t now_ms, uint8_t min_sats, float max_hdop)
{
    if (state_ == LOCKED) return false;
    if (!f.valid || f.sats < min_sats || f.hdop > max_hdop) return false;
    if (n_ > 0 && now_ms - lastMs_ < SPACING_MS) return false;
    lastMs_ = now_ms;
    state_ = AVERAGING;
    sLat_ += f.lat;
    sLon_ += f.lon;
    sAlt_ += f.alt_m;
    ++n_;
    if (n_ < SAMPLES) return false;
    lat_ = sLat_ / n_;
    lon_ = sLon_ / n_;
    alt_ = (float)(sAlt_ / n_);
    state_ = LOCKED;
    return true;
}
