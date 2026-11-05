// ESP-NOW antenna tracker for ExpressLRS Backpack telemetry.
//
//   TX module -> TX Backpack --(ESP-NOW, MSP v2 wrapping CRSF frames)--> this board
//   this board --(USB / UART, JSON lines)--> host application      (and pan/tilt servos)
//
// All the protocol, geometry and tracking logic lives in lib/tracker_core (unit tested on a PC).
// This file only wires it to the hardware: Wi-Fi/ESP-NOW, servos, NVS storage, the serial port, and the
// optional tracker sensors (GPS, compass, accelerometer, barometer: sensors.cpp) and screen (display.cpp).

#include <Arduino.h>
#include <ESP32Servo.h>
#include <Preferences.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>

#if __has_include("esp_arduino_version.h")
#include "esp_arduino_version.h"
#endif

#include "board.h"
#include "compass.h"
#include "crsf.h"
#include "md5.h"
#include "msp.h"
#include "proto.h"
#include "nmea.h"
#include "screen.h"
#include "sensors.h"
#include "tracker.h"
#if HAS_TFT
#include "display.h"
#endif

// ---- state ---------------------------------------------------------------------------------------

struct NowPkt {
    uint8_t len;
    uint8_t data[250]; // ESP-NOW maximum payload
};

static Tracker tracker;
static Counters counters;
static Servo panServo, tiltServo;
static Preferences prefs;
static QueueHandle_t rxQueue;
static uint8_t myMac[6];
static bool espnowOn = false;

static char outBuf[640];
static char lineBuf[128];
static size_t lineLen = 0;
static bool lineOverflow = false;

static uint32_t lastServoMs = 0, lastTrkMs = 0, lastStatMs = 0, lastHelloMs = 0, lastSensMs = 0;

// latest drone telemetry, for the screen
static CrsfLinkStats lastLink;
static CrsfBattery lastBat;
static bool haveLink = false, haveBat = false;
static char lastMode[16] = "";
static uint32_t lastRxMs = 0, rxThisSecond = 0, rxPerSecond = 0, rxSecondStart = 0;
static bool everRx = false;

// tracker sensors
static Sensors sensors;
static bool sensorsOn = false;
static MagCalibrator magCal;
static AngleFilter headingFilter;
static uint32_t lastMagSeq = 0, lastNorthMs = 0;
static bool northApplied = false;
static float tiltDeg = 0;
static bool tiltValid = false;

// tracker GPS
#if PIN_GPS_RX >= 0
static HardwareSerial gpsSerial(1);
#endif
static NmeaParser nmea;
static AutoHome autoHome;
static uint32_t gpsBaud = 0, gpsBaudSince = 0, gpsLastGood = 0, gpsGoodSeen = 0;
static uint8_t gpsBaudIdx = 0;
static const uint32_t GPS_BAUDS[] = {9600, 38400, 57600, 115200, 19200, 4800};

#if HAS_TFT
static Display display;
static uint8_t screenPage = 0;
static uint32_t lastScreenMs = 0;
#endif
static char lastResult[40] = "";
static bool lastOk = true;
#if PIN_LED >= 0
static uint32_t ledOffAt = 0;
#endif

// ---- helpers -------------------------------------------------------------------------------------

static void emit(int n)
{
    if (n <= 0) return;
    Serial.write(reinterpret_cast<const uint8_t *>(outBuf), (size_t)n);
    Serial.write('\n');
}

static void blink(uint32_t now)
{
#if PIN_LED >= 0
    digitalWrite(PIN_LED, LED_ON_LEVEL);
    ledOffAt = now + 25;
#else
    (void)now;
#endif
}

static void saveConfig()
{
    prefs.begin("esptrk", false);
    prefs.putBytes("cfg", &tracker.cfg, sizeof(TrackerConfig));
    prefs.end();
}

static void loadConfig()
{
    prefs.begin("esptrk", false);
    if (prefs.getBytesLength("cfg") == sizeof(TrackerConfig)) {
        TrackerConfig tmp;
        prefs.getBytes("cfg", &tmp, sizeof(tmp));
        if (tmp.magic == CFG_MAGIC) tracker.cfg = tmp;
    }
    prefs.end();
}

static void factoryReset()
{
    prefs.begin("esptrk", false);
    prefs.clear();
    prefs.end();
}

static void attachServos()
{
    ESP32PWM::allocateTimer(0);
    ESP32PWM::allocateTimer(1);
    panServo.setPeriodHertz(50);
    tiltServo.setPeriodHertz(50);
    // Wide attach range: the real limits are enforced by the pan_/tilt_ min/max_us settings.
    panServo.attach(PIN_PAN, 400, 2600);
    tiltServo.attach(PIN_TILT, 400, 2600);
    panServo.writeMicroseconds(tracker.panUs());
    tiltServo.writeMicroseconds(tracker.tiltUs());
}

// ---- ESP-NOW -------------------------------------------------------------------------------------

static void onRecvCommon(const uint8_t *src, const uint8_t *data, int len)
{
    // Runs in the Wi-Fi task: do the minimum and hand over to loop().
    if (len <= 0 || len > (int)sizeof(NowPkt::data)) return;
    if (memcmp(src, myMac, 6) != 0) return; // only our bound Backpack (its MAC == UID)
    NowPkt p;
    p.len = (uint8_t)len;
    memcpy(p.data, data, (size_t)len);
    if (xQueueSend(rxQueue, &p, 0) != pdTRUE) ++counters.dropped;
}

#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
static void onRecv(const esp_now_recv_info_t *info, const uint8_t *data, int len)
{
    onRecvCommon(info->src_addr, data, len);
}
#else
static void onRecv(const uint8_t *mac, const uint8_t *data, int len) { onRecvCommon(mac, data, len); }
#endif

static bool startEspNow()
{
    uid_to_mac(tracker.cfg.uid, myMac);

    // Same sequence as the ELRS Backpack firmware (SetSoftMACAddress): the Backpack sets its own
    // MAC to the UID and sends unicast ESP-NOW to that same address on channel 1.
    WiFi.mode(WIFI_STA);
    esp_wifi_set_protocol(WIFI_IF_STA, WIFI_PROTOCOL_11B | WIFI_PROTOCOL_11G | WIFI_PROTOCOL_11N | WIFI_PROTOCOL_LR);
    WiFi.begin("network-name", "pass-to-network", ESPNOW_CHANNEL);
    WiFi.disconnect();
    if (esp_wifi_set_mac(WIFI_IF_STA, myMac) != ESP_OK) return false;
    esp_wifi_set_ps(WIFI_PS_NONE); // never sleep the radio: we only listen
    esp_wifi_set_channel(ESPNOW_CHANNEL, WIFI_SECOND_CHAN_NONE);

    if (esp_now_init() != ESP_OK) return false;
    esp_now_register_recv_cb(onRecv);
    return true;
}

// ---- telemetry processing ------------------------------------------------------------------------

static void handleCrsf(const uint8_t *data, size_t n, uint32_t now)
{
    CrsfFrame f;
    if (!crsf_parse_frame(data, n, &f)) {
        ++counters.crsf_bad;
        return;
    }
    ++counters.crsf_ok;

    switch (f.type) {
    case CRSF_TYPE_GPS: {
        CrsfGps g;
        if (crsf_decode_gps(f, &g)) {
            tracker.onGps(g, now);
            emit(json_gps(outBuf, sizeof(outBuf), now, g));
            blink(now);
        }
        break;
    }
    case CRSF_TYPE_BATTERY: {
        CrsfBattery b;
        if (crsf_decode_battery(f, &b)) {
            lastBat = b;
            haveBat = true;
            emit(json_battery(outBuf, sizeof(outBuf), now, b));
        }
        break;
    }
    case CRSF_TYPE_LINK_STATS: {
        CrsfLinkStats l;
        if (crsf_decode_link_stats(f, &l)) {
            lastLink = l;
            haveLink = true;
            emit(json_link(outBuf, sizeof(outBuf), now, l));
        }
        break;
    }
    case CRSF_TYPE_ATTITUDE: {
        CrsfAttitude a;
        if (crsf_decode_attitude(f, &a)) emit(json_attitude(outBuf, sizeof(outBuf), now, a));
        break;
    }
    case CRSF_TYPE_VARIO: {
        float vs;
        if (crsf_decode_vario(f, &vs)) emit(json_vario(outBuf, sizeof(outBuf), now, vs));
        break;
    }
    case CRSF_TYPE_BARO_ALT: {
        CrsfBaro b;
        if (crsf_decode_baro(f, &b)) {
            tracker.onDroneBaro(b.alt_m, now);
            emit(json_baro(outBuf, sizeof(outBuf), now, b));
        }
        break;
    }
    case CRSF_TYPE_FLIGHT_MODE: {
        char mode[24];
        if (crsf_decode_flight_mode(f, mode, sizeof(mode))) {
            strncpy(lastMode, mode, sizeof(lastMode) - 1);
            lastMode[sizeof(lastMode) - 1] = '\0';
            emit(json_flight_mode(outBuf, sizeof(outBuf), now, mode));
        }
        break;
    }
    default:
        ++counters.crsf_other;
        break;
    }
}

static void handlePacket(const NowPkt &p, uint32_t now)
{
    static MspParser parser;
    MspPacket msp;
    ++counters.espnow;
    lastRxMs = now;
    everRx = true;
    ++rxThisSecond;
    parser.reset(); // every ESP-NOW payload holds whole MSP packets
    for (uint8_t i = 0; i < p.len; ++i) {
        if (parser.feed(p.data[i], &msp)) {
            ++counters.msp_ok;
            if (msp.function == MSP_ELRS_BACKPACK_CRSF_TLM) handleCrsf(msp.payload, msp.size, now);
        }
    }
    counters.msp_bad = parser.crcErrors + parser.oversize;
}

// ---- commands from the host ----------------------------------------------------------------------

static void ack(const Cmd &c)
{
    emit(json_ack(outBuf, sizeof(outBuf), cmd_name(c.type)));
    snprintf(lastResult, sizeof(lastResult), "%s OK", cmd_name(c.type));
    lastOk = true;
}
static void fail(const char *msg)
{
    emit(json_error(outBuf, sizeof(outBuf), msg));
    snprintf(lastResult, sizeof(lastResult), "%s", msg);
    lastOk = false;
}
static void note(const char *what)
{
    emit(json_ack(outBuf, sizeof(outBuf), what));
}

// ---- tracker sensors ------------------------------------------------------------------------------

static bool gpsPresent(uint32_t now) { return gpsGoodSeen > 0 && now - gpsLastGood < 5000; }

static SensorReport sensorReport()
{
    SensorReport r;
    memset(&r, 0, sizeof(r));
    r.imu = sensors.imuName();
    r.mag = sensors.magName();
    r.baro = sensors.baroName();
    r.has_heading = sensors.hasMag() && headingFilter.ready();
    if (r.has_heading) {
        r.heading_true = headingFilter.value();
        float m = r.heading_true - tracker.cfg.declination;
        r.heading_mag = m < 0 ? m + 360 : (m >= 360 ? m - 360 : m);
    }
    r.has_tilt = tiltValid;
    r.tilt_deg = tiltDeg;
    r.cal = magCal.active() ? 2 : (tracker.cfg.magcal.valid ? 1 : 0);
    r.cal_cov = magCal.coverage();
    r.has_press = sensors.pressValid();
    r.press_pa = sensors.pressPa();
    r.temp_c = sensors.tempC();
    r.north_applied = northApplied;
    return r;
}

static void reportSensors(uint32_t now)
{
    if (sensorsOn) emit(json_sensors(outBuf, sizeof(outBuf), now, sensorReport()));
    if (gpsPresent(now))
        emit(json_tracker_gps(outBuf, sizeof(outBuf), now, nmea.fix(), gpsBaud, autoHome, nmea.good, nmea.bad));
}

static void gpsSetBaud(uint32_t baud, uint32_t now)
{
#if PIN_GPS_RX >= 0
    gpsSerial.end();
    gpsSerial.begin(baud, SERIAL_8N1, PIN_GPS_RX, PIN_GPS_TX);
#endif
    gpsBaud = baud;
    gpsBaudSince = now;
}

static bool autoHomeWanted()
{
    // Follow the tracker GPS unless the user chose another home (drone / map / typed) on purpose.
    const TrackerConfig &c = tracker.cfg;
    return c.auto_home && (c.home_src == HOME_SRC_NONE || c.home_src == HOME_SRC_GPS || !c.home_valid);
}

static void pollGps(uint32_t now)
{
#if PIN_GPS_RX >= 0
    const uint32_t before = nmea.good;
    for (int i = 0; i < 256 && gpsSerial.available() > 0; ++i) {
        if (!nmea.feed((char)gpsSerial.read())) continue;
        if (autoHomeWanted() && autoHome.feed(nmea.fix(), now, tracker.cfg.min_sats)) {
            tracker.setHome(autoHome.lat(), autoHome.lon(), autoHome.alt(), HOME_SRC_GPS);
            note("HOME GPS (auto)");
        }
    }
    if (nmea.good != before) {
        gpsLastGood = now;
        gpsGoodSeen = nmea.good;
    }
    // baud auto-detection: try the next speed when nothing valid arrived for 3 s
    if (tracker.cfg.gps_baud == 0 && now - gpsLastGood > 3000 && now - gpsBaudSince > 3000) {
        gpsBaudIdx = (uint8_t)((gpsBaudIdx + 1) % (sizeof(GPS_BAUDS) / sizeof(GPS_BAUDS[0])));
        gpsSetBaud(GPS_BAUDS[gpsBaudIdx], now);
    }
#else
    (void)now;
#endif
}

static void pollCompass(uint32_t now)
{
    if (!sensorsOn) return;
    sensors.poll(now);
    if (sensors.hasAccel() && sensors.accelValid()) {
        // tilt even without a compass: tells whether the tracker stands level
        compass_heading(Vec3{0, 1, 0}, &sensors.accel(), &tiltDeg);
        tiltValid = true;
    }
    if (!sensors.hasMag() || sensors.magSeq() == lastMagSeq) return;
    lastMagSeq = sensors.magSeq();
    const Vec3 raw = sensors.mag();
    if (magCal.active()) magCal.add(raw);
    const Vec3 m = magcal_apply(tracker.cfg.magcal, raw);
    const Vec3 *acc = sensors.hasAccel() && sensors.accelValid() ? &sensors.accel() : nullptr;
    float h = compass_heading(m, acc, nullptr);
    if (h < 0) return;
    h += tracker.cfg.declination;
    if (h < 0) h += 360;
    if (h >= 360) h -= 360;
    headingFilter.update(h, 0.1f);

    // Automatic north: the antenna's pan = 0 direction follows the compass, once calibrated.
    northApplied = tracker.cfg.auto_north && tracker.cfg.magcal.valid && !magCal.active();
    if (northApplied && now - lastNorthMs >= 1000) {
        lastNorthMs = now;
        float off = headingFilter.value() + tracker.cfg.compass_mount;
        while (off < 0) off += 360;
        while (off >= 360) off -= 360;
        float diff = off - tracker.cfg.offset_deg;
        if (diff > 180) diff -= 360;
        if (diff < -180) diff += 360;
        if (diff > 0.5f || diff < -0.5f) { // ignore noise: do not make the servos hunt
            tracker.cfg.offset_deg = off;
            tracker.recompute();
        }
    }
}

static void sendStatus(uint32_t now)
{
    emit(json_hello(outBuf, sizeof(outBuf), FW_VERSION, ESP.getChipModel(), tracker.cfg, espnowOn));
    emit(json_config(outBuf, sizeof(outBuf), tracker.cfg));
    emit(json_tracker(outBuf, sizeof(outBuf), now, tracker));
    emit(json_stats(outBuf, sizeof(outBuf), now, counters));
    reportSensors(now);
}

static void handleCommand(const char *line, uint32_t now)
{
    Cmd c;
    if (!cmd_parse(line, &c)) {
        fail(c.err);
        return;
    }
    switch (c.type) {
    case CMD_NONE:
        return;
    case CMD_HELP:
        emit(json_help(outBuf, sizeof(outBuf)));
        return;
    case CMD_PING:
        ack(c);
        return;
    case CMD_STATUS:
        sendStatus(now);
        return;

    case CMD_BIND:
    case CMD_UID:
        memcpy(tracker.cfg.uid, c.uid, 6);
        tracker.cfg.has_uid = 1;
        saveConfig();
        ack(c);
        Serial.flush();
        delay(100);
        ESP.restart(); // the MAC can only be changed cleanly at boot
        return;

    case CMD_HOME_SET:
        tracker.setHome(c.v[0], c.v[1], (float)c.v[2]);
        ack(c);
        return;
    case CMD_HOME_DRONE:
        if (tracker.setHomeFromDrone(now))
            ack(c);
        else
            fail("no usable drone GPS (need >= min_sats and a recent fix)");
        return;
    case CMD_HOME_CLEAR:
        tracker.clearHome();
        autoHome.reset();
        ack(c);
        return;
    case CMD_HOME_GPS:
        if (!gpsPresent(now)) {
            fail("no tracker GPS (check wiring / PIN_GPS_RX)");
            return;
        }
        // keep tracking with the current home until the new average is locked
        tracker.cfg.home_src = HOME_SRC_GPS;
        tracker.cfg.auto_home = 1;
        autoHome.reset();
        ack(c);
        return;
    case CMD_CAL_START:
        if (!sensors.hasMag()) {
            fail("no compass found");
            return;
        }
        magCal.start();
        ack(c);
        return;
    case CMD_CAL_STOP: {
        if (!magCal.active()) {
            fail("no calibration running (CAL MAG START)");
            return;
        }
        const char *why = "";
        MagCalibration mc;
        if (magCal.finish(&mc, &why)) {
            tracker.cfg.magcal = mc;
            headingFilter.reset();
            ack(c); // SAVE keeps it
        } else {
            fail(why);
        }
        return;
    }
    case CMD_CAL_CLEAR:
        magcal_identity(&tracker.cfg.magcal);
        headingFilter.reset();
        northApplied = false;
        ack(c);
        return;

    case CMD_MODE_AUTO:
        tracker.setAuto();
        ack(c);
        return;
    case CMD_MODE_MANUAL:
        tracker.setManual(tracker.pan(), tracker.tilt());
        ack(c);
        return;
    case CMD_AIM:
        tracker.setManual((float)c.v[0], (float)c.v[1]);
        ack(c);
        return;

    case CMD_SET: {
        TrackerConfig backup = tracker.cfg;
        char err[48];
        if (!cfg_set(&tracker.cfg, c.text, c.v[0], err)) {
            fail(err);
            return;
        }
        if (tracker.cfg.pan_min_us >= tracker.cfg.pan_max_us || tracker.cfg.tilt_min_us >= tracker.cfg.tilt_max_us) {
            tracker.cfg = backup;
            fail("min_us must be lower than max_us");
            return;
        }
        tracker.recompute();
        ack(c);
        return;
    }

    case CMD_SAVE:
        saveConfig();
        ack(c);
        return;
    case CMD_FACTORY:
        factoryReset();
        ack(c);
        Serial.flush();
        delay(100);
        ESP.restart();
        return;
    case CMD_REBOOT:
        ack(c);
        Serial.flush();
        delay(100);
        ESP.restart();
        return;
    default:
        return;
    }
}

static void pollSerial(uint32_t now)
{
    while (Serial.available() > 0) {
        int ch = Serial.read();
        if (ch < 0) break;
        if (ch == '\n') {
            if (!lineOverflow) {
                lineBuf[lineLen] = '\0';
                handleCommand(lineBuf, now);
            } else {
                fail("line too long");
            }
            lineLen = 0;
            lineOverflow = false;
        } else if (ch != '\r') {
            if (lineLen < sizeof(lineBuf) - 1)
                lineBuf[lineLen++] = (char)ch;
            else
                lineOverflow = true;
        }
    }
}

// ---- screen (TTGO TS) ------------------------------------------------------------------------------

#if HAS_TFT
static void updateScreen(uint32_t now)
{
    ButtonEvent ev[3];
    display.pollButtons(now, ev);
    if (ev[0] == BTN_SHORT) {
        screenPage = (uint8_t)((screenPage + 1) % PAGE_COUNT);
        lastScreenMs = 0; // repaint now
    }
    if (ev[1] == BTN_LONG) {
        if (screenPage == PAGE_SENSORS) handleCommand(magCal.active() ? "CAL MAG STOP" : "CAL MAG START", now);
        else handleCommand(gpsPresent(now) && nmea.fix().valid ? "HOME GPS" : "HOME DRONE", now);
        display.toast(lastResult, lastOk ? SC_GREEN : SC_RED, now);
    }
    if (ev[2] == BTN_LONG) {
        handleCommand("SAVE", now);
        display.toast(lastOk ? "Saved to flash" : lastResult, lastOk ? SC_GREEN : SC_RED, now);
    }
    if (now - lastScreenMs < SCREEN_REFRESH_MS) return;
    lastScreenMs = now;

    ScreenData d;
    memset(&d, 0, sizeof(d));
    d.now_ms = now;
    d.has_uid = tracker.cfg.has_uid;
    d.espnow = espnowOn;
    memcpy(d.uid, tracker.cfg.uid, 6);
    d.rx_per_s = rxPerSecond;
    d.rx_age_ms = everRx ? now - lastRxMs : 0xFFFFFFFFu;
    d.has_link = haveLink;
    d.link = lastLink;
    d.has_bat = haveBat;
    d.bat = lastBat;
    strncpy(d.mode, lastMode, sizeof(d.mode) - 1);
    d.trk = &tracker;
    d.tgps_present = gpsPresent(now);
    d.tfix = nmea.fix();
    d.tgps_baud = gpsBaud;
    d.ahome_state = autoHome.state();
    d.ahome_pct = autoHome.progress();
    d.sens = sensorReport();
    ScreenLine lines[SCREEN_LINES];
    int n = screen_page(screenPage, d, lines);
    display.draw(lines, n);
}
#endif

// ---- Arduino entry points ------------------------------------------------------------------------

void setup()
{
    Serial.begin(SERIAL_BAUD);
#if defined(ARDUINO_USB_CDC_ON_BOOT) && ARDUINO_USB_CDC_ON_BOOT
    // Never block the servo loop when nobody is listening on the USB port (tracker powered by a charger).
    Serial.setTxTimeoutMs(0);
#endif

#if PIN_LED >= 0
    pinMode(PIN_LED, OUTPUT);
    digitalWrite(PIN_LED, !LED_ON_LEVEL);
#endif

    tracker.begin();
    loadConfig();
    tracker.recompute();
    attachServos();

#if HAS_TFT
    display.begin();
#endif
    sensorsOn = sensors.begin(PIN_SDA, PIN_SCL);
#if PIN_GPS_RX >= 0
    gpsSetBaud(tracker.cfg.gps_baud ? tracker.cfg.gps_baud : GPS_BAUDS[0], millis());
#endif
    // A home that came from the tracker GPS last time is re-measured: the tracker may be at a new field.
    if (tracker.cfg.home_src == HOME_SRC_GPS && PIN_GPS_RX >= 0) autoHome.reset();

    rxQueue = xQueueCreate(16, sizeof(NowPkt));
    espnowOn = tracker.cfg.has_uid && startEspNow();

    sendStatus(millis());
}

void loop()
{
    const uint32_t now = millis();

    // 1) telemetry from the Backpack
    NowPkt p;
    for (int i = 0; i < 8 && xQueueReceive(rxQueue, &p, 0) == pdTRUE; ++i) handlePacket(p, now);

    // 2) commands from the host
    pollSerial(now);

    // 2b) tracker sensors
    pollGps(now);
    pollCompass(now);
    if (now - rxSecondStart >= 1000) {
        rxPerSecond = rxThisSecond;
        rxThisSecond = 0;
        rxSecondStart = now;
    }

    // 3) servos
    if (now - lastServoMs >= SERVO_PERIOD_MS) {
        lastServoMs = now;
        tracker.update(now);
        panServo.writeMicroseconds(tracker.panUs());
        tiltServo.writeMicroseconds(tracker.tiltUs());
    }

    // 4) periodic reports
    if (now - lastTrkMs >= TRACKER_REPORT_MS) {
        lastTrkMs = now;
        emit(json_tracker(outBuf, sizeof(outBuf), now, tracker));
    }
    if (now - lastStatMs >= STATS_REPORT_MS) {
        lastStatMs = now;
        emit(json_stats(outBuf, sizeof(outBuf), now, counters));
    }
    if (now - lastSensMs >= SENSOR_REPORT_MS) {
        lastSensMs = now;
        reportSensors(now);
    }
    if (now - lastHelloMs >= HELLO_REPORT_MS) {
        lastHelloMs = now;
        emit(json_hello(outBuf, sizeof(outBuf), FW_VERSION, ESP.getChipModel(), tracker.cfg, espnowOn));
    }

#if HAS_TFT
    updateScreen(now);
#endif

#if PIN_LED >= 0
    if (ledOffAt && (int32_t)(now - ledOffAt) >= 0) {
        digitalWrite(PIN_LED, !LED_ON_LEVEL);
        ledOffAt = 0;
    }
#endif

    delay(1);
}
