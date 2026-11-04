// CRSF (Crossfire) telemetry frame validation and decoding.
//
// Frame layout:  addr(1) len(1) type(1) payload(len-2) crc8_d5(1)
// `len` counts type + payload + crc, so the whole frame is len + 2 bytes. The CRC covers type..payload.
// All multi-byte values are big endian.
#pragma once
#include <stddef.h>
#include <stdint.h>

enum CrsfType : uint8_t {
    CRSF_TYPE_GPS = 0x02,
    CRSF_TYPE_VARIO = 0x07,
    CRSF_TYPE_BATTERY = 0x08,
    CRSF_TYPE_BARO_ALT = 0x09,
    CRSF_TYPE_LINK_STATS = 0x14,
    CRSF_TYPE_ATTITUDE = 0x1E,
    CRSF_TYPE_FLIGHT_MODE = 0x21,
};

#define CRSF_MAX_FRAME 64

struct CrsfFrame {
    uint8_t addr;
    uint8_t type;
    uint8_t payloadLen;
    const uint8_t *payload; // points into the caller's buffer
};

// Validate framing + CRC of a buffer holding exactly one frame.
bool crsf_parse_frame(const uint8_t *buf, size_t n, CrsfFrame *f);

struct CrsfGps {
    int32_t lat_e7;       // degrees * 1e7
    int32_t lon_e7;
    float groundspeed_kmh;
    float heading_deg;
    int32_t alt_m;        // metres above sea level
    uint8_t sats;
};
bool crsf_decode_gps(const CrsfFrame &f, CrsfGps *out);

struct CrsfBattery {
    float volts;
    float amps;
    uint32_t mah;
    uint8_t percent;
};
bool crsf_decode_battery(const CrsfFrame &f, CrsfBattery *out);

struct CrsfLinkStats {
    int8_t up_rssi1_dbm;  // negative dBm
    int8_t up_rssi2_dbm;
    uint8_t up_lq;        // 0..100
    int8_t up_snr;
    uint8_t antenna;
    uint8_t rf_mode;      // raw packet-rate index as reported by ELRS
    uint8_t tx_power_idx; // see crsf_tx_power_mw()
    int8_t dn_rssi_dbm;
    uint8_t dn_lq;
    int8_t dn_snr;
};
bool crsf_decode_link_stats(const CrsfFrame &f, CrsfLinkStats *out);
uint16_t crsf_tx_power_mw(uint8_t idx); // 0 if unknown

struct CrsfAttitude {
    float pitch_deg;
    float roll_deg;
    float yaw_deg;
};
bool crsf_decode_attitude(const CrsfFrame &f, CrsfAttitude *out);

// Copies the (NUL-terminated) flight mode string, truncating to outLen-1.
bool crsf_decode_flight_mode(const CrsfFrame &f, char *out, size_t outLen);
