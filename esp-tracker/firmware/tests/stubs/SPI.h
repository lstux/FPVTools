#pragma once
#include <stdint.h>
struct SPIClass {
    void begin(int8_t sck, int8_t miso, int8_t mosi, int8_t ss);
};
extern SPIClass SPI;
