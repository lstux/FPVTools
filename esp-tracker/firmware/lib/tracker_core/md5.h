// Minimal MD5 (RFC 1321) plus the ExpressLRS bind-phrase -> UID derivation.
#pragma once
#include <stddef.h>
#include <stdint.h>

// One-shot MD5 of `len` bytes.
void md5(const uint8_t *data, size_t len, uint8_t out[16]);

// ExpressLRS derives the 6-byte UID from a bind phrase as
//   MD5( '-DMY_BINDING_PHRASE="' + phrase + '"' )[0..5]
// Returns false if the phrase is empty or too long (> 120 bytes).
bool uid_from_phrase(const char *phrase, uint8_t uid[6]);

// The Backpack soft-sets its Wi-Fi MAC to the UID with the multicast bit of the
// first byte cleared (a MAC must be unicast). ESP-NOW traffic is addressed to / sent from it.
void uid_to_mac(const uint8_t uid[6], uint8_t mac[6]);

// Parse a UID typed by the user: either 12 hex digits (colons/dashes allowed, e.g. "a1:b2:c3:d4:e5:f6")
// or six comma separated decimal bytes as printed by the ExpressLRS tools ("UID bytes: 161,178,195,212,229,246").
bool uid_parse(const char *text, uint8_t uid[6]);
