#include "frame_parse.h"

#include <string.h>

#define FC0_TYPE(fc0)    (((fc0) >> 2) & 0x3)
#define FRAME_TYPE_DATA  2
#define FC1_TO_DS        0x01
#define FC1_FROM_DS      0x02
#define DATA_HDR_MIN     24 /* fc, dur, addr1-3, seq */

bool wp_parse_data_frame(const uint8_t *frame, size_t len,
                         uint8_t sta[6], uint8_t bssid[6])
{
    if (len < DATA_HDR_MIN) {
        return false;
    }
    if (FC0_TYPE(frame[0]) != FRAME_TYPE_DATA) {
        return false;
    }

    const uint8_t ds = frame[1] & (FC1_TO_DS | FC1_FROM_DS);
    const uint8_t *addr1 = frame + 4;
    const uint8_t *addr2 = frame + 10;
    const uint8_t *client;
    const uint8_t *ap;

    if (ds == FC1_TO_DS) {
        ap = addr1;
        client = addr2;
    } else if (ds == FC1_FROM_DS) {
        client = addr1;
        ap = addr2;
    } else {
        return false; /* IBSS (neither) or WDS (both) */
    }

    if (client[0] & 0x01) {
        return false; /* broadcast / multicast destination */
    }

    memcpy(sta, client, 6);
    memcpy(bssid, ap, 6);
    return true;
}

static int hex_nibble(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

bool wp_parse_mac(const char *text, uint8_t mac[6])
{
    if (!text) {
        return false;
    }
    for (int i = 0; i < 6; i++) {
        int hi = hex_nibble(text[0]);
        int lo = hi < 0 ? -1 : hex_nibble(text[1]);
        if (hi < 0 || lo < 0) {
            return false;
        }
        mac[i] = (uint8_t)((hi << 4) | lo);
        text += 2;
        if (i < 5) {
            if (*text != ':' && *text != '-') {
                return false;
            }
            text++;
        }
    }
    return *text == '\0';
}

bool wp_hex_decode(const char *hex, uint8_t *out, size_t out_len)
{
    if (!hex || strlen(hex) != out_len * 2) {
        return false;
    }
    for (size_t i = 0; i < out_len; i++) {
        int hi = hex_nibble(hex[2 * i]);
        int lo = hex_nibble(hex[2 * i + 1]);
        if (hi < 0 || lo < 0) {
            return false;
        }
        out[i] = (uint8_t)((hi << 4) | lo);
    }
    return true;
}
