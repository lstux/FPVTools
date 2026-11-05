#pragma once
#include <stddef.h>
#include <stdint.h>
class Preferences {
public:
    bool begin(const char *name, bool readOnly = false);
    void end();
    bool clear();
    size_t putBytes(const char *key, const void *value, size_t len);
    size_t getBytes(const char *key, void *buf, size_t maxLen);
    size_t getBytesLength(const char *key);
};
