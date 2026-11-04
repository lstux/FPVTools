// Prints one sample of every JSON event the firmware can emit (built from the real formatting
// code). The output is committed as backend/tests/fixtures/firmware_events.jsonl so the Python
// backend is tested against what the firmware actually produces.
//   make -C firmware/tests golden
#include <stdio.h>
#include <string.h>

#include "crc8.h"
#include "md5.h"
#include "proto.h"
#include "tracker.h"

static void emit(const char *buf) { printf("%s\n", buf); }

int main()
{
    char b[640];
    Tracker t;
    t.begin();
    uid_from_phrase("my phrase", t.cfg.uid);
    t.cfg.has_uid = 1;

    json_hello(b, sizeof(b), "0.1.0", "ESP32-C3", t.cfg, true);
    emit(b);

    CrsfGps g = {481234567, -16543210, 45.3f, 182.3f, 120, 12};
    t.setHome(48.1230000, -1.6540000, 100.0f);
    t.onGps(g, 1000);
    for (uint32_t ms = 1000; ms < 2500; ms += 20) t.update(ms);

    json_gps(b, sizeof(b), 1000, g);
    emit(b);
    CrsfBattery bat = {16.4f, 12.5f, 432, 70};
    json_battery(b, sizeof(b), 1010, bat);
    emit(b);
    CrsfLinkStats l = {-60, -62, 99, -3, 1, 6, 3, -70, 98, 8};
    json_link(b, sizeof(b), 1020, l);
    emit(b);
    CrsfAttitude a = {30.0f, -10.0f, 180.0f};
    json_attitude(b, sizeof(b), 1030, a);
    emit(b);
    json_flight_mode(b, sizeof(b), 1040, "ACRO*");
    emit(b);
    json_tracker(b, sizeof(b), 2500, t);
    emit(b);

    Tracker nohome;
    nohome.begin();
    json_tracker(b, sizeof(b), 500, nohome);
    emit(b);

    Counters c;
    c.espnow = 120; c.msp_ok = 118; c.msp_bad = 2; c.crsf_ok = 118; c.crsf_bad = 0; c.crsf_other = 40; c.dropped = 0;
    json_stats(b, sizeof(b), 3000, c);
    emit(b);
    json_config(b, sizeof(b), t.cfg);
    emit(b);
    json_ack(b, sizeof(b), "SAVE");
    emit(b);
    json_error(b, sizeof(b), "unknown key 'x\"y'");
    emit(b);
    json_help(b, sizeof(b));
    emit(b);
    return 0;
}
