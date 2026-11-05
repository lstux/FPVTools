#pragma once
#include <stdint.h>
class ESP32PWM {
public:
    static void allocateTimer(int timer);
};
class Servo {
public:
    int attach(int pin, int minUs, int maxUs);
    void setPeriodHertz(int hz);
    void writeMicroseconds(int us);
};
