#pragma once
#include <stddef.h>
#include <stdint.h>
struct TwoWire {
    bool begin(int sda, int scl);
    void setClock(uint32_t hz);
    void beginTransmission(uint8_t addr);
    size_t write(uint8_t b);
    uint8_t endTransmission(bool stop = true);
    uint8_t requestFrom(uint8_t addr, uint8_t n);
    int read();
};
extern TwoWire Wire;
