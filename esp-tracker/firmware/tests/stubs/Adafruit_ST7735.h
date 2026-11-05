#pragma once
#include <stdint.h>
#include "SPI.h"
#define INITR_GREENTAB 0x00
#define INITR_REDTAB 0x01
#define INITR_BLACKTAB 0x02
class Adafruit_ST7735 {
public:
    Adafruit_ST7735(SPIClass *spi, int8_t cs, int8_t dc, int8_t rst);
    void initR(uint8_t options);
    void setRotation(uint8_t r);
    void fillScreen(uint16_t c);
    void fillRect(int16_t x, int16_t y, int16_t w, int16_t h, uint16_t c);
    void setTextWrap(bool w);
    void setTextSize(uint8_t s);
    void setTextColor(uint16_t fg, uint16_t bg);
    void setCursor(int16_t x, int16_t y);
    size_t print(const char *s);
};
