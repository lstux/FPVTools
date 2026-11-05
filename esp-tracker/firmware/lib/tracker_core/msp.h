// Streaming parser for MSP v2 "native" packets as used by the ExpressLRS Backpack.
//
//   '$' 'X' type('<' or '>') flags(1) function(2, LE) size(2, LE) payload(size) crc8_d5
//
// The CRC covers flags..payload. The ELRS TX Backpack forwards CRSF telemetry with
// function MSP_ELRS_BACKPACK_CRSF_TLM (0x11); the payload is one complete CRSF frame.
#pragma once
#include <stddef.h>
#include <stdint.h>

#define MSP_ELRS_BACKPACK_CRSF_TLM 0x0011
#define MSP_MAX_PAYLOAD 128

struct MspPacket {
    char type;         // '<' command, '>' response
    uint8_t flags;
    uint16_t function;
    uint16_t size;
    uint8_t payload[MSP_MAX_PAYLOAD];
};

class MspParser {
public:
    MspParser() { reset(); }
    void reset();
    // Feed one byte. Returns true when a complete, CRC-valid packet is available in `out`.
    bool feed(uint8_t c, MspPacket *out);

    uint32_t crcErrors = 0;  // packets dropped because of a bad checksum
    uint32_t oversize = 0;   // packets dropped because the payload did not fit MSP_MAX_PAYLOAD

private:
    enum State : uint8_t { IDLE, GOT_DOLLAR, GOT_X, HEADER, PAYLOAD, CHECKSUM };
    State state_;
    uint8_t hdr_[5];
    uint8_t hdrPos_;
    uint16_t payloadPos_;
    uint8_t crc_;
    MspPacket pkt_;
};
