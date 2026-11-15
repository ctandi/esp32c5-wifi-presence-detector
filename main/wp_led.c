#include "wp_led.h"

#include <stdbool.h>

#include "sdkconfig.h"

#if CONFIG_WP_LED_ENABLE

#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "wp_led_logic.h"
#include "wp_store.h"

static const char *TAG = "led";

#define ON_LEVEL  (CONFIG_WP_LED_ACTIVE_LOW ? 0 : 1)
#define OFF_LEVEL (CONFIG_WP_LED_ACTIVE_LOW ? 1 : 0)

static volatile bool     s_running;
static volatile bool     s_poll_valid;
static volatile bool     s_pulse_valid;
static volatile uint32_t s_last_poll_ms;
static volatile uint32_t s_last_pulse_ms;
static volatile uint32_t s_poll_interval_ms;

static uint32_t now_ms(void)
{
    return (uint32_t)(esp_timer_get_time() / 1000);
}

void wp_led_activity(void)
{
    const uint32_t now = now_ms();
    if (wp_led_pulse_allowed(now, s_last_pulse_ms, s_pulse_valid)) {
        s_last_pulse_ms = now;
        s_pulse_valid = true;
    }
}

void wp_led_poll_done(void)
{
    const uint32_t now = now_ms();
    if (s_poll_valid) {
        const uint32_t gap = now - s_last_poll_ms;
        if (gap <= WP_LED_ALIVE_MAX_MS) {
            s_poll_interval_ms = gap; /* learn Home Assistant's polling period */
        }
    }
    s_last_poll_ms = now;
    s_poll_valid = true;
    wp_led_activity();
}

static void led_task(void *arg)
{
    for (;;) {
        const uint32_t now = now_ms();
        const wp_led_mode_t mode = wp_led_mode(s_running, wp_store_paired(), s_poll_valid, now,
                                               s_last_poll_ms, s_poll_interval_ms);
        const bool on = wp_led_level(mode, now, s_last_pulse_ms, s_pulse_valid);
        gpio_set_level(CONFIG_WP_LED_GPIO, on ? ON_LEVEL : OFF_LEVEL);
        vTaskDelay(pdMS_TO_TICKS(20));
    }
}

void wp_led_start(void)
{
    const gpio_config_t io = {
        .pin_bit_mask = 1ULL << CONFIG_WP_LED_GPIO,
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    if (gpio_config(&io) != ESP_OK) {
        ESP_LOGW(TAG, "GPIO%d is not usable as the status LED", CONFIG_WP_LED_GPIO);
        return;
    }
    gpio_set_level(CONFIG_WP_LED_GPIO, OFF_LEVEL);
    s_running = true;
    xTaskCreate(led_task, "wp_led", 2048, NULL, 2, NULL);
    ESP_LOGI(TAG, "status LED on GPIO%d (active %s)", CONFIG_WP_LED_GPIO,
             CONFIG_WP_LED_ACTIVE_LOW ? "low" : "high");
}

#else /* LED disabled in the build: do nothing */

void wp_led_start(void) {}
void wp_led_poll_done(void) {}
void wp_led_activity(void) {}

#endif
