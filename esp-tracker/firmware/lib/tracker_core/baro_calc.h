// Pressure sensor compensation maths (from the Bosch datasheets), kept free of I2C code so it can be
// checked against the datasheet worked examples on a PC.
#pragma once
#include <stdint.h>

// ---- BMP085 / BMP180 ------------------------------------------------------------------------------
struct Bmp180Cal {
    int16_t ac1, ac2, ac3;
    uint16_t ac4, ac5, ac6;
    int16_t b1, b2, mb, mc, md;
};
// Parse the 22 calibration bytes read from 0xAA (big endian).
void bmp180_parse_cal(const uint8_t raw[22], Bmp180Cal *c);
// ut = raw temperature, up = raw pressure (already shifted right by 8 - oss). Outputs degC and Pa.
void bmp180_compensate(const Bmp180Cal &c, int32_t ut, int32_t up, uint8_t oss, float *temp_c, float *press_pa);

// ---- BMP280 / BME280 ------------------------------------------------------------------------------
struct Bmp280Cal {
    uint16_t t1;
    int16_t t2, t3;
    uint16_t p1;
    int16_t p2, p3, p4, p5, p6, p7, p8, p9;
};
// Parse the 24 calibration bytes read from 0x88 (little endian).
void bmp280_parse_cal(const uint8_t raw[24], Bmp280Cal *c);
// adc_t / adc_p are the 20-bit raw values. Returns false if the pressure cannot be computed.
bool bmp280_compensate(const Bmp280Cal &c, int32_t adc_t, int32_t adc_p, float *temp_c, float *press_pa);

// International standard atmosphere: altitude for a pressure, relative to `p0` (Pa, default 1013.25 hPa).
float pressure_altitude_m(float press_pa, float p0_pa = 101325.0f);
