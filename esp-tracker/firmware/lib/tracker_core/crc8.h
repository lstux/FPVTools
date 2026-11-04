// CRC-8, polynomial 0xD5 (a.k.a. CRC-8/DVB-S2), initial value 0, no reflection.
// Used by CRSF frames (over type+payload) and by MSP v2 packets (over flags..payload).
#pragma once
#include <stddef.h>
#include <stdint.h>

uint8_t crc8_d5_update(uint8_t crc, uint8_t byte);
uint8_t crc8_d5(const uint8_t *data, size_t len, uint8_t init = 0);
