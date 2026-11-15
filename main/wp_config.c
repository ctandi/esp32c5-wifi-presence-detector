#include "wp_config.h"

#include <string.h>

void wp_config_defaults(wp_config_t *c)
{
    memset(c, 0, sizeof(*c));
    c->band = WP_BAND_BOTH;
    strcpy(c->country, "DE");
    c->scan_dwell_ms = WP_CFG_SCAN_DWELL_DEF;
    c->hop_ms = WP_CFG_HOP_DEF;
    c->rescan_s = WP_CFG_RESCAN_DEF;
    c->min_frames = WP_CFG_MIN_FRAMES_DEF;
    c->hold_s = WP_CFG_HOLD_DEF;
    c->min_rssi = WP_CFG_MIN_RSSI_DEF;
}

bool wp_config_valid(const wp_config_t *c)
{
    if (c->band > WP_BAND_5G) return false;
    for (int i = 0; i < 2; i++) {
        if (c->country[i] < 'A' || c->country[i] > 'Z') return false;
    }
    if (c->scan_dwell_ms < WP_CFG_SCAN_DWELL_MIN || c->scan_dwell_ms > WP_CFG_SCAN_DWELL_MAX) return false;
    if (c->hop_ms < WP_CFG_HOP_MIN || c->hop_ms > WP_CFG_HOP_MAX) return false;
    if (c->rescan_s < WP_CFG_RESCAN_MIN || c->rescan_s > WP_CFG_RESCAN_MAX) return false;
    if (c->min_frames < WP_CFG_MIN_FRAMES_MIN || c->min_frames > WP_CFG_MIN_FRAMES_MAX) return false;
    if (c->hold_s < WP_CFG_HOLD_MIN || c->hold_s > WP_CFG_HOLD_MAX) return false;
    if (c->min_rssi < WP_CFG_MIN_RSSI_MIN || c->min_rssi > WP_CFG_MIN_RSSI_MAX) return false;
    if (c->ssid_count > WP_CFG_MAX_SSIDS) return false;
    for (size_t i = 0; i < c->ssid_count; i++) {
        const char *end = memchr(c->ssids[i], '\0', WP_CFG_SSID_MAX + 1);
        if (!end || end == c->ssids[i]) return false; /* unterminated or empty */
    }
    return true;
}

static void put16(uint8_t *p, uint16_t v)
{
    p[0] = (uint8_t)(v >> 8);
    p[1] = (uint8_t)v;
}

static uint16_t get16(const uint8_t *p)
{
    return (uint16_t)((p[0] << 8) | p[1]);
}

size_t wp_config_encode(const wp_config_t *c, uint8_t *out, size_t cap)
{
    if (!wp_config_valid(c)) return 0;
    size_t need = WP_CFG_HDR_LEN;
    for (size_t i = 0; i < c->ssid_count; i++) need += 1 + strlen(c->ssids[i]);
    if (cap < need) return 0;

    out[0] = WP_CFG_VERSION;
    out[1] = c->band;
    out[2] = (uint8_t)c->country[0];
    out[3] = (uint8_t)c->country[1];
    put16(out + 4, c->scan_dwell_ms);
    put16(out + 6, c->hop_ms);
    put16(out + 8, c->rescan_s);
    out[10] = c->min_frames;
    put16(out + 11, c->hold_s);
    out[13] = (uint8_t)c->min_rssi;
    out[14] = c->ssid_count;
    size_t i = WP_CFG_HDR_LEN;
    for (size_t k = 0; k < c->ssid_count; k++) {
        const size_t n = strlen(c->ssids[k]);
        out[i++] = (uint8_t)n;
        memcpy(out + i, c->ssids[k], n);
        i += n;
    }
    return i;
}

bool wp_config_decode(const uint8_t *b, size_t len, wp_config_t *out)
{
    if (len < WP_CFG_HDR_LEN || b[0] != WP_CFG_VERSION) return false;

    wp_config_t c;
    memset(&c, 0, sizeof(c));
    c.band = b[1];
    c.country[0] = (char)b[2];
    c.country[1] = (char)b[3];
    c.scan_dwell_ms = get16(b + 4);
    c.hop_ms = get16(b + 6);
    c.rescan_s = get16(b + 8);
    c.min_frames = b[10];
    c.hold_s = get16(b + 11);
    c.min_rssi = (int8_t)b[13];
    c.ssid_count = b[14];
    if (c.ssid_count > WP_CFG_MAX_SSIDS) return false;

    size_t i = WP_CFG_HDR_LEN;
    for (size_t k = 0; k < c.ssid_count; k++) {
        if (i >= len) return false;
        const size_t n = b[i++];
        if (n == 0 || n > WP_CFG_SSID_MAX || i + n > len) return false;
        for (size_t j = 0; j < n; j++) {
            if (b[i + j] == 0) return false; /* SSIDs are handled as C strings */
        }
        memcpy(c.ssids[k], b + i, n);
        i += n;
    }
    if (i != len || !wp_config_valid(&c)) return false;
    *out = c;
    return true;
}

uint32_t wp_crc32(const uint8_t *data, size_t len)
{
    uint32_t crc = 0xFFFFFFFFu;
    for (size_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (int b = 0; b < 8; b++) {
            crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1u)));
        }
    }
    return ~crc;
}
