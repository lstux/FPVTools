// Text of the small status screen (TTGO TS: ST7735 160x128 in landscape). Built here as plain lines
// so the content can be unit tested; src/display.cpp only paints them.
#pragma once
#include <stddef.h>
#include <stdint.h>

#include "compass.h"
#include "nmea.h"
#include "proto.h"
#include "tracker.h"

enum ScreenColor : uint8_t { SC_WHITE, SC_GREY, SC_GREEN, SC_AMBER, SC_RED, SC_CYAN, SC_MAGENTA };

#define SCREEN_COLS 26 // 160 px / 6 px per character at text size 1
#define SCREEN_LINES 11

struct ScreenLine {
    char text[SCREEN_COLS + 1];
    uint8_t color;
    uint8_t size; // 1 = 6x8 px characters, 2 = 12x16 (13 columns)
};

struct ScreenData {
    uint32_t now_ms;
    // receiver
    bool has_uid;
    bool espnow;
    uint8_t uid[6];
    uint32_t rx_per_s;
    uint32_t rx_age_ms; // since the last ESP-NOW packet, 0xFFFFFFFF = never
    // drone telemetry
    bool has_link;
    CrsfLinkStats link;
    bool has_bat;
    CrsfBattery bat;
    char mode[16];
    // tracker
    const Tracker *trk;
    // tracker GPS
    bool tgps_present;
    NmeaFix tfix;
    uint32_t tgps_baud;
    uint8_t ahome_state; // AutoHome::State
    uint8_t ahome_pct;
    // sensors
    SensorReport sens;
};

enum ScreenPage : uint8_t { PAGE_LINK, PAGE_TRACK, PAGE_SENSORS, PAGE_COUNT };

// Fills `out` (at least SCREEN_LINES entries) and returns the number of lines.
int screen_page(uint8_t page, const ScreenData &d, ScreenLine *out);
