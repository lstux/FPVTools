#include "crsf.h"

#include <math.h>
#include <string.h>

#include "crc8.h"

namespace {

inline uint16_t be16(const uint8_t *p) { return (uint16_t)((p[0] << 8) | p[1]); }
inline int16_t bes16(const uint8_t *p) { return (int16_t)be16(p); }
inline uint32_t be32(const uint8_t *p)
{
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | (uint32_t)p[3];
}

const float RAD2DEG = 57.29577951308232f;

} // namespace

bool crsf_parse_frame(const uint8_t *buf, size_t n, CrsfFrame *f)
{
    if (n < 4 || n > CRSF_MAX_FRAME) return false;
    uint8_t len = buf[1];
    if (len < 2 || (size_t)len + 2 != n) return false;
    // CRC over type + payload = bytes [2, len] i.e. len-1 bytes
    if (crc8_d5(buf + 2, (size_t)len - 1) != buf[len + 1]) return false;
    f->addr = buf[0];
    f->type = buf[2];
    f->payloadLen = (uint8_t)(len - 2);
    f->payload = buf + 3;
    return true;
}

bool crsf_decode_gps(const CrsfFrame &f, CrsfGps *out)
{
    if (f.type != CRSF_TYPE_GPS || f.payloadLen < 15) return false;
    const uint8_t *p = f.payload;
    out->lat_e7 = (int32_t)be32(p);
    out->lon_e7 = (int32_t)be32(p + 4);
    out->groundspeed_kmh = be16(p + 8) / 10.0f;
    out->heading_deg = be16(p + 10) / 100.0f;
    out->alt_m = (int32_t)be16(p + 12) - 1000;
    out->sats = p[14];
    return true;
}

bool crsf_decode_battery(const CrsfFrame &f, CrsfBattery *out)
{
    if (f.type != CRSF_TYPE_BATTERY || f.payloadLen < 8) return false;
    const uint8_t *p = f.payload;
    out->volts = be16(p) / 10.0f;
    out->amps = be16(p + 2) / 10.0f;
    out->mah = ((uint32_t)p[4] << 16) | ((uint32_t)p[5] << 8) | p[6];
    out->percent = p[7];
    return true;
}

bool crsf_decode_link_stats(const CrsfFrame &f, CrsfLinkStats *out)
{
    if (f.type != CRSF_TYPE_LINK_STATS || f.payloadLen < 10) return false;
    const uint8_t *p = f.payload;
    out->up_rssi1_dbm = (int8_t)(-(int)p[0]);
    out->up_rssi2_dbm = (int8_t)(-(int)p[1]);
    out->up_lq = p[2];
    out->up_snr = (int8_t)p[3];
    out->antenna = p[4];
    out->rf_mode = p[5];
    out->tx_power_idx = p[6];
    out->dn_rssi_dbm = (int8_t)(-(int)p[7]);
    out->dn_lq = p[8];
    out->dn_snr = (int8_t)p[9];
    return true;
}

uint16_t crsf_tx_power_mw(uint8_t idx)
{
    static const uint16_t table[] = {0, 10, 25, 100, 500, 1000, 2000, 250, 50};
    return idx < sizeof(table) / sizeof(table[0]) ? table[idx] : 0;
}

bool crsf_decode_attitude(const CrsfFrame &f, CrsfAttitude *out)
{
    if (f.type != CRSF_TYPE_ATTITUDE || f.payloadLen < 6) return false;
    const uint8_t *p = f.payload;
    out->pitch_deg = bes16(p) / 10000.0f * RAD2DEG;
    out->roll_deg = bes16(p + 2) / 10000.0f * RAD2DEG;
    out->yaw_deg = bes16(p + 4) / 10000.0f * RAD2DEG;
    return true;
}

bool crsf_decode_vario(const CrsfFrame &f, float *vspeed_ms)
{
    if (f.type != CRSF_TYPE_VARIO || f.payloadLen < 2) return false;
    *vspeed_ms = bes16(f.payload) / 100.0f;
    return true;
}

bool crsf_decode_baro(const CrsfFrame &f, CrsfBaro *out)
{
    if (f.type != CRSF_TYPE_BARO_ALT || f.payloadLen < 2) return false;
    const uint8_t *p = f.payload;
    uint16_t packed = be16(p);
    if (packed & 0x8000) out->alt_m = (float)(packed & 0x7fff);
    else out->alt_m = ((int32_t)packed - 10000) / 10.0f;
    out->has_vspeed = false;
    out->vspeed_ms = 0.0f;
    if (f.payloadLen >= 4) {
        out->has_vspeed = true;
        out->vspeed_ms = bes16(p + 2) / 100.0f;
    } else if (f.payloadLen == 3) {
        int8_t v = (int8_t)p[2];
        int a = v < 0 ? -v : v;
        float cms = (expf(a * 0.026f) - 1.0f) * 100.0f;
        out->has_vspeed = true;
        out->vspeed_ms = (v < 0 ? -cms : cms) / 100.0f;
    }
    return true;
}

bool crsf_decode_flight_mode(const CrsfFrame &f, char *out, size_t outLen)
{
    if (f.type != CRSF_TYPE_FLIGHT_MODE || outLen == 0) return false;
    size_t n = 0;
    while (n < f.payloadLen && f.payload[n] != 0) ++n;
    if (n >= outLen) n = outLen - 1;
    memcpy(out, f.payload, n);
    out[n] = '\0';
    return true;
}
