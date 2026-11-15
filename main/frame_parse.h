#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/**
 * Pull the associated client (STA) and the BSSID out of an 802.11 data frame.
 *
 * Only data frames with exactly one of the ToDS/FromDS bits set are
 * understood, because only those carry a (client, BSSID) pair in their
 * addr1/addr2 fields:
 *   ToDS   (client -> AP): addr1 = BSSID, addr2 = client
 *   FromDS (AP -> client): addr1 = client, addr2 = BSSID
 *
 * Group-addressed frames (broadcast, multicast) and WDS frames are rejected.
 * Management frames are deliberately ignored: a probe response to a passing
 * phone would otherwise look like an association.
 */
bool wp_parse_data_frame(const uint8_t *frame, size_t len,
                         uint8_t sta[6], uint8_t bssid[6]);

/** Parse "aa:bb:cc:dd:ee:ff" (or '-' separated). Returns false on bad input. */
bool wp_parse_mac(const char *text, uint8_t mac[6]);

/** Decode exactly `out_len` bytes from a hex string (no separators). */
bool wp_hex_decode(const char *hex, uint8_t *out, size_t out_len);
