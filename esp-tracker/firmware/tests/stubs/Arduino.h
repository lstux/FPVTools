// Minimal stand-in for the Arduino-ESP32 API subset used by src/main.cpp.
// Only for `make syntax` (compile check on a PC) - NOT the real core.
#pragma once
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define HIGH 1
#define LOW 0
#define OUTPUT 1
#define INPUT 0
#define INPUT_PULLUP 2
#define SERIAL_8N1 0x800001c

int digitalRead(uint8_t pin);

unsigned long millis();
void delay(uint32_t ms);
void pinMode(uint8_t pin, uint8_t mode);
void digitalWrite(uint8_t pin, uint8_t val);

struct HWSerialStub {
    void begin(unsigned long baud);
    size_t write(const uint8_t *buf, size_t n);
    size_t write(uint8_t b);
    int available();
    int read();
    void flush();
    void setTxTimeoutMs(uint32_t ms);
};
extern HWSerialStub Serial;

class HardwareSerial {
public:
    explicit HardwareSerial(int uart);
    void begin(unsigned long baud, uint32_t config, int8_t rx, int8_t tx);
    void end();
    int available();
    int read();
};

struct EspStub {
    void restart();
    const char *getChipModel();
};
extern EspStub ESP;
