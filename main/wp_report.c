#include "wp_report.h"

#include <string.h>

size_t wp_report_pack(uint8_t *out, size_t cap, uint32_t uptime_s, uint8_t ap_count,
                      uint32_t cfg_crc, const wp_client_info_t *clients, size_t n)
{
    uint8_t flags = 0;
    if (n > 255) {
        n = 255;
        flags |= WP_REPORT_FLAG_TRUNCATED;
    }
    const size_t need = WP_REPORT_MAX_LEN(n);
    if (cap < need) {
        return 0;
    }

    size_t i = 0;
    out[i++] = WP_REPORT_VERSION;
    out[i++] = flags;
    out[i++] = (uint8_t)(uptime_s >> 24);
    out[i++] = (uint8_t)(uptime_s >> 16);
    out[i++] = (uint8_t)(uptime_s >> 8);
    out[i++] = (uint8_t)uptime_s;
    out[i++] = ap_count;
    out[i++] = (uint8_t)(cfg_crc >> 24);
    out[i++] = (uint8_t)(cfg_crc >> 16);
    out[i++] = (uint8_t)(cfg_crc >> 8);
    out[i++] = (uint8_t)cfg_crc;
    out[i++] = (uint8_t)n;

    for (size_t k = 0; k < n; k++) {
        memcpy(&out[i], clients[k].mac, 6);
        i += 6;
        out[i++] = (uint8_t)clients[k].rssi;
        const uint32_t age = clients[k].age_s > 0xFFFF ? 0xFFFF : clients[k].age_s;
        out[i++] = (uint8_t)(age >> 8);
        out[i++] = (uint8_t)age;
    }
    return i;
}

size_t wp_frag_count(size_t len, size_t data_per_chunk)
{
    if (data_per_chunk == 0) {
        return 0;
    }
    return len == 0 ? 1 : (len + data_per_chunk - 1) / data_per_chunk;
}

size_t wp_frag_build(const uint8_t *msg, size_t len, size_t data_per_chunk,
                     size_t seq, uint8_t *out)
{
    const size_t count = wp_frag_count(len, data_per_chunk);
    if (count == 0 || count > 128 || seq >= count) {
        return 0;
    }
    const size_t off = seq * data_per_chunk;
    size_t n = len - off;
    if (n > data_per_chunk) {
        n = data_per_chunk;
    }
    out[0] = (uint8_t)(seq | (seq == count - 1 ? 0x80 : 0));
    memcpy(&out[1], msg + off, n);
    return 1 + n;
}

void wp_reasm_init(wp_reasm_t *r, uint8_t *buf, size_t cap)
{
    r->buf = buf;
    r->cap = cap;
    wp_reasm_reset(r);
}

void wp_reasm_reset(wp_reasm_t *r)
{
    r->len = 0;
    r->next = 0;
}

int wp_reasm_feed(wp_reasm_t *r, const uint8_t *chunk, size_t len)
{
    if (len < 1) {
        wp_reasm_reset(r);
        return WP_REASM_ERR;
    }
    const uint8_t seq = chunk[0] & 0x7F;
    const bool last = (chunk[0] & 0x80) != 0;
    const size_t n = len - 1;
    if (seq != r->next || r->len + n > r->cap) {
        wp_reasm_reset(r);
        return WP_REASM_ERR;
    }
    memcpy(r->buf + r->len, chunk + 1, n);
    r->len += n;
    if (!last) {
        r->next++;
        return WP_REASM_MORE;
    }
    r->next = 0; /* r->len stays for the caller */
    return WP_REASM_DONE;
}
