#include <stdio.h>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"
#include "sdkconfig.h"

#include "presence.h"
#include "wifi_sniffer.h"
#include "wp_crypto.h"
#include "wp_gatt.h"
#include "wp_led.h"
#include "wp_report.h"
#include "wp_store.h"

static const char *TAG = "main";

#define STATUS_PERIOD_S   30
#define PAIRING_PERIOD_S  10 /* repeat the pairing key this often until Home Assistant has paired */

#if CONFIG_WP_SELFTEST_KAT
/* Known-answer test: fixed key, nonces and clients. test/check_kat.py computes
 * the same message independently in Python and compares it with this output. */
static void print_kat(void)
{
    uint8_t psk[WP_PSK_LEN], cn[WP_NONCE_LEN], dn[WP_NONCE_LEN];
    for (int i = 0; i < WP_PSK_LEN; i++) psk[i] = (uint8_t)i;
    for (int i = 0; i < WP_NONCE_LEN; i++) { cn[i] = (uint8_t)(0x10 + i); dn[i] = (uint8_t)(0x20 + i); }

    wp_client_info_t c[2] = {
        { .mac = {1, 2, 3, 4, 5, 6},                      .rssi = -40, .age_s = 3 },
        { .mac = {0xaa, 0xbb, 0xcc, 0xdd, 0xee, 0xff},    .rssi = -71, .age_s = 125 },
    };
    uint8_t plain[WP_REPORT_MAX_LEN(2)], msg[WP_REPORT_MAX_LEN(2) + WP_MSG_OVERHEAD];
    size_t plen = wp_report_pack(plain, sizeof(plain), 1234, 5, 0xCAFEF00D, c, 2);
    uint8_t key[WP_KEY_LEN];
    size_t mlen = wp_seal(psk, cn, dn, plain, plen, msg, key);

    printf("KAT_PLAIN ");
    for (size_t i = 0; i < plen; i++) printf("%02x", plain[i]);
    printf("\nKAT_MSG ");
    for (size_t i = 0; i < mlen; i++) printf("%02x", msg[i]);
    printf("\n");
}
#endif

/* The key and address Home Assistant asks for. Plain printf, no log prefix, so
 * the key can be selected and copied from the web flasher's console. */
static void print_pairing(void)
{
    char key[WP_PSK_LEN * 2 + 1];
    char addr[18] = "(starting)";
    wp_store_psk_hex(key);
    wp_gatt_address(addr);

    printf("\n"
           "==================== WI-FI PRESENCE SENSOR: PAIRING ====================\n"
           " In Home Assistant: Settings > Devices & services > Wi-Fi Presence Sensor\n"
           " (it is found automatically through Bluetooth) and enter this key:\n"
           "\n"
           "%s\n"
           "\n"
           " Bluetooth address: %s\n"
           "========================================================================\n\n",
           key, addr);
}

void app_main(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);

#if CONFIG_WP_SELFTEST_KAT
    print_kat();
#endif

    wp_store_init();
    wp_presence_init();
    wp_sniffer_start(); /* Wi-Fi is up from here: the hardware RNG is now a true one */
    if (!wp_store_ensure_key()) {
        ESP_LOGE(TAG, "no pairing key, Bluetooth stays off");
        vTaskDelay(portMAX_DELAY);
    }
    wp_gatt_start();

    vTaskDelay(pdMS_TO_TICKS(1500)); /* let Bluetooth report its address */
    print_pairing();
    wp_led_start(); /* everything is up: the LED now says "firmware is running" */

    static wp_client_info_t list[CONFIG_WP_MAX_DEVICES];
    uint32_t elapsed = 0;
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(PAIRING_PERIOD_S * 1000));
        elapsed += PAIRING_PERIOD_S;
        if (!wp_store_paired()) {
            print_pairing();
        }
        if (elapsed % STATUS_PERIOD_S == 0) {
            size_t n = wp_presence_snapshot(list, CONFIG_WP_MAX_DEVICES);
            ESP_LOGI(TAG, "%u client(s) present, %s", (unsigned)n,
                     wp_store_paired() ? "paired with Home Assistant" : "waiting for pairing");
        }
    }
}
