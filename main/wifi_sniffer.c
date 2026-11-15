#include "wifi_sniffer.h"

#include <stdbool.h>
#include <stdlib.h>
#include <string.h>

#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/portmacro.h"
#include "freertos/task.h"
#include "sdkconfig.h"

#include "frame_parse.h"
#include "presence.h"
#include "wp_store.h"

static const char *TAG = "sniffer";

#define MAX_TARGETS       16
#define MAX_SCAN_RECORDS  48
#define MISSES_BEFORE_DROP 3  /* one missed beacon must not forget an AP */
#define NO_TARGET_RETRY_S 30

typedef struct {
    bool                used;
    uint8_t             bssid[6];
    uint8_t             channel;
    wifi_second_chan_t  second;
    uint8_t             misses;
    char                ssid[33];
} target_t;

typedef struct {
    uint8_t            channel;
    wifi_second_chan_t second;
} chan_t;

static wp_config_t  s_cfg; /* the settings in force; touched by the sniffer task only */
static target_t     s_targets[MAX_TARGETS];
static portMUX_TYPE s_lock = portMUX_INITIALIZER_UNLOCKED;
static TaskHandle_t s_task;

/* ---- configuration ------------------------------------------------------ */

static bool ssid_wanted(const uint8_t *ssid)
{
    for (size_t i = 0; i < s_cfg.ssid_count; i++) {
        if (strcmp(s_cfg.ssids[i], (const char *)ssid) == 0) {
            return true;
        }
    }
    return false;
}

void wp_sniffer_config_changed(void)
{
    if (s_task) {
        xTaskNotifyGive(s_task);
    }
}

/** Forget all APs: the SSID list may have changed, the next scan refills it. */
static void clear_targets(void)
{
    portENTER_CRITICAL(&s_lock);
    memset(s_targets, 0, sizeof(s_targets));
    portEXIT_CRITICAL(&s_lock);
}

/** Push the settings into Wi-Fi and the presence table. */
static void apply_config(void)
{
    static char applied_country[3];

    wp_presence_set_params(s_cfg.min_frames, s_cfg.hold_s, s_cfg.min_rssi);

    wifi_band_mode_t band = WIFI_BAND_MODE_AUTO;
    if (s_cfg.band == WP_BAND_2G) band = WIFI_BAND_MODE_2G_ONLY;
    if (s_cfg.band == WP_BAND_5G) band = WIFI_BAND_MODE_5G_ONLY;
    esp_err_t err = esp_wifi_set_band_mode(band);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "set_band_mode: %s", esp_err_to_name(err));
    }
    if (strcmp(applied_country, s_cfg.country) != 0) {
        err = esp_wifi_set_country_code(s_cfg.country, false);
        if (err == ESP_OK) {
            strcpy(applied_country, s_cfg.country);
        } else {
            ESP_LOGW(TAG, "set_country_code(%s): %s", s_cfg.country, esp_err_to_name(err));
        }
    }
}

/* ---- target list -------------------------------------------------------- */

static bool is_target_bssid(const uint8_t bssid[6])
{
    bool found = false;
    portENTER_CRITICAL(&s_lock);
    for (size_t i = 0; i < MAX_TARGETS; i++) {
        if (s_targets[i].used && memcmp(s_targets[i].bssid, bssid, 6) == 0) {
            found = true;
            break;
        }
    }
    portEXIT_CRITICAL(&s_lock);
    return found;
}

size_t wp_sniffer_target_count(void)
{
    size_t n = 0;
    portENTER_CRITICAL(&s_lock);
    for (size_t i = 0; i < MAX_TARGETS; i++) {
        n += s_targets[i].used;
    }
    portEXIT_CRITICAL(&s_lock);
    return n;
}

/** Merge one scan result set into the target list. */
static void merge_scan(const wifi_ap_record_t *recs, uint16_t n)
{
    portENTER_CRITICAL(&s_lock);
    for (size_t i = 0; i < MAX_TARGETS; i++) {
        if (s_targets[i].used) {
            s_targets[i].misses++;
        }
    }
    for (uint16_t r = 0; r < n; r++) {
        if (!ssid_wanted(recs[r].ssid)) {
            continue;
        }
        target_t *slot = NULL;
        for (size_t i = 0; i < MAX_TARGETS; i++) {
            if (s_targets[i].used && memcmp(s_targets[i].bssid, recs[r].bssid, 6) == 0) {
                slot = &s_targets[i];
                break;
            }
            if (!slot && !s_targets[i].used) {
                slot = &s_targets[i];
            }
        }
        if (!slot) {
            continue; /* list full */
        }
        slot->used = true;
        memcpy(slot->bssid, recs[r].bssid, 6);
        slot->channel = recs[r].primary;
        slot->second = recs[r].second;
        slot->misses = 0;
        strncpy(slot->ssid, (const char *)recs[r].ssid, sizeof(slot->ssid) - 1);
    }
    for (size_t i = 0; i < MAX_TARGETS; i++) {
        if (s_targets[i].used && s_targets[i].misses >= MISSES_BEFORE_DROP) {
            s_targets[i].used = false;
        }
    }
    portEXIT_CRITICAL(&s_lock);
}

/** Distinct (primary, secondary) channel pairs of all targets. */
static size_t build_channel_list(chan_t out[MAX_TARGETS])
{
    size_t n = 0;
    portENTER_CRITICAL(&s_lock);
    for (size_t i = 0; i < MAX_TARGETS; i++) {
        if (!s_targets[i].used) {
            continue;
        }
        bool dup = false;
        for (size_t k = 0; k < n; k++) {
            if (out[k].channel == s_targets[i].channel && out[k].second == s_targets[i].second) {
                dup = true;
                break;
            }
        }
        if (!dup) {
            out[n].channel = s_targets[i].channel;
            out[n].second = s_targets[i].second;
            n++;
        }
    }
    portEXIT_CRITICAL(&s_lock);
    return n;
}

static void log_targets(void)
{
    for (size_t i = 0; i < MAX_TARGETS; i++) {
        const target_t *t = &s_targets[i];
        if (t->used) {
            ESP_LOGI(TAG, "AP '%s' %02x:%02x:%02x:%02x:%02x:%02x on channel %u%s",
                     t->ssid, t->bssid[0], t->bssid[1], t->bssid[2], t->bssid[3],
                     t->bssid[4], t->bssid[5], t->channel,
                     t->second == WIFI_SECOND_CHAN_ABOVE ? "+" :
                     t->second == WIFI_SECOND_CHAN_BELOW ? "-" : "");
        }
    }
}

/* ---- scanning ----------------------------------------------------------- */

static void scan_for_targets(void)
{
    esp_wifi_set_promiscuous(false);

    wifi_scan_config_t cfg = {
        .show_hidden = false,
        .scan_type = WIFI_SCAN_TYPE_PASSIVE,
        .scan_time.passive = s_cfg.scan_dwell_ms,
    };
    esp_err_t err = esp_wifi_scan_start(&cfg, true);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "scan failed: %s", esp_err_to_name(err));
        return;
    }

    uint16_t n = MAX_SCAN_RECORDS;
    wifi_ap_record_t *recs = calloc(n, sizeof(*recs));
    if (!recs) {
        esp_wifi_clear_ap_list();
        return;
    }
    if (esp_wifi_scan_get_ap_records(&n, recs) == ESP_OK) {
        merge_scan(recs, n);
        ESP_LOGI(TAG, "scan saw %u APs", n);
    }
    free(recs);
    log_targets();
}

/* ---- sniffing ----------------------------------------------------------- */

static void sniffer_cb(void *buf, wifi_promiscuous_pkt_type_t type)
{
    if (type != WIFI_PKT_DATA) {
        return;
    }
    const wifi_promiscuous_pkt_t *pkt = buf;
    uint8_t sta[6], bssid[6];

    if (!wp_parse_data_frame(pkt->payload, pkt->rx_ctrl.sig_len, sta, bssid)) {
        return;
    }
    if (!is_target_bssid(bssid) || is_target_bssid(sta)) {
        return; /* other network, or AP-to-AP traffic of a mesh */
    }
    wp_presence_seen(sta, pkt->rx_ctrl.rssi);
}

/** Sniff for `seconds`, or until new settings arrive. Returns true in that case. */
static bool sniff_window(const chan_t *chans, size_t n_chans, uint32_t seconds)
{
    wifi_promiscuous_filter_t filter = { .filter_mask = WIFI_PROMIS_FILTER_MASK_DATA };
    esp_wifi_set_promiscuous_filter(&filter);
    esp_wifi_set_promiscuous_rx_cb(sniffer_cb);
    esp_wifi_set_promiscuous(true);

    bool changed = false;
    const int64_t end_us = esp_timer_get_time() + (int64_t)seconds * 1000000;
    size_t idx = 0;
    for (;;) {
        const int64_t left_us = end_us - esp_timer_get_time();
        if (left_us <= 0) {
            break;
        }
        const chan_t *c = &chans[idx % n_chans];
        esp_wifi_set_channel(c->channel, c->second);

        uint32_t dwell_ms = (uint32_t)(left_us / 1000);
        if (n_chans > 1 && dwell_ms > s_cfg.hop_ms) {
            dwell_ms = s_cfg.hop_ms;
        }
        if (ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(dwell_ms)) > 0) {
            changed = true;
            break;
        }
        idx++;
    }
    esp_wifi_set_promiscuous(false);
    return changed;
}

static void sniffer_task(void *arg)
{
    bool reconfigured = false;
    for (;;) {
        /* A pending notification means new settings: take them and start over. */
        if (ulTaskNotifyTake(pdTRUE, 0) > 0 || reconfigured) {
            clear_targets();
            reconfigured = false;
        }
        wp_config_get(&s_cfg);
        apply_config();

        if (s_cfg.ssid_count == 0) {
            ESP_LOGW(TAG, "no SSID configured yet, waiting for settings from Home Assistant");
            ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
            reconfigured = true;
            continue;
        }

        scan_for_targets();

        chan_t chans[MAX_TARGETS];
        size_t n = build_channel_list(chans);
        if (n == 0) {
            ESP_LOGW(TAG, "none of the watched SSIDs found, retrying in %d s", NO_TARGET_RETRY_S);
            reconfigured = ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(NO_TARGET_RETRY_S * 1000)) > 0;
            continue;
        }
        ESP_LOGI(TAG, "sniffing %u channel(s) for %u s", (unsigned)n, (unsigned)s_cfg.rescan_s);
        reconfigured = sniff_window(chans, n, s_cfg.rescan_s);
    }
}

/* ---- start-up ----------------------------------------------------------- */

void wp_sniffer_start(void)
{
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());

    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_start());

    wp_store_on_config_change(wp_sniffer_config_changed);
    xTaskCreate(sniffer_task, "wp_sniffer", 4096, NULL, 5, &s_task);
}
