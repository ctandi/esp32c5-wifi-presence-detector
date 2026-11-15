/* Host-side tests for the pure logic.  Run: ./test/run_host_tests.sh */
#include <assert.h>
#include <stdio.h>
#include <string.h>

#include "../main/wp_config.h"
#include "../main/wp_report.h"
#include "../main/frame_parse.h"

static const uint8_t AP[6]  = { 0x00, 0x11, 0x22, 0x33, 0x44, 0x55 };
static const uint8_t STA[6] = { 0xda, 0xa1, 0x19, 0x0b, 0x2c, 0x3d };
static const uint8_t BCAST[6] = { 0xff, 0xff, 0xff, 0xff, 0xff, 0xff };

/* fc0 = type/subtype byte, fc1 = flags byte */
static size_t make_frame(uint8_t *f, uint8_t fc0, uint8_t fc1,
                         const uint8_t *a1, const uint8_t *a2, const uint8_t *a3)
{
    memset(f, 0, 32);
    f[0] = fc0;
    f[1] = fc1;
    memcpy(f + 4, a1, 6);
    memcpy(f + 10, a2, 6);
    memcpy(f + 16, a3, 6);
    return 28;
}

static void test_frames(void)
{
    uint8_t f[32], sta[6], bssid[6];

    /* QoS data, ToDS: STA -> AP */
    size_t n = make_frame(f, 0x88, 0x01, AP, STA, BCAST);
    assert(wp_parse_data_frame(f, n, sta, bssid));
    assert(!memcmp(sta, STA, 6) && !memcmp(bssid, AP, 6));

    /* QoS null (subtype 12), ToDS: what a sleeping phone sends */
    n = make_frame(f, 0xC8, 0x11, AP, STA, AP); /* PwrMgt bit set as well */
    assert(wp_parse_data_frame(f, n, sta, bssid));
    assert(!memcmp(sta, STA, 6));

    /* Data, FromDS: AP -> STA */
    n = make_frame(f, 0x08, 0x02, STA, AP, BCAST);
    assert(wp_parse_data_frame(f, n, sta, bssid));
    assert(!memcmp(sta, STA, 6) && !memcmp(bssid, AP, 6));

    /* FromDS broadcast (AP beacon-ish traffic): no client */
    n = make_frame(f, 0x08, 0x02, BCAST, AP, STA);
    assert(!wp_parse_data_frame(f, n, sta, bssid));

    /* WDS (both DS bits) and IBSS (neither) */
    n = make_frame(f, 0x08, 0x03, AP, STA, AP);
    assert(!wp_parse_data_frame(f, n, sta, bssid));
    n = make_frame(f, 0x08, 0x00, AP, STA, AP);
    assert(!wp_parse_data_frame(f, n, sta, bssid));

    /* Management frame (probe response, type 0) must not count */
    n = make_frame(f, 0x50, 0x00, STA, AP, AP);
    assert(!wp_parse_data_frame(f, n, sta, bssid));

    /* Control frame (ACK-like, type 1) */
    n = make_frame(f, 0xD4, 0x00, STA, AP, AP);
    assert(!wp_parse_data_frame(f, n, sta, bssid));

    /* Truncated */
    n = make_frame(f, 0x88, 0x01, AP, STA, BCAST);
    assert(!wp_parse_data_frame(f, 23, sta, bssid));
    (void)n;
}

static void test_mac(void)
{
    uint8_t m[6];
    assert(wp_parse_mac("aa:BB:cc:dd:ee:0f", m));
    assert(m[0] == 0xaa && m[1] == 0xbb && m[5] == 0x0f);
    assert(wp_parse_mac("aa-bb-cc-dd-ee-ff", m));
    assert(!wp_parse_mac("aa:bb:cc:dd:ee", m));
    assert(!wp_parse_mac("aa:bb:cc:dd:ee:ff:00", m));
    assert(!wp_parse_mac("gg:bb:cc:dd:ee:ff", m));
    assert(!wp_parse_mac("", m));
    assert(!wp_parse_mac(NULL, m));
}

static void test_hex(void)
{
    uint8_t k[4];
    assert(wp_hex_decode("00ff10Ab", k, 4));
    assert(k[0] == 0x00 && k[1] == 0xff && k[2] == 0x10 && k[3] == 0xab);
    assert(!wp_hex_decode("00ff10A", k, 4));    /* too short */
    assert(!wp_hex_decode("00ff10Abcd", k, 4)); /* too long */
    assert(!wp_hex_decode("00ff10Ag", k, 4));   /* not hex */
    assert(!wp_hex_decode("", k, 4));
    assert(!wp_hex_decode(NULL, k, 4));
}

static void test_report(void)
{
    /* the same inputs and expected bytes as the firmware known-answer test */
    wp_client_info_t c[2] = {
        { .mac = {1, 2, 3, 4, 5, 6},                   .rssi = -40, .age_s = 3 },
        { .mac = {0xaa, 0xbb, 0xcc, 0xdd, 0xee, 0xff}, .rssi = -71, .age_s = 125 },
    };
    static const uint8_t expect[] = {
        0x02, 0x00, 0x00, 0x00, 0x04, 0xd2, 0x05, 0xca, 0xfe, 0xf0, 0x0d, 0x02,
        1, 2, 3, 4, 5, 6, 0xd8, 0x00, 0x03,
        0xaa, 0xbb, 0xcc, 0xdd, 0xee, 0xff, 0xb9, 0x00, 0x7d,
    };
    uint8_t out[64];
    size_t n = wp_report_pack(out, sizeof(out), 1234, 5, 0xCAFEF00D, c, 2);
    assert(n == sizeof(expect) && !memcmp(out, expect, n));

    assert(wp_report_pack(out, n - 1, 1234, 5, 0xCAFEF00D, c, 2) == 0); /* buffer too small */
    assert(wp_report_pack(out, sizeof(out), 0, 0, 0, c, 0) == WP_REPORT_HDR_LEN);

    /* age saturates instead of wrapping */
    c[0].age_s = 100000;
    wp_report_pack(out, sizeof(out), 0, 0, 0, c, 1);
    assert(out[WP_REPORT_HDR_LEN + 7] == 0xff && out[WP_REPORT_HDR_LEN + 8] == 0xff);
}

static void test_fragments(void)
{
    uint8_t msg[200], chunk[64], rebuilt[200];
    for (size_t i = 0; i < sizeof(msg); i++) msg[i] = (uint8_t)(i * 7);

    for (size_t per = 5; per <= 60; per += 11) {
        for (size_t len = 0; len <= sizeof(msg); len += 17) {
            size_t count = wp_frag_count(len, per);
            if (count > 128) {
                assert(wp_frag_build(msg, len, per, 0, chunk) == 0);
                continue;
            }
            size_t got = 0;
            for (size_t seq = 0; seq < count; seq++) {
                size_t cl = wp_frag_build(msg, len, per, seq, chunk);
                assert(cl >= 1 && cl <= 1 + per);
                assert((chunk[0] & 0x7f) == seq);
                assert(((chunk[0] & 0x80) != 0) == (seq == count - 1));
                memcpy(rebuilt + got, chunk + 1, cl - 1);
                got += cl - 1;
            }
            assert(got == len && !memcmp(rebuilt, msg, len));
            assert(wp_frag_build(msg, len, per, count, chunk) == 0); /* past the end */
        }
    }
    assert(wp_frag_count(10, 0) == 0);
    assert(wp_frag_build(msg, 10, 0, 0, chunk) == 0);
    /* exactly 128 fragments fit, 129 do not (7-bit sequence number) */
    assert(wp_frag_build(msg, 128, 1, 127, chunk) == 2);
    assert(wp_frag_build(msg, 129, 1, 0, chunk) == 0);
}

static void test_reassembler(void)
{
    uint8_t msg[100], chunk[48], store[100];
    for (size_t i = 0; i < sizeof(msg); i++) msg[i] = (uint8_t)(i * 13 + 1);

    /* every message split by wp_frag_build comes back out whole */
    for (size_t per = 1; per <= 40; per += 3) {
        for (size_t len = 1; len <= sizeof(msg); len += 9) {
            size_t count = wp_frag_count(len, per);
            if (count > 128) continue;
            wp_reasm_t r;
            wp_reasm_init(&r, store, sizeof(store));
            for (size_t seq = 0; seq < count; seq++) {
                size_t cl = wp_frag_build(msg, len, per, seq, chunk);
                int rc = wp_reasm_feed(&r, chunk, cl);
                assert(rc == (seq == count - 1 ? WP_REASM_DONE : WP_REASM_MORE));
            }
            assert(r.len == len && !memcmp(store, msg, len));
        }
    }

    wp_reasm_t r;
    wp_reasm_init(&r, store, 10);
    const uint8_t f0[] = { 0x00, 1, 2, 3, 4, 5 }, f1[] = { 0x01, 6, 7, 8, 9, 10 },
                  f2[] = { 0x82, 11 }, skip[] = { 0x02, 1 }, empty[] = { 0 };
    assert(wp_reasm_feed(&r, f0, sizeof(f0)) == WP_REASM_MORE);
    assert(wp_reasm_feed(&r, skip, sizeof(skip)) == WP_REASM_ERR);   /* gap: starts over */
    assert(wp_reasm_feed(&r, f1, sizeof(f1)) == WP_REASM_ERR);       /* wanted fragment 0 */
    assert(wp_reasm_feed(&r, f0, sizeof(f0)) == WP_REASM_MORE);
    assert(wp_reasm_feed(&r, f1, sizeof(f1)) == WP_REASM_MORE);
    assert(wp_reasm_feed(&r, f2, sizeof(f2)) == WP_REASM_ERR);       /* 11 bytes > capacity 10 */
    assert(wp_reasm_feed(&r, empty, 0) == WP_REASM_ERR);
    const uint8_t single[] = { 0x80, 42 };
    assert(wp_reasm_feed(&r, single, sizeof(single)) == WP_REASM_DONE && r.len == 1 && store[0] == 42);
}

static wp_config_t sample_config(void)
{
    wp_config_t c;
    wp_config_defaults(&c);
    c.band = WP_BAND_5G;
    strcpy(c.country, "AT");
    c.scan_dwell_ms = 300;
    c.hop_ms = 1500;
    c.rescan_s = 900;
    c.min_frames = 4;
    c.hold_s = 600;
    c.min_rssi = -85;
    c.ssid_count = 2;
    strcpy(c.ssids[0], "MyNet");
    strcpy(c.ssids[1], "Gäste");
    return c;
}

static void test_config(void)
{
    uint8_t blob[WP_CFG_BLOB_MAX];
    wp_config_t c = sample_config(), d;

    /* the same bytes test_protocol.py builds independently */
    static const uint8_t expect[] = {
        0x01, 0x02, 'A', 'T', 0x01, 0x2c, 0x05, 0xdc, 0x03, 0x84, 0x04, 0x02, 0x58, 0xab, 0x02,
        5, 'M', 'y', 'N', 'e', 't',
        6, 'G', 0xc3, 0xa4, 's', 't', 'e',
    };
    size_t n = wp_config_encode(&c, blob, sizeof(blob));
    assert(n == sizeof(expect) && !memcmp(blob, expect, n));

    assert(wp_config_decode(blob, n, &d));
    assert(d.band == c.band && !strcmp(d.country, "AT") && d.scan_dwell_ms == 300 &&
           d.hop_ms == 1500 && d.rescan_s == 900 && d.min_frames == 4 && d.hold_s == 600 &&
           d.min_rssi == -85 && d.ssid_count == 2 && !strcmp(d.ssids[1], "Gäste"));

    /* defaults: no SSIDs, valid, round-trips */
    wp_config_defaults(&d);
    assert(d.ssid_count == 0 && wp_config_valid(&d));
    n = wp_config_encode(&d, blob, sizeof(blob));
    assert(n == WP_CFG_HDR_LEN && wp_config_decode(blob, n, &d));

    /* the standard CRC-32 check value */
    assert(wp_crc32((const uint8_t *)"123456789", 9) == 0xCBF43926u);
    assert(wp_crc32((const uint8_t *)"", 0) == 0);

    /* limits are enforced on both encode and decode */
    for (int k = 0; k < 9; k++) {
        c = sample_config();
        switch (k) {
        case 0: c.band = 3; break;
        case 1: c.country[0] = 'a'; break;
        case 2: c.scan_dwell_ms = WP_CFG_SCAN_DWELL_MIN - 1; break;
        case 3: c.hop_ms = WP_CFG_HOP_MAX + 1; break;
        case 4: c.rescan_s = 5; break;
        case 5: c.min_frames = 0; break;
        case 6: c.hold_s = 0; break;
        case 7: c.min_rssi = 0; break;
        case 8: c.ssids[0][0] = '\0'; break; /* empty SSID */
        }
        assert(!wp_config_valid(&c) && wp_config_encode(&c, blob, sizeof(blob)) == 0);
    }
    c = sample_config();
    c.ssid_count = 9;
    assert(!wp_config_valid(&c));
    memset(c.ssids[0], 'x', 33); /* 33 characters, no terminator inside the field */
    c.ssid_count = 1;
    assert(!wp_config_valid(&c));
    c = sample_config();
    assert(wp_config_encode(&c, blob, 10) == 0); /* buffer too small */

    /* a hostile blob: every truncation, trailing bytes, an embedded NUL, bad count */
    c = sample_config();
    n = wp_config_encode(&c, blob, sizeof(blob));
    for (size_t cut = 0; cut < n; cut++) assert(!wp_config_decode(blob, cut, &d));
    blob[n] = 0;
    assert(!wp_config_decode(blob, n + 1, &d));
    uint8_t bad[WP_CFG_BLOB_MAX];
    memcpy(bad, blob, n);
    bad[WP_CFG_HDR_LEN + 2] = 0; /* NUL inside "MyNet" */
    assert(!wp_config_decode(bad, n, &d));
    memcpy(bad, blob, n);
    bad[14] = 3; /* claims three SSIDs, has two */
    assert(!wp_config_decode(bad, n, &d));
    bad[14] = 200;
    assert(!wp_config_decode(bad, n, &d));
    memcpy(bad, blob, n);
    bad[0] = 2; /* unknown version */
    assert(!wp_config_decode(bad, n, &d));

    /* a maximal config fits the advertised blob size */
    c = sample_config();
    c.ssid_count = WP_CFG_MAX_SSIDS;
    for (int i = 0; i < WP_CFG_MAX_SSIDS; i++) { memset(c.ssids[i], 'a' + i, 32); c.ssids[i][32] = 0; }
    n = wp_config_encode(&c, blob, sizeof(blob));
    assert(n == WP_CFG_BLOB_MAX && wp_config_decode(blob, n, &d));
}

int main(void)
{
    test_frames();
    test_mac();
    test_hex();
    test_report();
    test_fragments();
    test_reassembler();
    test_config();
    puts("all host tests passed");
    return 0;
}
