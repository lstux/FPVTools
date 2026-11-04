// ESP-NOW antenna tracker for ExpressLRS Backpack telemetry.
//
//   TX module -> TX Backpack --(ESP-NOW, MSP v2 wrapping CRSF frames)--> this board
//   this board --(USB / UART, JSON lines)--> host application      (and pan/tilt servos)
//
// All the protocol, geometry and tracking logic lives in lib/tracker_core (unit tested on a PC).
// This file only wires it to the hardware: Wi-Fi/ESP-NOW, servos, NVS storage and the serial port.

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
#include "crsf.h"
#include "md5.h"
#include "msp.h"
#include "proto.h"
#include "tracker.h"

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

static uint32_t lastServoMs = 0, lastTrkMs = 0, lastStatMs = 0, lastHelloMs = 0;
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
        if (crsf_decode_battery(f, &b)) emit(json_battery(outBuf, sizeof(outBuf), now, b));
        break;
    }
    case CRSF_TYPE_LINK_STATS: {
        CrsfLinkStats l;
        if (crsf_decode_link_stats(f, &l)) emit(json_link(outBuf, sizeof(outBuf), now, l));
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
        if (crsf_decode_baro(f, &b)) emit(json_baro(outBuf, sizeof(outBuf), now, b));
        break;
    }
    case CRSF_TYPE_FLIGHT_MODE: {
        char mode[24];
        if (crsf_decode_flight_mode(f, mode, sizeof(mode))) emit(json_flight_mode(outBuf, sizeof(outBuf), now, mode));
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

static void ack(const Cmd &c) { emit(json_ack(outBuf, sizeof(outBuf), cmd_name(c.type))); }
static void fail(const char *msg) { emit(json_error(outBuf, sizeof(outBuf), msg)); }

static void sendStatus(uint32_t now)
{
    emit(json_hello(outBuf, sizeof(outBuf), FW_VERSION, ESP.getChipModel(), tracker.cfg, espnowOn));
    emit(json_config(outBuf, sizeof(outBuf), tracker.cfg));
    emit(json_tracker(outBuf, sizeof(outBuf), now, tracker));
    emit(json_stats(outBuf, sizeof(outBuf), now, counters));
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
    if (now - lastHelloMs >= HELLO_REPORT_MS) {
        lastHelloMs = now;
        emit(json_hello(outBuf, sizeof(outBuf), FW_VERSION, ESP.getChipModel(), tracker.cfg, espnowOn));
    }

#if PIN_LED >= 0
    if (ledOffAt && (int32_t)(now - ledOffAt) >= 0) {
        digitalWrite(PIN_LED, !LED_ON_LEVEL);
        ledOffAt = 0;
    }
#endif

    delay(1);
}
