#include "crc8.h"

uint8_t crc8_d5_update(uint8_t crc, uint8_t byte)
{
    crc ^= byte;
    for (int i = 0; i < 8; ++i)
        crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0xD5) : (uint8_t)(crc << 1);
    return crc;
}

uint8_t crc8_d5(const uint8_t *data, size_t len, uint8_t init)
{
    uint8_t crc = init;
    for (size_t i = 0; i < len; ++i)
        crc = crc8_d5_update(crc, data[i]);
    return crc;
}
