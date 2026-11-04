// Host-side unit tests for the portable core (no ESP toolchain needed).
//   make -C firmware/tests test
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "crc8.h"
#include "crsf.h"
#include "geo.h"
#include "md5.h"
#include "msp.h"
#include "proto.h"
#include "tracker.h"

static int g_fail = 0, g_checks = 0;

#define CHECK(cond)                                                                   \
    do {                                                                              \
        ++g_checks;                                                                   \
        if (!(cond)) {                                                                \
            ++g_fail;                                                                 \
            printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);                    \
        }                                                                             \
    } while (0)

#define CHECK_NEAR(a, b, tol)                                                         \
    do {                                                                              \
        ++g_checks;                                                                   \
        double _a = (a), _b = (b);                                                    \
        if (fabs(_a - _b) > (tol)) {                                                  \
            ++g_fail;                                                                 \
            printf("FAIL %s:%d: %s = %.6f, expected %.6f (+-%g)\n", __FILE__, __LINE__, #a, _a, _b, (double)(tol)); \
        }                                                                             \
    } while (0)

static void hex(const uint8_t *d, size_t n, char *out)
{
    for (size_t i = 0; i < n; ++i) sprintf(out + i * 2, "%02x", d[i]);
    out[n * 2] = 0;
}

// ---- helpers building wire data the way ELRS does ------------------------------------------------

static size_t build_crsf(uint8_t type, const uint8_t *payload, size_t plen, uint8_t *out, uint8_t addr = 0xEA)
{
    out[0] = addr;
    out[1] = (uint8_t)(plen + 2);
    out[2] = type;
    memcpy(out + 3, payload, plen);
    out[3 + plen] = crc8_d5(out + 2, plen + 1);
    return plen + 4;
}

static size_t build_msp(uint16_t function, const uint8_t *payload, size_t plen, uint8_t *out)
{
    size_t p = 0;
    out[p++] = '$';
    out[p++] = 'X';
    out[p++] = '<';
    uint8_t crc = 0;
    uint8_t hdr[5] = {0, (uint8_t)(function & 0xFF), (uint8_t)(function >> 8), (uint8_t)(plen & 0xFF), (uint8_t)(plen >> 8)};
    for (int i = 0; i < 5; ++i) {
        out[p++] = hdr[i];
        crc = crc8_d5_update(crc, hdr[i]);
    }
    for (size_t i = 0; i < plen; ++i) {
        out[p++] = payload[i];
        crc = crc8_d5_update(crc, payload[i]);
    }
    out[p++] = crc;
    return p;
}

static size_t gps_frame(int32_t lat_e7, int32_t lon_e7, uint16_t speed_dkmh, uint16_t hdg_cdeg, int alt_m, uint8_t sats,
                        uint8_t *out)
{
    uint8_t p[15];
    for (int i = 0; i < 4; ++i) {
        p[i] = (uint8_t)((uint32_t)lat_e7 >> (24 - 8 * i));
        p[4 + i] = (uint8_t)((uint32_t)lon_e7 >> (24 - 8 * i));
    }
    p[8] = speed_dkmh >> 8; p[9] = speed_dkmh & 0xFF;
    p[10] = hdg_cdeg >> 8; p[11] = hdg_cdeg & 0xFF;
    uint16_t a = (uint16_t)(alt_m + 1000);
    p[12] = a >> 8; p[13] = a & 0xFF;
    p[14] = sats;
    return build_crsf(CRSF_TYPE_GPS, p, sizeof(p), out);
}

// ---- tests --------------------------------------------------------------------------------------

static void test_crc8()
{
    const uint8_t s[] = {'1', '2', '3', '4', '5', '6', '7', '8', '9'};
    CHECK(crc8_d5(s, sizeof(s)) == 0xBC); // CRC-8/DVB-S2 check value
}

static void test_md5()
{
    struct V { size_t n; const char *hex; } v[] = {
        {0, "d41d8cd98f00b204e9800998ecf8427e"},   {1, "8666683506aacd900bbd5a74ac4edf68"},
        {55, "52c0e574e1198de5fe3f8f11440dcb1b"},  {56, "46c9907fc908ee68b1e7b8e71286a518"},
        {63, "a62f6d59e837867693f042f5b8f5a236"},  {64, "7160b8fb5e9e4023d549c3971fbaeead"},
        {65, "70bd662e7aefbda85a0f7244167b7897"},  {119, "e84905d4214f4d1ca56c2cdcc152b143"},
        {120, "e3eb5a6c8669ea01a8c185b8abc8a5dc"}, {128, "10b2da1a82f16d99a81a7203fe9f02cb"},
        {200, "4c79b81ac94bad7a875519ce6b964c66"},
    };
    uint8_t buf[256];
    for (size_t i = 0; i < sizeof(buf); ++i) buf[i] = (uint8_t)((i * 7 + 3) % 256);
    for (auto &t : v) {
        uint8_t d[16];
        char h[33];
        md5(buf, t.n, d);
        hex(d, 16, h);
        if (strcmp(h, t.hex) != 0) printf("md5 len %zu: got %s want %s\n", t.n, h, t.hex);
        CHECK(strcmp(h, t.hex) == 0);
    }
}

static void test_uid()
{
    uint8_t uid[6];
    char h[13];
    CHECK(uid_from_phrase("my phrase", uid));
    hex(uid, 6, h);
    CHECK(strcmp(h, "3b933b37b1e4") == 0);
    CHECK(uid_from_phrase("a", uid));
    hex(uid, 6, h);
    CHECK(strcmp(h, "f7c920620818") == 0);
    CHECK(!uid_from_phrase("", uid));

    uint8_t mac[6];
    uint8_t odd[6] = {0xF7, 1, 2, 3, 4, 5};
    uid_to_mac(odd, mac);
    CHECK(mac[0] == 0xF6 && mac[5] == 5);

    CHECK(uid_parse("3b:93:3b:37:b1:e4", uid));
    hex(uid, 6, h);
    CHECK(strcmp(h, "3b933b37b1e4") == 0);
    CHECK(uid_parse("3B933B37B1E4", uid));
    CHECK(uid_parse("59,147,59,55,177,228", uid));
    hex(uid, 6, h);
    CHECK(strcmp(h, "3b933b37b1e4") == 0);
    CHECK(uid_parse("59, 147, 59, 55, 177, 228", uid));
    CHECK(!uid_parse("59,147,59,55,177", uid));
    CHECK(!uid_parse("59,147,59,55,177,256", uid));
    CHECK(!uid_parse("3b933b37b1e", uid));
    CHECK(!uid_parse("zz933b37b1e4", uid));
}

static void test_msp()
{
    uint8_t crsf[64], msp[128];
    size_t cn = gps_frame(481234567, -16543210, 453, 18230, 120, 12, crsf);
    size_t mn = build_msp(MSP_ELRS_BACKPACK_CRSF_TLM, crsf, cn, msp);

    MspParser p;
    MspPacket pkt;
    int got = 0;
    for (size_t i = 0; i < mn; ++i)
        if (p.feed(msp[i], &pkt)) ++got;
    CHECK(got == 1);
    CHECK(pkt.function == MSP_ELRS_BACKPACK_CRSF_TLM);
    CHECK(pkt.size == cn);
    CHECK(memcmp(pkt.payload, crsf, cn) == 0);

    // garbage before + two packets back to back
    uint8_t two[300];
    size_t n = 0;
    two[n++] = 0x55; two[n++] = '$'; two[n++] = 'M';
    memcpy(two + n, msp, mn); n += mn;
    memcpy(two + n, msp, mn); n += mn;
    got = 0;
    for (size_t i = 0; i < n; ++i)
        if (p.feed(two[i], &pkt)) ++got;
    CHECK(got == 2);

    // corrupted CRC
    msp[mn - 1] ^= 0x40;
    got = 0;
    for (size_t i = 0; i < mn; ++i)
        if (p.feed(msp[i], &pkt)) ++got;
    CHECK(got == 0);
    CHECK(p.crcErrors == 1);

    // oversize payload is rejected without overflowing
    uint8_t big[8] = {'$', 'X', '<', 0, 0x11, 0x00, 0xFF, 0x00};
    for (size_t i = 0; i < sizeof(big); ++i) p.feed(big[i], &pkt);
    CHECK(p.oversize == 1);
}

static void test_crsf()
{
    uint8_t f[64];
    CrsfFrame fr;

    size_t n = gps_frame(481234567, -16543210, 453, 18230, 120, 12, f);
    CHECK(crsf_parse_frame(f, n, &fr));
    CHECK(fr.type == CRSF_TYPE_GPS && fr.payloadLen == 15);
    CrsfGps g;
    CHECK(crsf_decode_gps(fr, &g));
    CHECK(g.lat_e7 == 481234567 && g.lon_e7 == -16543210);
    CHECK_NEAR(g.groundspeed_kmh, 45.3, 1e-3);
    CHECK_NEAR(g.heading_deg, 182.3, 1e-3);
    CHECK(g.alt_m == 120 && g.sats == 12);

    // negative altitude (below sea level) and southern/western hemisphere
    n = gps_frame(-337000000, -706000000, 0, 0, -50, 3, f);
    CHECK(crsf_parse_frame(f, n, &fr) && crsf_decode_gps(fr, &g));
    CHECK(g.lat_e7 == -337000000 && g.alt_m == -50);

    // corrupt CRC / wrong length / truncated
    uint8_t bad[64];
    memcpy(bad, f, n);
    bad[5] ^= 1;
    CHECK(!crsf_parse_frame(bad, n, &fr));
    CHECK(!crsf_parse_frame(f, n - 1, &fr));
    CHECK(!crsf_parse_frame(f, n + 1, &fr));
    CHECK(!crsf_parse_frame(f, 3, &fr));

    // battery: 16.4 V, 12.5 A, 432 mAh, 70 %
    uint8_t b[8] = {0, 164, 0, 125, 0x00, 0x01, 0xB0, 70};
    n = build_crsf(CRSF_TYPE_BATTERY, b, sizeof(b), f);
    CrsfBattery bat;
    CHECK(crsf_parse_frame(f, n, &fr) && crsf_decode_battery(fr, &bat));
    CHECK_NEAR(bat.volts, 16.4, 1e-3);
    CHECK_NEAR(bat.amps, 12.5, 1e-3);
    CHECK(bat.mah == 432 && bat.percent == 70);

    // link stats
    uint8_t l[10] = {60, 62, 99, (uint8_t)-3 /* snr -3 */, 1, 6, 3, 70, 98, 8};
    n = build_crsf(CRSF_TYPE_LINK_STATS, l, sizeof(l), f);
    CrsfLinkStats ls;
    CHECK(crsf_parse_frame(f, n, &fr) && crsf_decode_link_stats(fr, &ls));
    CHECK(ls.up_rssi1_dbm == -60 && ls.up_rssi2_dbm == -62 && ls.up_lq == 99 && ls.up_snr == -3);
    CHECK(ls.antenna == 1 && ls.rf_mode == 6 && crsf_tx_power_mw(ls.tx_power_idx) == 100);
    CHECK(ls.dn_rssi_dbm == -70 && ls.dn_lq == 98 && ls.dn_snr == 8);

    // attitude: pitch 0.5236 rad (30 deg), roll -0.1745 rad (-10 deg), yaw 3.1416 rad (180 deg)
    int16_t pr[3] = {5236, -1745, 31416};
    uint8_t a[6];
    for (int i = 0; i < 3; ++i) { a[i * 2] = (uint8_t)((uint16_t)pr[i] >> 8); a[i * 2 + 1] = (uint8_t)(pr[i] & 0xFF); }
    n = build_crsf(CRSF_TYPE_ATTITUDE, a, sizeof(a), f);
    CrsfAttitude at;
    CHECK(crsf_parse_frame(f, n, &fr) && crsf_decode_attitude(fr, &at));
    CHECK_NEAR(at.pitch_deg, 30.0, 0.01);
    CHECK_NEAR(at.roll_deg, -10.0, 0.01);
    CHECK_NEAR(at.yaw_deg, 180.0, 0.01);

    // flight mode
    const uint8_t fm[] = {'A', 'C', 'R', 'O', '*', 0};
    n = build_crsf(CRSF_TYPE_FLIGHT_MODE, fm, sizeof(fm), f);
    char mode[8];
    CHECK(crsf_parse_frame(f, n, &fr) && crsf_decode_flight_mode(fr, mode, sizeof(mode)));
    CHECK(strcmp(mode, "ACRO*") == 0);
    char tiny[3];
    CHECK(crsf_decode_flight_mode(fr, tiny, sizeof(tiny)) && strcmp(tiny, "AC") == 0);

    // decoders refuse frames of the wrong type / short payloads
    CHECK(!crsf_decode_gps(fr, &g));
    float vs = 0;
    CHECK(!crsf_decode_vario(fr, &vs));

    // vario: -1.5 m/s
    uint8_t v[2] = {0xFF, 0x6A}; // -150 cm/s
    n = build_crsf(CRSF_TYPE_VARIO, v, sizeof(v), f);
    CHECK(crsf_parse_frame(f, n, &fr) && crsf_decode_vario(fr, &vs));
    CHECK_NEAR(vs, -1.5, 1e-4);

    // baro, decimetre form: 123.4 m -> 1234 + 10000 = 11234 (0x2BE2), packed vspeed +127 cm/s ~ 35
    CrsfBaro baro;
    uint8_t ba[3] = {0x2B, 0xE2, 35};
    n = build_crsf(CRSF_TYPE_BARO_ALT, ba, sizeof(ba), f);
    CHECK(crsf_parse_frame(f, n, &fr) && crsf_decode_baro(fr, &baro));
    CHECK_NEAR(baro.alt_m, 123.4, 1e-3);
    CHECK(baro.has_vspeed);
    CHECK_NEAR(baro.vspeed_ms, (exp(35 * 0.026) - 1.0), 1e-3); // ~1.48 m/s
    ba[2] = (uint8_t)-35;
    n = build_crsf(CRSF_TYPE_BARO_ALT, ba, sizeof(ba), f);
    CHECK(crsf_parse_frame(f, n, &fr) && crsf_decode_baro(fr, &baro));
    CHECK_NEAR(baro.vspeed_ms, -(exp(35 * 0.026) - 1.0), 1e-3);
    // below the power-on point, altitude only
    uint8_t bb[2] = {0x26, 0xFC}; // 9980 -> -2.0 m
    n = build_crsf(CRSF_TYPE_BARO_ALT, bb, sizeof(bb), f);
    CHECK(crsf_parse_frame(f, n, &fr) && crsf_decode_baro(fr, &baro));
    CHECK_NEAR(baro.alt_m, -2.0, 1e-3);
    CHECK(!baro.has_vspeed);
    // metre form (bit 15) with an int16 cm/s vertical speed
    uint8_t bc[4] = {0x8F, 0xA0, 0x01, 0x2C}; // 4000 m, +300 cm/s
    n = build_crsf(CRSF_TYPE_BARO_ALT, bc, sizeof(bc), f);
    CHECK(crsf_parse_frame(f, n, &fr) && crsf_decode_baro(fr, &baro));
    CHECK_NEAR(baro.alt_m, 4000.0, 1e-3);
    CHECK(baro.has_vspeed);
    CHECK_NEAR(baro.vspeed_ms, 3.0, 1e-4);
    CHECK(!crsf_decode_attitude(fr, &at));
}

static void test_geo()
{
    CHECK_NEAR(geo_bearing_deg(0, 0, 0, 1), 90.0, 1e-6);
    CHECK_NEAR(geo_bearing_deg(0, 0, 1, 0), 0.0, 1e-6);
    CHECK_NEAR(geo_bearing_deg(0, 0, 0, -1), 270.0, 1e-6);
    CHECK_NEAR(geo_bearing_deg(0, 0, -1, 0), 180.0, 1e-6);
    CHECK_NEAR(geo_distance_m(0, 0, 1, 0), 111194.93, 1.0);
    CHECK_NEAR(geo_distance_m(48.0, -1.6, 48.0, -1.6), 0.0, 1e-6);
    CHECK_NEAR(geo_elevation_deg(1000, 1000), 45.0, 1e-9);
    CHECK_NEAR(geo_elevation_deg(1000, -50), 0.0, 1e-9); // below the horizon -> clamped
    CHECK_NEAR(geo_elevation_deg(0, 100), 90.0, 1e-9);
    CHECK_NEAR(geo_wrap360(-90), 270.0, 1e-9);
    CHECK_NEAR(geo_wrap360(725), 5.0, 1e-9);
}

static void test_mapper()
{
    AimMapper m;
    PanTilt r = m.map(90, 30, 0, 3);
    CHECK(!r.flipped && fabsf(r.pan - 90) < 1e-4 && fabsf(r.tilt - 30) < 1e-4);

    r = m.map(270, 30, 0, 3); // behind the pan range -> over the top
    CHECK(r.flipped && fabsf(r.pan - 90) < 1e-4 && fabsf(r.tilt - 150) < 1e-4);

    // hysteresis: rel = 178 deg is inside the band, stays flipped; 170 releases the flip
    r = m.map(178, 10, 0, 3);
    CHECK(r.flipped && r.pan == 0);
    r = m.map(170, 10, 0, 3);
    CHECK(!r.flipped && fabsf(r.pan - 170) < 1e-4);

    // offset shifts the zero direction: with offset 90, azimuth 90 -> pan 0
    AimMapper m2;
    r = m2.map(90, 0, 90, 3);
    CHECK(!r.flipped && r.pan == 0);
    r = m2.map(80, 0, 90, 3); // rel = 350 -> flipped, pan 170
    CHECK(r.flipped && fabsf(r.pan - 170) < 1e-4 && fabsf(r.tilt - 180) < 1e-4);

    CHECK(angle_to_us(0, 500, 2500, false) == 500);
    CHECK(angle_to_us(90, 500, 2500, false) == 1500);
    CHECK(angle_to_us(180, 500, 2500, false) == 2500);
    CHECK(angle_to_us(0, 500, 2500, true) == 2500);
    CHECK(angle_to_us(300, 500, 2500, false) == 2500);
    CHECK_NEAR(slew_toward(0, 100, 10), 10, 1e-6);
    CHECK_NEAR(slew_toward(95, 100, 10), 100, 1e-6);
    CHECK_NEAR(slew_toward(0, -100, 10), -10, 1e-6);
}

static void test_tracker()
{
    Tracker t;
    t.begin();
    t.cfg.min_sats = 6;

    CrsfGps g = {};
    g.lat_e7 = 480000000; g.lon_e7 = -16000000; g.alt_m = 50; g.sats = 10;

    // no home yet -> nothing computed, not tracking
    t.onGps(g, 1000);
    CHECK(!t.geoValid() && !t.tracking(1000));

    // use the drone position as home (drone is sitting next to the tracker)
    CHECK(t.setHomeFromDrone(1000));
    CHECK(t.cfg.home_valid && fabs(t.cfg.home_lat - 48.0) < 1e-9);

    // drone 0.01 deg east (~744 m at 48N), 100 m higher
    g.lon_e7 = -16000000 + 100000; g.alt_m = 150;
    t.onGps(g, 2000);
    CHECK(t.geoValid() && t.tracking(2000));
    CHECK_NEAR(t.azimuth(), 90.0, 0.01);
    CHECK_NEAR(t.groundDistance(), 744.0, 3.0);
    CHECK_NEAR(t.elevation(), atan2(100.0, t.groundDistance()) * 180.0 / M_PI, 0.01);
    CHECK_NEAR(t.targetPan(), 90.0, 0.01);

    // the slew limiter walks the servo to the target, never jumping
    t.update(2000);
    float last = t.pan();
    for (uint32_t ms = 2020; ms <= 4000; ms += 20) {
        t.update(ms);
        CHECK(fabsf(t.pan() - last) <= t.cfg.slew_dps * 0.02f + 1e-3f);
        last = t.pan();
    }
    CHECK_NEAR(t.pan(), t.targetPan(), 0.01);
    CHECK_NEAR(t.tilt(), t.targetTilt(), 0.01);

    // poor GPS quality: the target is held, tracking is reported as lost
    float holdPan = t.targetPan();
    g.sats = 3; g.lon_e7 = -16000000 - 100000;
    t.onGps(g, 3000);
    CHECK(t.targetPan() == holdPan);
    CHECK(!t.tracking(3000));

    // good fix again, then timeout
    g.sats = 9;
    t.onGps(g, 3500);
    CHECK_NEAR(t.azimuth(), 270.0, 0.01);
    CHECK(t.flipped());
    CHECK(t.tracking(3500));
    CHECK(!t.tracking(3500 + t.cfg.lost_ms + 1));

    // manual mode
    t.setManual(45, 200);
    CHECK(t.mode() == Tracker::MANUAL && t.targetPan() == 45 && t.targetTilt() == 180);
    t.onGps(g, 4000); // manual: GPS no longer moves the target
    CHECK(t.targetPan() == 45);
    t.setAuto();
    CHECK(t.mode() == Tracker::AUTO && t.flipped());
}

static void test_commands()
{
    Cmd c;
    CHECK(cmd_parse("", &c) && c.type == CMD_NONE);
    CHECK(cmd_parse("   \r", &c) && c.type == CMD_NONE);
    CHECK(cmd_parse("ping", &c) && c.type == CMD_PING);
    CHECK(cmd_parse("STATUS\r", &c) && c.type == CMD_STATUS);

    CHECK(cmd_parse("HOME 48.1234567 -1.6 52.5", &c) && c.type == CMD_HOME_SET);
    CHECK_NEAR(c.v[0], 48.1234567, 1e-9);
    CHECK_NEAR(c.v[1], -1.6, 1e-9);
    CHECK_NEAR(c.v[2], 52.5, 1e-9);
    CHECK(cmd_parse("home drone", &c) && c.type == CMD_HOME_DRONE);
    CHECK(cmd_parse("HOME CLEAR", &c) && c.type == CMD_HOME_CLEAR);
    CHECK(!cmd_parse("HOME 91 0 0", &c) && c.type == CMD_ERROR);
    CHECK(!cmd_parse("HOME 1 2", &c));
    CHECK(!cmd_parse("HOME a b c", &c));

    CHECK(cmd_parse("MODE manual", &c) && c.type == CMD_MODE_MANUAL);
    CHECK(cmd_parse("MODE AUTO", &c) && c.type == CMD_MODE_AUTO);
    CHECK(!cmd_parse("MODE x", &c));

    CHECK(cmd_parse("AIM 90 45.5", &c) && c.type == CMD_AIM && c.v[0] == 90 && c.v[1] == 45.5);
    CHECK(!cmd_parse("AIM 200 0", &c));

    CHECK(cmd_parse("SET Offset 123.5", &c) && c.type == CMD_SET && strcmp(c.text, "offset") == 0 && c.v[0] == 123.5);
    CHECK(!cmd_parse("SET offset", &c));

    CHECK(cmd_parse("BIND my phrase", &c) && c.type == CMD_BIND && strcmp(c.text, "my phrase") == 0);
    char h[13];
    hex(c.uid, 6, h);
    CHECK(strcmp(h, "3b933b37b1e4") == 0);
    CHECK(!cmd_parse("BIND", &c));
    CHECK(cmd_parse("UID 3b933b37b1e4", &c) && c.type == CMD_UID);
    CHECK(cmd_parse("UID 59, 147, 59, 55, 177, 228", &c) && c.type == CMD_UID && c.uid[0] == 59 && c.uid[5] == 228);
    CHECK(!cmd_parse("UID nonsense", &c));

    CHECK(!cmd_parse("FLY", &c) && c.type == CMD_ERROR);
    char longline[200];
    memset(longline, 'A', sizeof(longline));
    longline[199] = 0;
    CHECK(!cmd_parse(longline, &c));

    // config setter
    TrackerConfig cfg;
    cfg_default(&cfg);
    char err[48];
    CHECK(cfg_set(&cfg, "offset", 90, err) && cfg.offset_deg == 90);
    CHECK(cfg_set(&cfg, "pan_min_us", 600, err) && cfg.pan_min_us == 600);
    CHECK(cfg_set(&cfg, "tilt_invert", 1, err) && cfg.tilt_invert == 1);
    CHECK(!cfg_set(&cfg, "offset", 400, err));
    CHECK(!cfg_set(&cfg, "bogus", 1, err));
}

static void test_json()
{
    char b[512];
    CHECK(json_escape("a\"b\\c\n", b, sizeof(b)) == 8 && strcmp(b, "a\\\"b\\\\c?") == 0);

    CrsfGps g = {481234567, -16543210, 45.3f, 182.3f, 120, 12};
    int n = json_gps(b, sizeof(b), 1234, g);
    CHECK(n > 0 && strstr(b, "\"lat\":48.1234567") && strstr(b, "\"lon\":-1.6543210") && strstr(b, "\"sats\":12"));

    Counters c;
    c.espnow = 5;
    n = json_stats(b, sizeof(b), 10, c);
    CHECK(n > 0 && strstr(b, "\"espnow\":5"));

    TrackerConfig cfg;
    cfg_default(&cfg);
    n = json_config(b, sizeof(b), cfg);
    CHECK(n > 0 && strstr(b, "\"uid\":null") && strstr(b, "\"home\":false"));
    cfg.has_uid = 1;
    uid_from_phrase("my phrase", cfg.uid);
    n = json_hello(b, sizeof(b), "0.1.0", "ESP32-C3", cfg, true);
    CHECK(n > 0 && strstr(b, "\"uid\":\"3b933b37b1e4\"") && strstr(b, "\"espnow\":true"));
}

int main()
{
    test_crc8();
    test_md5();
    test_uid();
    test_msp();
    test_crsf();
    test_geo();
    test_mapper();
    test_tracker();
    test_commands();
    test_json();
    printf("%d checks, %d failed\n", g_checks, g_fail);
    return g_fail ? 1 : 0;
}
