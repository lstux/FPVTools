// Board level defaults. Override any of these with -D flags in platformio.ini.
#pragma once

#define FW_VERSION "0.3.0"

#ifndef PIN_PAN
#error "PIN_PAN is not defined: set it in platformio.ini (build_flags = -DPIN_PAN=<gpio>)"
#endif
#ifndef PIN_TILT
#error "PIN_TILT is not defined: set it in platformio.ini (build_flags = -DPIN_TILT=<gpio>)"
#endif

#ifndef SERIAL_BAUD
#define SERIAL_BAUD 115200 // ignored on native USB-CDC (C3/S2)
#endif

// ExpressLRS Backpacks talk ESP-NOW on Wi-Fi channel 1.
#ifndef ESPNOW_CHANNEL
#define ESPNOW_CHANNEL 1
#endif

// Optional activity LED (blinks on every decoded GPS frame). -1 = disabled.
#ifndef PIN_LED
#define PIN_LED -1
#endif
#ifndef LED_ON_LEVEL
#define LED_ON_LEVEL HIGH
#endif

// ---- optional tracker sensors (any pin = -1 disables that part) ----------------------------------
// I2C bus for the IMU / compass / barometer module ("10DOF" GY-87, GY-91, GY-80, BN-880 compass...)
#ifndef PIN_SDA
#define PIN_SDA -1
#endif
#ifndef PIN_SCL
#define PIN_SCL -1
#endif
// GPS module UART (NMEA). RX = the ESP pin wired to the GPS "TX". TX is optional (not used yet).
#ifndef PIN_GPS_RX
#define PIN_GPS_RX -1
#endif
#ifndef PIN_GPS_TX
#define PIN_GPS_TX -1
#endif

// ---- optional ST7735 status screen + buttons (LilyGO TTGO TS) -------------------------------------
#ifndef HAS_TFT
#define HAS_TFT 0
#endif
#ifndef PIN_TFT_RST
#define PIN_TFT_RST -1
#endif
#ifndef PIN_TFT_BL
#define PIN_TFT_BL -1
#endif
#ifndef TFT_TAB
#define TFT_TAB INITR_GREENTAB   // try INITR_BLACKTAB / INITR_REDTAB if the picture is shifted
#endif
#ifndef TFT_SWAP_RB
#define TFT_SWAP_RB 0            // 1 if red and blue come out swapped
#endif
#ifndef PIN_BTN1
#define PIN_BTN1 -1
#endif
#ifndef PIN_BTN2
#define PIN_BTN2 -1
#endif
#ifndef PIN_BTN3
#define PIN_BTN3 -1
#endif
#ifndef BTN_ACTIVE_LEVEL
#define BTN_ACTIVE_LEVEL LOW
#endif

// Servo loop / reporting periods
#define SERVO_PERIOD_MS 20
#define TRACKER_REPORT_MS 500
#define STATS_REPORT_MS 2000
#define HELLO_REPORT_MS 10000
#define SENSOR_REPORT_MS 1000
#define SCREEN_REFRESH_MS 250
