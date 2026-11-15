#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/*
 * The settings Home Assistant pushes to the sensor. Pure logic (no ESP-IDF),
 * so it is covered by the host tests. Wire format: PROTOCOL.md, "Settings".
 */

#define WP_CFG_VERSION     1
#define WP_CFG_MAX_SSIDS   8
#define WP_CFG_SSID_MAX    32
#define WP_CFG_HDR_LEN     15
#define WP_CFG_BLOB_MAX    (WP_CFG_HDR_LEN + WP_CFG_MAX_SSIDS * (1 + WP_CFG_SSID_MAX))

enum { WP_BAND_BOTH = 0, WP_BAND_2G = 1, WP_BAND_5G = 2 };

/* Limits and defaults. The Home Assistant integration uses the same numbers. */
#define WP_CFG_SCAN_DWELL_MIN   120   /* must exceed one beacon interval (~102 ms) */
#define WP_CFG_SCAN_DWELL_MAX   1500
#define WP_CFG_SCAN_DWELL_DEF   200
#define WP_CFG_HOP_MIN          200
#define WP_CFG_HOP_MAX          30000
#define WP_CFG_HOP_DEF          2000
#define WP_CFG_RESCAN_MIN       30
#define WP_CFG_RESCAN_MAX       3600
#define WP_CFG_RESCAN_DEF       600
#define WP_CFG_MIN_FRAMES_MIN   1
#define WP_CFG_MIN_FRAMES_MAX   100
#define WP_CFG_MIN_FRAMES_DEF   3
#define WP_CFG_HOLD_MIN         10
#define WP_CFG_HOLD_MAX         43200
#define WP_CFG_HOLD_DEF         300
#define WP_CFG_MIN_RSSI_MIN     (-100)
#define WP_CFG_MIN_RSSI_MAX     (-20)
#define WP_CFG_MIN_RSSI_DEF     (-100) /* = hear everything */

typedef struct {
    uint8_t  band;                 /* WP_BAND_* */
    char     country[3];           /* 2 upper-case letters + NUL */
    uint16_t scan_dwell_ms;        /* passive AP scan, per channel */
    uint16_t hop_ms;               /* sniffing, per channel, when hopping */
    uint16_t rescan_s;             /* between AP scans */
    uint8_t  min_frames;           /* frames before a client counts */
    uint16_t hold_s;               /* keep a client this long after its last frame */
    int8_t   min_rssi;             /* ignore frames weaker than this (dBm) */
    uint8_t  ssid_count;
    char     ssids[WP_CFG_MAX_SSIDS][WP_CFG_SSID_MAX + 1];
} wp_config_t;

/** Fill in the defaults: no SSIDs, so the sensor idles until it is configured. */
void wp_config_defaults(wp_config_t *c);

/** True when every field is inside its limits. */
bool wp_config_valid(const wp_config_t *c);

/** Serialise a valid config. Returns the length, or 0 if invalid or `cap` too small. */
size_t wp_config_encode(const wp_config_t *c, uint8_t *out, size_t cap);

/** Parse and validate a blob (strict: no trailing bytes). */
bool wp_config_decode(const uint8_t *blob, size_t len, wp_config_t *out);

/** Standard CRC-32 (IEEE 802.3, as zlib.crc32). Identifies a settings blob. */
uint32_t wp_crc32(const uint8_t *data, size_t len);
