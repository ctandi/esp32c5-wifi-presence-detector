#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "presence.h"

#define WP_REPORT_VERSION   2
#define WP_REPORT_HDR_LEN   12  /* ver, flags, uptime(4), ap_count, cfg_crc(4), n */
#define WP_REPORT_ENTRY_LEN 9   /* mac(6), rssi, age(2) */
#define WP_REPORT_FLAG_TRUNCATED 0x01

/** Largest plaintext report for `max_clients` clients. */
#define WP_REPORT_MAX_LEN(max_clients) (WP_REPORT_HDR_LEN + (max_clients) * WP_REPORT_ENTRY_LEN)

/**
 * Serialise the client list (see PROTOCOL.md). At most 255 clients fit; more
 * set the truncated flag. `cfg_crc` identifies the settings in force (0 = none
 * stored yet). Returns the number of bytes written, or 0 when `cap` is too small.
 */
size_t wp_report_pack(uint8_t *out, size_t cap, uint32_t uptime_s, uint8_t ap_count,
                      uint32_t cfg_crc, const wp_client_info_t *clients, size_t n);

/** Number of fragments needed for `len` bytes at `data_per_chunk` bytes each. */
size_t wp_frag_count(size_t len, size_t data_per_chunk);

/**
 * Build fragment `seq` of `msg` into `out` (1 header byte + data). Header bit 7
 * marks the last fragment, bits 0-6 hold `seq`. Returns the bytes written, or
 * 0 for a bad argument (seq out of range, data_per_chunk 0, or more than 128
 * fragments).
 */
size_t wp_frag_build(const uint8_t *msg, size_t len, size_t data_per_chunk,
                     size_t seq, uint8_t *out);

/** Collects the fragments of one incoming message (the inverse of wp_frag_build). */
typedef struct {
    uint8_t *buf;
    size_t   cap;
    size_t   len;
    uint8_t  next; /* sequence number expected next */
} wp_reasm_t;

enum { WP_REASM_ERR = -1, WP_REASM_MORE = 0, WP_REASM_DONE = 1 };

void wp_reasm_init(wp_reasm_t *r, uint8_t *buf, size_t cap);
void wp_reasm_reset(wp_reasm_t *r);

/**
 * Feed one fragment (header byte + data). Returns WP_REASM_DONE when the last
 * fragment arrived (message in r->buf, r->len bytes; call wp_reasm_reset before
 * the next one), WP_REASM_MORE when more are needed, WP_REASM_ERR on a gap, an
 * overflow or an empty fragment (the reassembler resets itself).
 */
int wp_reasm_feed(wp_reasm_t *r, const uint8_t *chunk, size_t len);
