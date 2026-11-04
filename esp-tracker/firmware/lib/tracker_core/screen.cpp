#include "screen.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>


namespace {

const uint32_t RX_STALE_MS = 2000;

struct Out {
    ScreenLine *l;
    int n;
    void add(uint8_t color, uint8_t size, const char *fmt, ...)
    {
        if (n >= SCREEN_LINES) return;
        ScreenLine &x = l[n++];
        va_list ap;
        va_start(ap, fmt);
        vsnprintf(x.text, sizeof(x.text), fmt, ap);
        va_end(ap);
        size_t maxc = size == 2 ? SCREEN_COLS / 2 : SCREEN_COLS;
        if (strlen(x.text) > maxc) x.text[maxc] = '\0';
        x.color = color;
        x.size = size;
    }
};

void fmt_dist(char *out, size_t cap, double m)
{
    if (m >= 10000) snprintf(out, cap, "%.1fkm", m / 1000.0);
    else if (m >= 1000) snprintf(out, cap, "%.2fkm", m / 1000.0);
    else snprintf(out, cap, "%.0fm", m);
}

bool rx_ok(const ScreenData &d) { return d.rx_age_ms != 0xFFFFFFFFu && d.rx_age_ms < RX_STALE_MS; }

void header(Out &o, const ScreenData &d, const char *title, uint8_t page)
{
    if (!d.has_uid) o.add(SC_RED, 1, "%-12s NO UID  %u/%u", title, page + 1, PAGE_COUNT);
    else if (!d.espnow) o.add(SC_RED, 1, "%-12s ESPNOW! %u/%u", title, page + 1, PAGE_COUNT);
    else if (rx_ok(d)) o.add(SC_GREEN, 1, "%-12s RX OK   %u/%u", title, page + 1, PAGE_COUNT);
    else o.add(SC_AMBER, 1, "%-12s NO RX   %u/%u", title, page + 1, PAGE_COUNT);
}

void tracker_gps_lines(Out &o, const ScreenData &d)
{
    if (!d.tgps_present) {
        o.add(SC_GREY, 1, "Tracker GPS: none");
        return;
    }
    const NmeaFix &f = d.tfix;
    o.add(f.valid ? SC_GREEN : SC_AMBER, 1, "Tracker GPS %u sats %s", (unsigned)f.sats, f.valid ? "fix" : "no fix");
}

void home_line(Out &o, const ScreenData &d)
{
    const TrackerConfig &c = d.trk->cfg;
    if (c.home_valid) {
        o.add(SC_MAGENTA, 1, "Home set (%s) %.0fm", home_src_name(c.home_src), (double)c.home_alt);
    } else if (d.tgps_present && c.auto_home && d.ahome_state == AutoHome::AVERAGING) {
        o.add(SC_AMBER, 1, "Home: averaging GPS %u%%", (unsigned)d.ahome_pct);
    } else {
        o.add(SC_AMBER, 1, "Home: not set");
    }
}

} // namespace

int screen_page(uint8_t page, const ScreenData &d, ScreenLine *out)
{
    Out o = {out, 0};
    const Tracker &t = *d.trk;
    const TrackerConfig &c = t.cfg;
    char a[16], b[16];

    switch (page % PAGE_COUNT) {
    case PAGE_LINK:
    default: {
        header(o, d, "LINK", PAGE_LINK);
        if (d.has_link && rx_ok(d)) {
            const uint8_t col = d.link.up_lq >= 60 ? SC_GREEN : d.link.up_lq >= 25 ? SC_AMBER : SC_RED;
            o.add(col, 2, "LQ%3u %4d", (unsigned)d.link.up_lq, (int)d.link.up_rssi1_dbm);
        } else {
            o.add(SC_RED, 2, "NO TELEM");
        }
        if (!d.has_uid) {
            o.add(SC_RED, 1, "Send BIND <phrase> on USB");
        } else {
            char uid[13];
            uid_hex(d.uid, uid);
            o.add(d.espnow ? SC_WHITE : SC_RED, 1, "UID %s %s", uid, d.espnow ? "on" : "FAIL");
        }
        if (d.rx_age_ms == 0xFFFFFFFFu) o.add(SC_GREY, 1, "RX %lu/s  nothing yet", (unsigned long)d.rx_per_s);
        else o.add(rx_ok(d) ? SC_WHITE : SC_AMBER, 1, "RX %lu/s  last %.1fs", (unsigned long)d.rx_per_s, d.rx_age_ms / 1000.0);
        if (t.hasGps()) {
            const uint8_t s = t.gps().sats;
            o.add(s >= c.min_sats ? SC_GREEN : SC_AMBER, 1, "Drone GPS %u sats", (unsigned)s);
        } else {
            o.add(SC_GREY, 1, "Drone GPS: no data");
        }
        if (d.has_bat) o.add(SC_WHITE, 1, "Bat %.1fV %u%%  %.13s", (double)d.bat.volts, (unsigned)d.bat.percent, d.mode);
        else if (d.mode[0]) o.add(SC_WHITE, 1, "Mode %.20s", d.mode);
        if (d.has_link) o.add(SC_GREY, 1, "TX %umW  SNR %d", (unsigned)crsf_tx_power_mw(d.link.tx_power_idx), (int)d.link.up_snr);
        tracker_gps_lines(o, d);
        home_line(o, d);
        o.add(SC_GREY, 1, "1 page  hold:2 home 3 save");
        break;
    }

    case PAGE_TRACK: {
        header(o, d, "TRACK", PAGE_TRACK);
        if (t.geoValid()) {
            fmt_dist(a, sizeof(a), t.groundDistance());
            o.add(SC_CYAN, 2, "%s %+.0fm", a, t.heightAboveHome());
            o.add(SC_CYAN, 1, "Az %.1f  El %.1f", t.azimuth(), t.elevation());
        } else {
            o.add(SC_GREY, 2, "--");
            o.add(SC_GREY, 1, c.home_valid ? "Az/El: waiting for GPS" : "Az/El: set home first");
        }
        o.add(SC_WHITE, 1, "Pan %.0f  Tilt %.0f%s", (double)t.pan(), (double)t.tilt(), t.flipped() ? "  FLIP" : "");
        if (t.mode() == Tracker::MANUAL) o.add(SC_AMBER, 1, "Mode MANUAL");
        else if (t.tracking(d.now_ms)) o.add(SC_GREEN, 1, "Mode AUTO, tracking");
        else o.add(SC_AMBER, 1, "Mode AUTO, %s", c.home_valid ? "waiting GPS" : "no home");
        o.add(SC_WHITE, 1, "Offset %.1f%s", (double)c.offset_deg, d.sens.north_applied ? " (compass)" : "");
        o.add(SC_WHITE, 1, "Height from %s", t.usedBaro() ? "drone baro" : "GPS");
        home_line(o, d);
        if (c.home_valid) o.add(SC_GREY, 1, "%.6f %.6f", c.home_lat, c.home_lon);
        o.add(SC_GREY, 1, "1 page  hold:2 home 3 save");
        break;
    }

    case PAGE_SENSORS: {
        header(o, d, "SENSORS", PAGE_SENSORS);
        const SensorReport &s = d.sens;
        if (s.cal == 2) o.add(SC_AMBER, 2, "CAL %u%%", (unsigned)s.cal_cov);
        else if (s.has_heading) o.add(s.cal == 1 ? SC_GREEN : SC_AMBER, 2, "HDG %03.0f", (double)s.heading_true);
        else o.add(SC_GREY, 2, "HDG --");
        if (s.imu && s.imu[0]) {
            if (s.has_tilt) o.add(s.tilt_deg <= 5 ? SC_WHITE : SC_AMBER, 1, "%-9s tilt %.1f", s.imu, (double)s.tilt_deg);
            else o.add(SC_WHITE, 1, "%s", s.imu);
        } else {
            o.add(SC_GREY, 1, "Accel: none");
        }
        if (s.mag && s.mag[0])
            o.add(s.cal == 1 ? SC_WHITE : SC_AMBER, 1, "%-9s %s", s.mag,
                  s.cal == 1 ? "calibrated" : s.cal == 2 ? "turn slowly" : "NOT CALIBRATED");
        else o.add(SC_GREY, 1, "Compass: none");
        if (s.baro && s.baro[0] && s.has_press)
            o.add(SC_WHITE, 1, "%-6s %.1fhPa %.1fC", s.baro, (double)(s.press_pa / 100.0f), (double)s.temp_c);
        else if (s.baro && s.baro[0]) o.add(SC_AMBER, 1, "%s: no reading", s.baro);
        else o.add(SC_GREY, 1, "Baro: none");
        if (d.tgps_present) {
            const NmeaFix &f = d.tfix;
            snprintf(b, sizeof(b), "%.1f", (double)f.hdop);
            o.add(f.valid ? SC_GREEN : SC_AMBER, 1, "GPS %lubd %usat hdop %s", (unsigned long)d.tgps_baud, (unsigned)f.sats, b);
            if (f.valid) {
                o.add(SC_WHITE, 1, "%.6f %.6f", f.lat, f.lon);
                o.add(SC_WHITE, 1, "GPS alt %.1fm", (double)f.alt_m);
            }
        } else {
            o.add(SC_GREY, 1, "GPS: no NMEA received");
        }
        o.add(SC_GREY, 1, "1 page  hold:2 cal compass");
        break;
    }
    }
    return o.n;
}
