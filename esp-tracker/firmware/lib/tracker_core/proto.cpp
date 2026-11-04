#include "proto.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "md5.h"

namespace {

int finish(int n, size_t cap)
{
    if (n < 0) return 0;
    if ((size_t)n >= cap) return (int)cap - 1; // truncated
    return n;
}

void uid_hex(const uint8_t uid[6], char out[13])
{
    snprintf(out, 13, "%02x%02x%02x%02x%02x%02x", uid[0], uid[1], uid[2], uid[3], uid[4], uid[5]);
}

} // namespace

size_t json_escape(const char *in, char *out, size_t cap)
{
    size_t n = 0;
    if (cap == 0) return 0;
    for (; *in && n + 2 < cap; ++in) {
        unsigned char ch = (unsigned char)*in;
        if (ch == '"' || ch == '\\') {
            out[n++] = '\\';
            out[n++] = (char)ch;
        } else if (ch < 0x20 || ch >= 0x7f) {
            out[n++] = '?';
        } else {
            out[n++] = (char)ch;
        }
    }
    out[n] = '\0';
    return n;
}

int json_hello(char *buf, size_t cap, const char *fw, const char *chip, const TrackerConfig &cfg, bool espnow_on)
{
    char uid[13] = "";
    if (cfg.has_uid) uid_hex(cfg.uid, uid);
    char chipEsc[32];
    json_escape(chip, chipEsc, sizeof(chipEsc));
    return finish(snprintf(buf, cap, "{\"e\":\"hello\",\"fw\":\"%s\",\"chip\":\"%s\",\"uid\":%s%s%s,\"espnow\":%s}", fw,
                           chipEsc, cfg.has_uid ? "\"" : "null", uid, cfg.has_uid ? "\"" : "",
                           espnow_on ? "true" : "false"),
                  cap);
}

int json_gps(char *buf, size_t cap, uint32_t ms, const CrsfGps &g)
{
    return finish(snprintf(buf, cap,
                           "{\"e\":\"gps\",\"ms\":%lu,\"lat\":%.7f,\"lon\":%.7f,\"alt\":%ld,\"gs\":%.1f,\"hdg\":%.1f,\"sats\":%u}",
                           (unsigned long)ms, g.lat_e7 / 1e7, g.lon_e7 / 1e7, (long)g.alt_m, (double)g.groundspeed_kmh,
                           (double)g.heading_deg, (unsigned)g.sats),
                  cap);
}

int json_battery(char *buf, size_t cap, uint32_t ms, const CrsfBattery &b)
{
    return finish(snprintf(buf, cap, "{\"e\":\"bat\",\"ms\":%lu,\"v\":%.1f,\"a\":%.1f,\"mah\":%lu,\"pct\":%u}",
                           (unsigned long)ms, (double)b.volts, (double)b.amps, (unsigned long)b.mah, (unsigned)b.percent),
                  cap);
}

int json_link(char *buf, size_t cap, uint32_t ms, const CrsfLinkStats &l)
{
    return finish(snprintf(buf, cap,
                           "{\"e\":\"link\",\"ms\":%lu,\"rssi1\":%d,\"rssi2\":%d,\"lq\":%u,\"snr\":%d,\"ant\":%u,"
                           "\"rfmode\":%u,\"txpwr\":%u,\"drssi\":%d,\"dlq\":%u,\"dsnr\":%d}",
                           (unsigned long)ms, (int)l.up_rssi1_dbm, (int)l.up_rssi2_dbm, (unsigned)l.up_lq, (int)l.up_snr,
                           (unsigned)l.antenna, (unsigned)l.rf_mode, (unsigned)crsf_tx_power_mw(l.tx_power_idx),
                           (int)l.dn_rssi_dbm, (unsigned)l.dn_lq, (int)l.dn_snr),
                  cap);
}

int json_attitude(char *buf, size_t cap, uint32_t ms, const CrsfAttitude &a)
{
    return finish(snprintf(buf, cap, "{\"e\":\"att\",\"ms\":%lu,\"pitch\":%.1f,\"roll\":%.1f,\"yaw\":%.1f}",
                           (unsigned long)ms, (double)a.pitch_deg, (double)a.roll_deg, (double)a.yaw_deg),
                  cap);
}

int json_vario(char *buf, size_t cap, uint32_t ms, float vspeed_ms)
{
    return finish(snprintf(buf, cap, "{\"e\":\"vario\",\"ms\":%lu,\"vs\":%.2f}", (unsigned long)ms, (double)vspeed_ms),
                  cap);
}

int json_baro(char *buf, size_t cap, uint32_t ms, const CrsfBaro &b)
{
    if (b.has_vspeed)
        return finish(snprintf(buf, cap, "{\"e\":\"baro\",\"ms\":%lu,\"alt\":%.1f,\"vs\":%.2f}", (unsigned long)ms,
                               (double)b.alt_m, (double)b.vspeed_ms),
                      cap);
    return finish(snprintf(buf, cap, "{\"e\":\"baro\",\"ms\":%lu,\"alt\":%.1f}", (unsigned long)ms, (double)b.alt_m),
                  cap);
}

int json_flight_mode(char *buf, size_t cap, uint32_t ms, const char *mode)
{
    char esc[40];
    json_escape(mode, esc, sizeof(esc));
    return finish(snprintf(buf, cap, "{\"e\":\"mode\",\"ms\":%lu,\"m\":\"%s\"}", (unsigned long)ms, esc), cap);
}

int json_tracker(char *buf, size_t cap, uint32_t ms, const Tracker &t)
{
    const TrackerConfig &c = t.cfg;
    const bool geo = t.geoValid();
    int n = snprintf(buf, cap,
                     "{\"e\":\"trk\",\"ms\":%lu,\"mode\":\"%s\",\"home\":%s,\"hlat\":%.7f,\"hlon\":%.7f,\"halt\":%.1f,"
                     "\"tracking\":%s,\"pan\":%.1f,\"tilt\":%.1f,\"tpan\":%.1f,\"ttilt\":%.1f,\"flip\":%s,\"gps_age\":%ld",
                     (unsigned long)ms, t.mode() == Tracker::AUTO ? "auto" : "manual", c.home_valid ? "true" : "false",
                     c.home_lat, c.home_lon, (double)c.home_alt, t.tracking(ms) ? "true" : "false", (double)t.pan(),
                     (double)t.tilt(), (double)t.targetPan(), (double)t.targetTilt(), t.flipped() ? "true" : "false",
                     t.hasGps() ? (long)t.gpsAgeMs(ms) : -1L);
    if (n < 0 || (size_t)n >= cap) return finish(n, cap);
    if (geo) {
        int m = snprintf(buf + n, cap - n, ",\"az\":%.1f,\"el\":%.1f,\"dist\":%.1f,\"dist3d\":%.1f}", t.azimuth(),
                         t.elevation(), t.groundDistance(), t.distance3d());
        return finish(n + m, cap);
    }
    int m = snprintf(buf + n, cap - n, ",\"az\":null,\"el\":null,\"dist\":null,\"dist3d\":null}");
    return finish(n + m, cap);
}

int json_stats(char *buf, size_t cap, uint32_t ms, const Counters &c)
{
    return finish(snprintf(buf, cap,
                           "{\"e\":\"stat\",\"ms\":%lu,\"espnow\":%lu,\"msp_ok\":%lu,\"msp_bad\":%lu,\"crsf_ok\":%lu,"
                           "\"crsf_bad\":%lu,\"crsf_other\":%lu,\"dropped\":%lu}",
                           (unsigned long)ms, (unsigned long)c.espnow, (unsigned long)c.msp_ok, (unsigned long)c.msp_bad,
                           (unsigned long)c.crsf_ok, (unsigned long)c.crsf_bad, (unsigned long)c.crsf_other,
                           (unsigned long)c.dropped),
                  cap);
}

int json_config(char *buf, size_t cap, const TrackerConfig &c)
{
    char uid[13] = "";
    if (c.has_uid) uid_hex(c.uid, uid);
    return finish(snprintf(buf, cap,
                           "{\"e\":\"cfg\",\"uid\":%s%s%s,\"home\":%s,\"hlat\":%.7f,\"hlon\":%.7f,\"halt\":%.1f,"
                           "\"offset\":%.1f,\"hyst\":%.1f,\"slew\":%.0f,\"pan_min_us\":%u,\"pan_max_us\":%u,"
                           "\"tilt_min_us\":%u,\"tilt_max_us\":%u,\"pan_invert\":%u,\"tilt_invert\":%u,"
                           "\"min_sats\":%u,\"lost_ms\":%u}",
                           c.has_uid ? "\"" : "null", uid, c.has_uid ? "\"" : "", c.home_valid ? "true" : "false",
                           c.home_lat, c.home_lon, (double)c.home_alt, (double)c.offset_deg, (double)c.hyst_deg,
                           (double)c.slew_dps, (unsigned)c.pan_min_us, (unsigned)c.pan_max_us, (unsigned)c.tilt_min_us,
                           (unsigned)c.tilt_max_us, (unsigned)c.pan_invert, (unsigned)c.tilt_invert, (unsigned)c.min_sats,
                           (unsigned)c.lost_ms),
                  cap);
}

int json_ack(char *buf, size_t cap, const char *cmd)
{
    return finish(snprintf(buf, cap, "{\"e\":\"ack\",\"cmd\":\"%s\"}", cmd), cap);
}

int json_error(char *buf, size_t cap, const char *msg)
{
    char esc[96];
    json_escape(msg, esc, sizeof(esc));
    return finish(snprintf(buf, cap, "{\"e\":\"err\",\"msg\":\"%s\"}", esc), cap);
}

int json_help(char *buf, size_t cap)
{
    return finish(snprintf(buf, cap,
                           "{\"e\":\"help\",\"text\":\"PING | STATUS | BIND <phrase> | UID <hex12|d,d,d,d,d,d> | "
                           "HOME <lat> <lon> <alt> | HOME DRONE | HOME CLEAR | MODE AUTO|MANUAL | AIM <pan> <tilt> | "
                           "SET <key> <value> | SAVE | FACTORY | REBOOT. Keys: %s\"}",
                           cfg_keys()),
                  cap);
}

// ---------------------------------------------------------------------------------------------------

namespace {

bool parse_double(const char *s, double *out)
{
    if (!s || !*s) return false;
    char *end = nullptr;
    double v = strtod(s, &end);
    if (end == s || *end != '\0') return false;
    *out = v;
    return true;
}

// Split `buf` in place on whitespace. Returns the token count (max `maxTok`).
int tokenize(char *buf, char **tok, int maxTok)
{
    int n = 0;
    char *p = buf;
    while (*p && n < maxTok) {
        while (*p == ' ' || *p == '\t') ++p;
        if (!*p) break;
        tok[n++] = p;
        while (*p && *p != ' ' && *p != '\t') ++p;
        if (*p) *p++ = '\0';
    }
    return n;
}

bool fail(Cmd *c, const char *msg)
{
    c->type = CMD_ERROR;
    snprintf(c->err, sizeof(c->err), "%s", msg);
    return false;
}

bool ieq(const char *a, const char *b)
{
    for (; *a && *b; ++a, ++b)
        if (toupper((unsigned char)*a) != toupper((unsigned char)*b)) return false;
    return *a == *b;
}

} // namespace

const char *cmd_name(CmdType t)
{
    switch (t) {
    case CMD_HELP: return "HELP";
    case CMD_PING: return "PING";
    case CMD_STATUS: return "STATUS";
    case CMD_BIND: return "BIND";
    case CMD_UID: return "UID";
    case CMD_HOME_SET: return "HOME";
    case CMD_HOME_DRONE: return "HOME DRONE";
    case CMD_HOME_CLEAR: return "HOME CLEAR";
    case CMD_MODE_AUTO: return "MODE AUTO";
    case CMD_MODE_MANUAL: return "MODE MANUAL";
    case CMD_AIM: return "AIM";
    case CMD_SET: return "SET";
    case CMD_SAVE: return "SAVE";
    case CMD_FACTORY: return "FACTORY";
    case CMD_REBOOT: return "REBOOT";
    default: return "?";
    }
}

bool cmd_parse(const char *line, Cmd *c)
{
    memset(c, 0, sizeof(*c));
    c->type = CMD_NONE;

    char buf[112];
    size_t n = strlen(line);
    if (n >= sizeof(buf)) return fail(c, "line too long");
    memcpy(buf, line, n + 1);
    // trim trailing whitespace / CR
    while (n > 0 && (buf[n - 1] == '\r' || buf[n - 1] == '\n' || buf[n - 1] == ' ' || buf[n - 1] == '\t')) buf[--n] = '\0';
    char *start = buf;
    while (*start == ' ' || *start == '\t') ++start;
    if (!*start) return true; // empty line

    // BIND takes the rest of the line verbatim (a bind phrase may contain spaces)
    {
        char *sp = start;
        while (*sp && *sp != ' ' && *sp != '\t') ++sp;
        char saved = *sp;
        *sp = '\0';
        bool isBind = ieq(start, "BIND");
        *sp = saved;
        if (isBind) {
            char *arg = sp;
            while (*arg == ' ' || *arg == '\t') ++arg;
            if (!*arg) return fail(c, "usage: BIND <phrase>");
            if (strlen(arg) >= sizeof(c->text)) return fail(c, "phrase too long");
            strcpy(c->text, arg);
            if (!uid_from_phrase(c->text, c->uid)) return fail(c, "invalid bind phrase");
            c->type = CMD_BIND;
            return true;
        }
    }

    char *tok[10];
    int nt = tokenize(start, tok, 10);
    const char *verb = tok[0];

    if (ieq(verb, "HELP")) { c->type = CMD_HELP; return true; }
    if (ieq(verb, "PING")) { c->type = CMD_PING; return true; }
    if (ieq(verb, "STATUS")) { c->type = CMD_STATUS; return true; }
    if (ieq(verb, "SAVE")) { c->type = CMD_SAVE; return true; }
    if (ieq(verb, "FACTORY")) { c->type = CMD_FACTORY; return true; }
    if (ieq(verb, "REBOOT")) { c->type = CMD_REBOOT; return true; }

    if (ieq(verb, "UID")) {
        // The decimal form contains spaces after commas in some tools' output: rejoin the arguments.
        char joined[64];
        joined[0] = '\0';
        for (int i = 1; i < nt; ++i) {
            if (strlen(joined) + strlen(tok[i]) + 1 >= sizeof(joined)) return fail(c, "UID too long");
            strcat(joined, tok[i]);
        }
        if (!uid_parse(joined, c->uid)) return fail(c, "usage: UID <12 hex digits | d,d,d,d,d,d>");
        c->type = CMD_UID;
        return true;
    }

    if (ieq(verb, "HOME")) {
        if (nt == 2 && ieq(tok[1], "DRONE")) { c->type = CMD_HOME_DRONE; return true; }
        if (nt == 2 && ieq(tok[1], "CLEAR")) { c->type = CMD_HOME_CLEAR; return true; }
        if (nt == 4 && parse_double(tok[1], &c->v[0]) && parse_double(tok[2], &c->v[1]) &&
            parse_double(tok[3], &c->v[2])) {
            if (c->v[0] < -90 || c->v[0] > 90 || c->v[1] < -180 || c->v[1] > 180) return fail(c, "lat/lon out of range");
            if (c->v[2] < -500 || c->v[2] > 9000) return fail(c, "altitude out of range");
            c->type = CMD_HOME_SET;
            return true;
        }
        return fail(c, "usage: HOME <lat> <lon> <alt> | DRONE | CLEAR");
    }

    if (ieq(verb, "MODE")) {
        if (nt == 2 && ieq(tok[1], "AUTO")) { c->type = CMD_MODE_AUTO; return true; }
        if (nt == 2 && ieq(tok[1], "MANUAL")) { c->type = CMD_MODE_MANUAL; return true; }
        return fail(c, "usage: MODE AUTO|MANUAL");
    }

    if (ieq(verb, "AIM")) {
        if (nt == 3 && parse_double(tok[1], &c->v[0]) && parse_double(tok[2], &c->v[1])) {
            if (c->v[0] < 0 || c->v[0] > 180 || c->v[1] < 0 || c->v[1] > 180) return fail(c, "angles must be 0..180");
            c->type = CMD_AIM;
            return true;
        }
        return fail(c, "usage: AIM <pan 0-180> <tilt 0-180>");
    }

    if (ieq(verb, "SET")) {
        if (nt == 3 && parse_double(tok[2], &c->v[0])) {
            if (strlen(tok[1]) >= sizeof(c->text)) return fail(c, "key too long");
            strcpy(c->text, tok[1]);
            for (char *p = c->text; *p; ++p) *p = (char)tolower((unsigned char)*p);
            c->type = CMD_SET;
            return true;
        }
        return fail(c, "usage: SET <key> <value>");
    }

    return fail(c, "unknown command (try HELP)");
}
