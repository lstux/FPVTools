#include "baro_calc.h"

#include <math.h>

void bmp180_parse_cal(const uint8_t r[22], Bmp180Cal *c)
{
    auto s16 = [&](int i) { return (int16_t)((r[i] << 8) | r[i + 1]); };
    auto u16 = [&](int i) { return (uint16_t)((r[i] << 8) | r[i + 1]); };
    c->ac1 = s16(0);
    c->ac2 = s16(2);
    c->ac3 = s16(4);
    c->ac4 = u16(6);
    c->ac5 = u16(8);
    c->ac6 = u16(10);
    c->b1 = s16(12);
    c->b2 = s16(14);
    c->mb = s16(16);
    c->mc = s16(18);
    c->md = s16(20);
}

void bmp180_compensate(const Bmp180Cal &c, int32_t ut, int32_t up, uint8_t oss, float *temp_c, float *press_pa)
{
    // Datasheet section 3.5, integer algorithm
    int32_t x1 = ((ut - (int32_t)c.ac6) * (int32_t)c.ac5) >> 15;
    int32_t x2 = ((int32_t)c.mc * 2048) / (x1 + c.md);
    int32_t b5 = x1 + x2;
    *temp_c = ((b5 + 8) >> 4) / 10.0f;

    int32_t b6 = b5 - 4000;
    x1 = ((int32_t)c.b2 * ((b6 * b6) >> 12)) >> 11;
    x2 = ((int32_t)c.ac2 * b6) >> 11;
    int32_t x3 = x1 + x2;
    int32_t b3 = ((((int32_t)c.ac1 * 4 + x3) * (1 << oss)) + 2) / 4;
    x1 = ((int32_t)c.ac3 * b6) >> 13;
    x2 = ((int32_t)c.b1 * ((b6 * b6) >> 12)) >> 16;
    x3 = ((x1 + x2) + 2) >> 2;
    uint32_t b4 = ((uint32_t)c.ac4 * (uint32_t)(x3 + 32768)) >> 15;
    uint32_t b7 = ((uint32_t)up - (uint32_t)b3) * (uint32_t)(50000 >> oss);
    int32_t p;
    if (b7 < 0x80000000u) p = (int32_t)((b7 * 2) / b4);
    else p = (int32_t)((b7 / b4) * 2);
    x1 = (p >> 8) * (p >> 8);
    x1 = (x1 * 3038) >> 16;
    x2 = (-7357 * p) >> 16;
    p = p + ((x1 + x2 + 3791) >> 4);
    *press_pa = (float)p;
}

void bmp280_parse_cal(const uint8_t r[24], Bmp280Cal *c)
{
    auto u16 = [&](int i) { return (uint16_t)(r[i] | (r[i + 1] << 8)); };
    auto s16 = [&](int i) { return (int16_t)u16(i); };
    c->t1 = u16(0);
    c->t2 = s16(2);
    c->t3 = s16(4);
    c->p1 = u16(6);
    c->p2 = s16(8);
    c->p3 = s16(10);
    c->p4 = s16(12);
    c->p5 = s16(14);
    c->p6 = s16(16);
    c->p7 = s16(18);
    c->p8 = s16(20);
    c->p9 = s16(22);
}

bool bmp280_compensate(const Bmp280Cal &c, int32_t adc_t, int32_t adc_p, float *temp_c, float *press_pa)
{
    // Datasheet section 3.11.3 (32-bit temperature, 64-bit pressure)
    // left shifts of possibly negative values are written as multiplications (same result, no UB)
    int32_t var1 = ((((adc_t >> 3) - ((int32_t)c.t1 * 2))) * ((int32_t)c.t2)) >> 11;
    int32_t var2 = (((((adc_t >> 4) - ((int32_t)c.t1)) * ((adc_t >> 4) - ((int32_t)c.t1))) >> 12) * ((int32_t)c.t3)) >> 14;
    int32_t t_fine = var1 + var2;
    *temp_c = ((t_fine * 5 + 128) >> 8) / 100.0f;

    int64_t v1 = ((int64_t)t_fine) - 128000;
    int64_t v2 = v1 * v1 * (int64_t)c.p6;
    v2 = v2 + ((v1 * (int64_t)c.p5) * 131072);
    v2 = v2 + (((int64_t)c.p4) * 34359738368LL);
    v1 = ((v1 * v1 * (int64_t)c.p3) >> 8) + ((v1 * (int64_t)c.p2) * 4096);
    v1 = (((((int64_t)1) << 47) + v1)) * ((int64_t)c.p1) >> 33;
    if (v1 == 0) return false;
    int64_t p = 1048576 - adc_p;
    p = (((p * 2147483648LL) - v2) * 3125) / v1;
    v1 = (((int64_t)c.p9) * (p >> 13) * (p >> 13)) >> 25;
    v2 = (((int64_t)c.p8) * p) >> 19;
    p = ((p + v1 + v2) >> 8) + (((int64_t)c.p7) * 16);
    *press_pa = (float)p / 256.0f;
    return true;
}

float pressure_altitude_m(float press_pa, float p0_pa)
{
    if (press_pa <= 0 || p0_pa <= 0) return 0.0f;
    return 44330.0f * (1.0f - powf(press_pa / p0_pa, 0.1902949f));
}
