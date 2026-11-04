#include "msp.h"

#include <string.h>

#include "crc8.h"

void MspParser::reset()
{
    state_ = IDLE;
    hdrPos_ = 0;
    payloadPos_ = 0;
    crc_ = 0;
}

bool MspParser::feed(uint8_t c, MspPacket *out)
{
    switch (state_) {
    case IDLE:
        if (c == '$') state_ = GOT_DOLLAR;
        break;

    case GOT_DOLLAR:
        state_ = (c == 'X') ? GOT_X : IDLE;
        break;

    case GOT_X:
        if (c == '<' || c == '>') {
            pkt_.type = (char)c;
            hdrPos_ = 0;
            crc_ = 0;
            state_ = HEADER;
        } else {
            state_ = IDLE;
        }
        break;

    case HEADER:
        hdr_[hdrPos_++] = c;
        crc_ = crc8_d5_update(crc_, c);
        if (hdrPos_ == sizeof(hdr_)) {
            pkt_.flags = hdr_[0];
            pkt_.function = (uint16_t)(hdr_[1] | (hdr_[2] << 8));
            pkt_.size = (uint16_t)(hdr_[3] | (hdr_[4] << 8));
            payloadPos_ = 0;
            if (pkt_.size > MSP_MAX_PAYLOAD) {
                ++oversize;
                state_ = IDLE;
            } else {
                state_ = (pkt_.size == 0) ? CHECKSUM : PAYLOAD;
            }
        }
        break;

    case PAYLOAD:
        pkt_.payload[payloadPos_++] = c;
        crc_ = crc8_d5_update(crc_, c);
        if (payloadPos_ == pkt_.size) state_ = CHECKSUM;
        break;

    case CHECKSUM:
        state_ = IDLE;
        if (c == crc_) {
            *out = pkt_;
            return true;
        }
        ++crcErrors;
        break;
    }
    return false;
}
