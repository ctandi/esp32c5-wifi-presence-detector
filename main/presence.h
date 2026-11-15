#pragma once

#include <stddef.h>
#include <stdint.h>

typedef struct {
    uint8_t  mac[6];
    int8_t   rssi;     /* of the last frame heard (dBm) */
    uint32_t age_s;    /* seconds since the last frame */
    uint32_t frames;   /* frames counted since the entry was (re)created */
} wp_client_info_t;

/** Clear the table. Call once before anything else. */
void wp_presence_init(void);

/**
 * Presence rules: a client counts after `min_frames` frames and stays for
 * `hold_s` seconds after its last one; frames weaker than `min_rssi` dBm are
 * ignored. Takes effect immediately.
 */
void wp_presence_set_params(uint32_t min_frames, uint32_t hold_s, int8_t min_rssi);

/**
 * Record a frame from a client. Cheap and safe to call from the Wi-Fi task:
 * the table lock is held for a few microseconds.
 */
void wp_presence_seen(const uint8_t mac[6], int8_t rssi);

/**
 * Copy out the clients that count as present right now (see
 * wp_presence_set_params).
 * Returns the number of entries written (at most `max`).
 */
size_t wp_presence_snapshot(wp_client_info_t *out, size_t max);
