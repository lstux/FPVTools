#pragma once
#include <stdint.h>
typedef enum { WIFI_OFF = 0, WIFI_STA = 1, WIFI_AP = 2, WIFI_AP_STA = 3 } wifi_mode_t_stub;
struct WiFiStub {
    bool mode(wifi_mode_t_stub m);
    bool begin(const char *ssid, const char *pass, int32_t channel);
    bool disconnect(bool wifioff = false);
};
extern WiFiStub WiFi;
