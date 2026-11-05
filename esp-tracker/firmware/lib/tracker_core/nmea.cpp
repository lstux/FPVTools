#include "nmea.h"

#include <stdlib.h>
#include <string.h>

namespace {

int hexval(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    return -1;
}

// Split in place on ',' (empty fields stay empty strings). Returns the field count.
int split(char *s, char **f, int max)
{
    int n = 0;
    f[n++] = s;
    for (char *p = s; *p && n < max; ++p) {
        if (*p == ',') {
            *p = '\0';
            f[n++] = p + 1;
        }
    }
    return n;
}

} // namespace

bool nmea_parse_coord(const char *val, const char *hemi, double *out)
{
    if (!val || !*val || !hemi || !*hemi) return false;
    const char *dot = strchr(val, '.');
    size_t intLen = dot ? (size_t)(dot - val) : strlen(val);
    if (intLen < 3) return false; // at least D + MM
    char *end = nullptr;
    double raw = strtod(val, &end);
    if (end == val) return false;
    double deg = (double)(long)(raw / 100.0);
    double min = raw - deg * 100.0;
    if (min < 0 || min >= 60) return false;
    double v = deg + min / 60.0;
    if (*hemi == 'S' || *hemi == 'W') v = -v;
    else if (*hemi != 'N' && *hemi != 'E') return false;
    *out = v;
    return true;
}

void NmeaParser::reset()
{
    len_ = 0;
    inSentence_ = false;
    rmcValid_ = true;
    fix_ = {false, 0, 0, 99.9f, 0, 0, 0, 0};
    good = bad = 0;
}

bool NmeaParser::feed(char c)
{
    if (c == '$') {
        inSentence_ = true;
        len_ = 0;
        return false;
    }
    if (!inSentence_) return false;
    if (c == '\r' || c == '\n') {
        inSentence_ = false;
        buf_[len_] = '\0';
        return parseSentence();
    }
    if (len_ >= sizeof(buf_) - 1) { // too long: not NMEA
        inSentence_ = false;
        ++bad;
        return false;
    }
    buf_[len_++] = c;
    return false;
}

bool NmeaParser::parseSentence()
{
    // buf_ = "GPGGA,....*hh"
    char *star = strrchr(buf_, '*');
    if (!star || strlen(star) < 3) {
        ++bad;
        return false;
    }
    uint8_t sum = 0;
    for (char *p = buf_; p < star; ++p) sum ^= (uint8_t)*p;
    int hi = hexval(star[1]), lo = hexval(star[2]);
    if (hi < 0 || lo < 0 || sum != (uint8_t)(hi * 16 + lo)) {
        ++bad;
        return false;
    }
    *star = '\0';
    ++good;
    if (strlen(buf_) < 6) return false;
    const char *type = buf_ + 2; // skip talker id

    char *f[20];
    int n = split(buf_, f, 20);

    if (strncmp(type, "GGA", 3) == 0 && n >= 10) {
        // 0 GxGGA,1 time,2 lat,3 N,4 lon,5 E,6 quality,7 sats,8 hdop,9 alt,10 M,...
        int q = atoi(f[6]);
        fix_.quality = (uint8_t)(q < 0 ? 0 : q > 9 ? 9 : q);
        fix_.sats = (uint8_t)atoi(f[7]);
        fix_.hdop = *f[8] ? (float)atof(f[8]) : 99.9f;
        double lat, lon;
        bool pos = nmea_parse_coord(f[2], f[3], &lat) && nmea_parse_coord(f[4], f[5], &lon);
        if (pos) {
            fix_.lat = lat;
            fix_.lon = lon;
        }
        if (*f[9]) fix_.alt_m = (float)atof(f[9]);
        fix_.valid = pos && fix_.quality >= 1 && rmcValid_;
        ++fix_.updates;
        return true;
    }
    if (strncmp(type, "RMC", 3) == 0 && n >= 3) {
        // 0 GxRMC,1 time,2 status A/V,...
        rmcValid_ = f[2][0] == 'A';
        if (!rmcValid_) fix_.valid = false;
        return true;
    }
    return false;
}
