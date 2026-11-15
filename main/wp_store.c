#include "wp_store.h"

#include <string.h>

#include "esp_log.h"
#include "esp_random.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "nvs.h"

static const char *TAG = "store";

#define NVS_NS   "wp"
#define KEY_PSK  "psk"
#define KEY_CFG  "cfg"
#define KEY_PAIR "paired"

static SemaphoreHandle_t s_mutex;
static uint8_t  s_psk[WP_PSK_LEN];
static bool     s_have_psk;
static bool     s_paired;
static wp_config_t s_cfg;
static uint8_t  s_blob[WP_CFG_BLOB_MAX];
static size_t   s_blob_len;
static void   (*s_on_change)(void);

static bool nvs_put_blob(const char *key, const void *data, size_t len)
{
    nvs_handle_t h;
    if (nvs_open(NVS_NS, NVS_READWRITE, &h) != ESP_OK) {
        return false;
    }
    esp_err_t err = nvs_set_blob(h, key, data, len);
    if (err == ESP_OK) {
        err = nvs_commit(h);
    }
    nvs_close(h);
    return err == ESP_OK;
}

void wp_store_init(void)
{
    s_mutex = xSemaphoreCreateMutex();
    wp_config_defaults(&s_cfg);

    nvs_handle_t h;
    if (nvs_open(NVS_NS, NVS_READONLY, &h) != ESP_OK) {
        return; /* first boot: nothing stored yet */
    }

    size_t n = sizeof(s_psk);
    if (nvs_get_blob(h, KEY_PSK, s_psk, &n) == ESP_OK && n == WP_PSK_LEN) {
        s_have_psk = true;
    }

    uint8_t blob[WP_CFG_BLOB_MAX];
    n = sizeof(blob);
    wp_config_t cfg;
    if (nvs_get_blob(h, KEY_CFG, blob, &n) == ESP_OK && wp_config_decode(blob, n, &cfg)) {
        s_cfg = cfg;
        memcpy(s_blob, blob, n);
        s_blob_len = n;
    }

    uint8_t paired = 0;
    if (nvs_get_u8(h, KEY_PAIR, &paired) == ESP_OK) {
        s_paired = paired != 0;
    }
    nvs_close(h);
}

bool wp_store_ensure_key(void)
{
    if (s_have_psk) {
        return true;
    }
    esp_fill_random(s_psk, sizeof(s_psk));
    if (!nvs_put_blob(KEY_PSK, s_psk, sizeof(s_psk))) {
        memset(s_psk, 0, sizeof(s_psk));
        ESP_LOGE(TAG, "could not store the key");
        return false;
    }
    s_have_psk = true;
    ESP_LOGI(TAG, "generated a new pairing key");
    return true;
}

const uint8_t *wp_store_psk(void)
{
    return s_psk;
}

void wp_store_psk_hex(char out[WP_PSK_LEN * 2 + 1])
{
    static const char HEX[] = "0123456789abcdef";
    for (size_t i = 0; i < WP_PSK_LEN; i++) {
        out[2 * i] = HEX[s_psk[i] >> 4];
        out[2 * i + 1] = HEX[s_psk[i] & 15];
    }
    out[WP_PSK_LEN * 2] = '\0';
}

void wp_config_get(wp_config_t *out)
{
    xSemaphoreTake(s_mutex, portMAX_DELAY);
    *out = s_cfg;
    xSemaphoreGive(s_mutex);
}

uint32_t wp_config_crc(void)
{
    xSemaphoreTake(s_mutex, portMAX_DELAY);
    const uint32_t crc = s_blob_len ? wp_crc32(s_blob, s_blob_len) : 0;
    xSemaphoreGive(s_mutex);
    return crc;
}

wp_set_status_t wp_store_set_config(const uint8_t *blob, size_t len)
{
    wp_config_t cfg;
    if (len > WP_CFG_BLOB_MAX || !wp_config_decode(blob, len, &cfg)) {
        return WP_SET_INVALID;
    }

    xSemaphoreTake(s_mutex, portMAX_DELAY);
    const bool same = len == s_blob_len && memcmp(blob, s_blob, len) == 0;
    xSemaphoreGive(s_mutex);
    if (same) {
        return WP_SET_OK;
    }

    if (!nvs_put_blob(KEY_CFG, blob, len)) {
        ESP_LOGE(TAG, "could not store the settings");
        return WP_SET_STORAGE;
    }
    xSemaphoreTake(s_mutex, portMAX_DELAY);
    s_cfg = cfg;
    memcpy(s_blob, blob, len);
    s_blob_len = len;
    xSemaphoreGive(s_mutex);

    ESP_LOGI(TAG, "new settings stored: %u SSID(s)", cfg.ssid_count);
    if (s_on_change) {
        s_on_change();
    }
    return WP_SET_OK;
}

void wp_store_on_config_change(void (*callback)(void))
{
    s_on_change = callback;
}

bool wp_store_paired(void)
{
    return s_paired;
}

void wp_store_mark_paired(void)
{
    if (s_paired) {
        return;
    }
    const uint8_t one = 1;
    nvs_handle_t h;
    if (nvs_open(NVS_NS, NVS_READWRITE, &h) == ESP_OK) {
        if (nvs_set_u8(h, KEY_PAIR, one) == ESP_OK) {
            nvs_commit(h);
        }
        nvs_close(h);
    }
    s_paired = true;
    ESP_LOGI(TAG, "paired with Home Assistant");
}
