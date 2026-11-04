// Board level defaults. Override any of these with -D flags in platformio.ini.
#pragma once

#define FW_VERSION "0.1.0"

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

// Servo loop / reporting periods
#define SERVO_PERIOD_MS 20
#define TRACKER_REPORT_MS 500
#define STATS_REPORT_MS 2000
#define HELLO_REPORT_MS 10000
