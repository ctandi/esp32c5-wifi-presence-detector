#include "presence.h"

#include <stdbool.h>
#include <string.h>

#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/portmacro.h"
#include "sdkconfig.h"


static const char *TAG = "presence";

/* Tunable at run time (settings from Home Assistant). Plain word writes are
 * atomic on this CPU and each value is used on its own, so no lock is needed. */
static volatile uint32_t s_min_frames = 3;
static volatile uint32_t s_hold_s = 300;
static volatile int8_t   s_min_rssi = -100;

#define HOLD_US ((int64_t)s_hold_s * 1000000)

typedef struct {
    bool     used;
    uint8_t  mac[6];
    int8_t   rssi;
    uint32_t frames;
    int64_t  last_us;
} entry_t;

static entry_t s_table[CONFIG_WP_MAX_DEVICES];
static portMUX_TYPE s_lock = portMUX_INITIALIZER_UNLOCKED;
static bool s_full_warned;

void wp_presence_init(void)
{
    memset(s_table, 0, sizeof(s_table));
}

void wp_presence_set_params(uint32_t min_frames, uint32_t hold_s, int8_t min_rssi)
{
    s_min_frames = min_frames;
    s_hold_s = hold_s;
    s_min_rssi = min_rssi;
}

void wp_presence_seen(const uint8_t mac[6], int8_t rssi)
{
    if (rssi < s_min_rssi) {
        return; /* too weak: a neighbour's device, or one far outside */
    }
    const int64_t now = esp_timer_get_time();
    bool dropped = false;

    portENTER_CRITICAL(&s_lock);
    entry_t *hit = NULL;
    entry_t *free_slot = NULL;
    for (size_t i = 0; i < CONFIG_WP_MAX_DEVICES; i++) {
        entry_t *e = &s_table[i];
        if (e->used && memcmp(e->mac, mac, 6) == 0) {
            hit = e;
            break;
        }
        if (!free_slot && (!e->used || now - e->last_us > HOLD_US)) {
            free_slot = e;
        }
    }

    if (hit && now - hit->last_us > HOLD_US) {
        hit->frames = 0; /* it left and came back: start counting again */
    }
    if (!hit) {
        hit = free_slot;
        if (hit) {
            memset(hit, 0, sizeof(*hit));
            hit->used = true;
            memcpy(hit->mac, mac, 6);
        } else {
            dropped = true;
        }
    }
    if (hit) {
        hit->frames++;
        hit->rssi = rssi;
        hit->last_us = now;
    }
    portEXIT_CRITICAL(&s_lock);

    if (dropped && !s_full_warned) {
        s_full_warned = true; /* log once, never from inside the lock */
        ESP_LOGW(TAG, "client table full (%d), raise CONFIG_WP_MAX_DEVICES", CONFIG_WP_MAX_DEVICES);
    }
}

size_t wp_presence_snapshot(wp_client_info_t *out, size_t max)
{
    const int64_t now = esp_timer_get_time();
    size_t n = 0;

    portENTER_CRITICAL(&s_lock);
    for (size_t i = 0; i < CONFIG_WP_MAX_DEVICES && n < max; i++) {
        const entry_t *e = &s_table[i];
        if (!e->used || e->frames < s_min_frames || now - e->last_us > HOLD_US) {
            continue;
        }
        memcpy(out[n].mac, e->mac, 6);
        out[n].rssi = e->rssi;
        out[n].frames = e->frames;
        out[n].age_s = (uint32_t)((now - e->last_us) / 1000000);
        n++;
    }
    portEXIT_CRITICAL(&s_lock);
    return n;
}
