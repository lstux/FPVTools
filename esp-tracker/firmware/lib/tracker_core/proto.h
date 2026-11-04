// Host <-> tracker serial protocol: one JSON object per line from the tracker,
// one ASCII command per line to the tracker. See docs/architecture.md.
#pragma once
#include <stddef.h>
#include <stdint.h>

#include "tracker_config.h"
#include "crsf.h"
#include "tracker.h"

// ---- tracker -> host events (each returns the number of bytes written, without newline) ----------

struct Counters {
    uint32_t espnow = 0;     // ESP-NOW packets accepted (right source MAC)
    uint32_t msp_ok = 0;     // MSP packets with a valid CRC
    uint32_t msp_bad = 0;    // MSP packets rejected (CRC / size)
    uint32_t crsf_ok = 0;    // CRSF frames with a valid CRC
    uint32_t crsf_bad = 0;   // CRSF frames rejected
    uint32_t crsf_other = 0; // valid CRSF frames of a type we do not decode
    uint32_t dropped = 0;    // ESP-NOW packets dropped because the queue was full
};

int json_hello(char *buf, size_t cap, const char *fw, const char *chip, const TrackerConfig &cfg, bool espnow_on);
int json_gps(char *buf, size_t cap, uint32_t ms, const CrsfGps &g);
int json_battery(char *buf, size_t cap, uint32_t ms, const CrsfBattery &b);
int json_link(char *buf, size_t cap, uint32_t ms, const CrsfLinkStats &l);
int json_attitude(char *buf, size_t cap, uint32_t ms, const CrsfAttitude &a);
int json_flight_mode(char *buf, size_t cap, uint32_t ms, const char *mode);
int json_tracker(char *buf, size_t cap, uint32_t ms, const Tracker &t);
int json_stats(char *buf, size_t cap, uint32_t ms, const Counters &c);
int json_config(char *buf, size_t cap, const TrackerConfig &c);
int json_ack(char *buf, size_t cap, const char *cmd);
int json_error(char *buf, size_t cap, const char *msg);
int json_help(char *buf, size_t cap);

// Escape a string for inclusion inside a JSON string literal. Returns the output length.
size_t json_escape(const char *in, char *out, size_t cap);

// ---- host -> tracker commands ---------------------------------------------------------------------

enum CmdType : uint8_t {
    CMD_NONE,
    CMD_HELP,
    CMD_PING,
    CMD_STATUS,
    CMD_BIND,        // text = phrase, uid = derived UID
    CMD_UID,         // uid
    CMD_HOME_SET,    // v[0]=lat v[1]=lon v[2]=alt
    CMD_HOME_DRONE,
    CMD_HOME_CLEAR,
    CMD_MODE_AUTO,
    CMD_MODE_MANUAL,
    CMD_AIM,         // v[0]=pan v[1]=tilt
    CMD_SET,         // text = key, v[0] = value
    CMD_SAVE,
    CMD_FACTORY,
    CMD_REBOOT,
    CMD_ERROR,
};

struct Cmd {
    CmdType type;
    double v[3];
    char text[64];
    uint8_t uid[6];
    char err[48];
};

// Parse one line (without the trailing newline). Returns false for malformed commands
// (c->type == CMD_ERROR, c->err filled). An empty line yields CMD_NONE and true.
bool cmd_parse(const char *line, Cmd *c);
const char *cmd_name(CmdType t);
