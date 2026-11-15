#pragma once

/*
 * Status LED (the yellow user LED of the XIAO ESP32-C5, GPIO27).
 *
 *   slow blink   firmware is running, Home Assistant is not connected
 *   steady on    Home Assistant polled recently
 *   brief flash  activity: an exchange with Home Assistant, or Wi-Fi traffic
 *
 * The red LED of that board is the battery charge indicator, wired to the charger
 * chip, so no firmware can drive it. Patterns: wp_led_logic.h.
 */

/** Call once everything else is up: from here on the LED means "firmware is running". */
void wp_led_start(void);

/** An authenticated-or-not exchange with Home Assistant just completed. */
void wp_led_poll_done(void);

/** Something happened worth a flash. Cheap, rate limited, safe from any task. */
void wp_led_activity(void);
