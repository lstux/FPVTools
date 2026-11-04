// Minimal NMEA 0183 reader for a GPS module wired to the tracker (BN-880, BN-220, NEO-6M/M8N...).
// Uses GGA (position, fix quality, satellites, HDOP, altitude) and RMC (validity). Any talker
// ($GP, $GN, $GL, $GA, $GB) is accepted. Sentences with a bad checksum are rejected.
#pragma once
#include <stddef.h>
#include <stdint.h>

struct NmeaFix {
    bool valid;        // GGA says fix quality >= 1 (and RMC, if seen, says 'A')
    uint8_t quality;   // GGA fix quality: 0 none, 1 GPS, 2 DGPS/SBAS, 4/5 RTK, 6 dead reckoning
    uint8_t sats;
    float hdop;        // 99.9 when unknown
    double lat, lon;   // degrees
    float alt_m;       // above mean sea level
    uint32_t updates;  // number of GGA sentences accepted
};

class NmeaParser {
public:
    // Feed one character. Returns true when a complete, valid GGA/RMC sentence updated `fix`.
    bool feed(char c);
    const NmeaFix &fix() const { return fix_; }

    uint32_t good = 0;     // sentences with a valid checksum (any type)
    uint32_t bad = 0;      // checksum errors / malformed
    void reset();

private:
    bool parseSentence();
    char buf_[96];
    size_t len_ = 0;
    bool inSentence_ = false;
    bool rmcValid_ = true;
    NmeaFix fix_ = {false, 0, 0, 99.9f, 0, 0, 0, 0};
};

// Exposed for tests: "4807.038", "N" -> 48.1173
bool nmea_parse_coord(const char *val, const char *hemi, double *out);
