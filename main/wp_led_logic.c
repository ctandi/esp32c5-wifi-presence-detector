#include "wp_led_logic.h"

/* All differences are unsigned, so they stay correct when the 32-bit clock wraps. */

uint32_t wp_led_alive_window(uint32_t poll_interval_ms)
{
    uint64_t w = (uint64_t)poll_interval_ms * 5 / 2;
    if (w < WP_LED_ALIVE_MIN_MS) {
        w = WP_LED_ALIVE_MIN_MS;
    }
    if (w > WP_LED_ALIVE_MAX_MS) {
        w = WP_LED_ALIVE_MAX_MS;
    }
    return (uint32_t)w;
}

wp_led_mode_t wp_led_mode(bool running, bool paired, bool polled_ever, uint32_t now_ms,
                          uint32_t last_poll_ms, uint32_t poll_interval_ms)
{
    if (!running) {
        return WP_LED_OFF;
    }
    if (paired && polled_ever &&
        (uint32_t)(now_ms - last_poll_ms) < wp_led_alive_window(poll_interval_ms)) {
        return WP_LED_CONNECTED;
    }
    return WP_LED_WAITING;
}

bool wp_led_pulse_allowed(uint32_t now_ms, uint32_t last_pulse_ms, bool pulse_ever)
{
    return !pulse_ever || (uint32_t)(now_ms - last_pulse_ms) >= WP_LED_PULSE_GAP_MS;
}

bool wp_led_level(wp_led_mode_t mode, uint32_t now_ms, uint32_t last_pulse_ms, bool pulse_ever)
{
    switch (mode) {
    case WP_LED_CONNECTED:
        return !(pulse_ever && (uint32_t)(now_ms - last_pulse_ms) < WP_LED_PULSE_MS);
    case WP_LED_WAITING:
        return (now_ms % WP_LED_BLINK_PERIOD_MS) < WP_LED_BLINK_PERIOD_MS / 2;
    default:
        return false;
    }
}
