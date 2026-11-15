#pragma once

#include <stdbool.h>
#include <stdint.h>

/*
 * What the status LED shows, as pure functions of time (no hardware, so the
 * host tests cover it). One LED, two messages:
 *
 *   WAITING    firmware is running, no live Home Assistant connection: 1 Hz blink
 *   CONNECTED  Home Assistant polled recently: steady on
 *   (OFF       before the firmware has finished starting)
 *
 * Activity (an exchange with Home Assistant, heard Wi-Fi traffic) switches a
 * steady LED off for a moment: a flash that is easy to see and never leaves the
 * LED dark for long.
 */

#define WP_LED_BLINK_PERIOD_MS 1000  /* WAITING: 500 ms on, 500 ms off */
#define WP_LED_PULSE_MS        80    /* activity flash: LED off this long */
#define WP_LED_PULSE_GAP_MS    400   /* at most one flash per this time */
#define WP_LED_ALIVE_MIN_MS    90000   /* a poll counts as "alive" at least this long */
#define WP_LED_ALIVE_MAX_MS    900000  /* ... and never longer than this */

typedef enum {
    WP_LED_OFF = 0,
    WP_LED_WAITING,
    WP_LED_CONNECTED,
} wp_led_mode_t;

/**
 * How long after a poll Home Assistant still counts as connected: 2.5 times the
 * interval between its last two polls (so a slow polling period does not make
 * the LED blink between polls), between ALIVE_MIN and ALIVE_MAX. 0 = unknown.
 */
uint32_t wp_led_alive_window(uint32_t poll_interval_ms);

/** The mode for this moment. Times are milliseconds on a free-running 32-bit clock. */
wp_led_mode_t wp_led_mode(bool running, bool paired, bool polled_ever, uint32_t now_ms,
                          uint32_t last_poll_ms, uint32_t poll_interval_ms);

/** True if an activity flash may start now (rate limit). */
bool wp_led_pulse_allowed(uint32_t now_ms, uint32_t last_pulse_ms, bool pulse_ever);

/** Logical LED state (true = lit) at `now_ms`. */
bool wp_led_level(wp_led_mode_t mode, uint32_t now_ms, uint32_t last_pulse_ms, bool pulse_ever);
