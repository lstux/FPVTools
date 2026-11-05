#include "md5.h"

#include <stdlib.h>
#include <string.h>

namespace {

const uint32_t K[64] = {
    0xd76aa478, 0xe8c7b756, 0x242070db, 0xc1bdceee, 0xf57c0faf, 0x4787c62a, 0xa8304613, 0xfd469501,
    0x698098d8, 0x8b44f7af, 0xffff5bb1, 0x895cd7be, 0x6b901122, 0xfd987193, 0xa679438e, 0x49b40821,
    0xf61e2562, 0xc040b340, 0x265e5a51, 0xe9b6c7aa, 0xd62f105d, 0x02441453, 0xd8a1e681, 0xe7d3fbc8,
    0x21e1cde6, 0xc33707d6, 0xf4d50d87, 0x455a14ed, 0xa9e3e905, 0xfcefa3f8, 0x676f02d9, 0x8d2a4c8a,
    0xfffa3942, 0x8771f681, 0x6d9d6122, 0xfde5380c, 0xa4beea44, 0x4bdecfa9, 0xf6bb4b60, 0xbebfbc70,
    0x289b7ec6, 0xeaa127fa, 0xd4ef3085, 0x04881d05, 0xd9d4d039, 0xe6db99e5, 0x1fa27cf8, 0xc4ac5665,
    0xf4292244, 0x432aff97, 0xab9423a7, 0xfc93a039, 0x655b59c3, 0x8f0ccc92, 0xffeff47d, 0x85845dd1,
    0x6fa87e4f, 0xfe2ce6e0, 0xa3014314, 0x4e0811a1, 0xf7537e82, 0xbd3af235, 0x2ad7d2bb, 0xeb86d391};

const uint8_t S[64] = {7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22,
                       5, 9,  14, 20, 5, 9,  14, 20, 5, 9,  14, 20, 5, 9,  14, 20,
                       4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23,
                       6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21};

inline uint32_t rotl(uint32_t x, uint8_t c) { return (x << c) | (x >> (32 - c)); }

void processBlock(uint32_t st[4], const uint8_t *p)
{
    uint32_t M[16];
    for (int i = 0; i < 16; ++i)
        M[i] = (uint32_t)p[i * 4] | ((uint32_t)p[i * 4 + 1] << 8) | ((uint32_t)p[i * 4 + 2] << 16) |
               ((uint32_t)p[i * 4 + 3] << 24);

    uint32_t A = st[0], B = st[1], C = st[2], D = st[3];
    for (uint32_t i = 0; i < 64; ++i) {
        uint32_t F, g;
        if (i < 16) {
            F = (B & C) | (~B & D);
            g = i;
        } else if (i < 32) {
            F = (D & B) | (~D & C);
            g = (5 * i + 1) % 16;
        } else if (i < 48) {
            F = B ^ C ^ D;
            g = (3 * i + 5) % 16;
        } else {
            F = C ^ (B | ~D);
            g = (7 * i) % 16;
        }
        F = F + A + K[i] + M[g];
        A = D;
        D = C;
        C = B;
        B = B + rotl(F, S[i]);
    }
    st[0] += A;
    st[1] += B;
    st[2] += C;
    st[3] += D;
}

int hexval(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

} // namespace

void md5(const uint8_t *data, size_t len, uint8_t out[16])
{
    uint32_t st[4] = {0x67452301, 0xefcdab89, 0x98badcfe, 0x10325476};
    size_t offset = 0;
    while (len - offset >= 64) {
        processBlock(st, data + offset);
        offset += 64;
    }

    uint8_t block[64];
    size_t rem = len - offset;
    memcpy(block, data + offset, rem);
    block[rem] = 0x80;
    if (rem >= 56) {
        memset(block + rem + 1, 0, 63 - rem);
        processBlock(st, block);
        memset(block, 0, 56);
    } else {
        memset(block + rem + 1, 0, 55 - rem);
    }
    uint64_t bits = (uint64_t)len * 8;
    for (int i = 0; i < 8; ++i)
        block[56 + i] = (uint8_t)(bits >> (8 * i));
    processBlock(st, block);

    for (int i = 0; i < 4; ++i)
        for (int j = 0; j < 4; ++j)
            out[i * 4 + j] = (uint8_t)(st[i] >> (8 * j));
}

bool uid_from_phrase(const char *phrase, uint8_t uid[6])
{
    static const char prefix[] = "-DMY_BINDING_PHRASE=\"";
    if (!phrase) return false;
    size_t n = strlen(phrase);
    if (n == 0 || n > 120) return false;

    uint8_t buf[sizeof(prefix) + 130];
    size_t pos = 0;
    memcpy(buf, prefix, sizeof(prefix) - 1);
    pos += sizeof(prefix) - 1;
    memcpy(buf + pos, phrase, n);
    pos += n;
    buf[pos++] = '"';

    uint8_t digest[16];
    md5(buf, pos, digest);
    memcpy(uid, digest, 6);
    return true;
}

void uid_to_mac(const uint8_t uid[6], uint8_t mac[6])
{
    memcpy(mac, uid, 6);
    mac[0] &= (uint8_t)~0x01;
}

bool uid_parse(const char *text, uint8_t uid[6])
{
    if (!text) return false;
    while (*text == ' ' || *text == '\t') ++text;

    if (strchr(text, ',')) { // decimal list "1,2,3,4,5,6"
        char *end = nullptr;
        const char *p = text;
        for (int i = 0; i < 6; ++i) {
            while (*p == ' ') ++p;
            long v = strtol(p, &end, 10);
            if (end == p || v < 0 || v > 255) return false;
            uid[i] = (uint8_t)v;
            p = end;
            while (*p == ' ') ++p;
            if (i < 5) {
                if (*p != ',') return false;
                ++p;
            }
        }
        while (*p == ' ' || *p == '\r' || *p == '\n') ++p;
        return *p == '\0';
    }

    // hex form, separators allowed
    int nib = 0;
    uint8_t out[6] = {0};
    for (const char *p = text; *p; ++p) {
        if (*p == ':' || *p == '-' || *p == ' ' || *p == '\r' || *p == '\n') continue;
        int v = hexval(*p);
        if (v < 0 || nib >= 12) return false;
        out[nib / 2] = (uint8_t)((out[nib / 2] << 4) | v);
        ++nib;
    }
    if (nib != 12) return false;
    memcpy(uid, out, 6);
    return true;
}
