#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "wp_config.h"
#include "wp_crypto.h"

/*
 * Everything the sensor remembers across reboots, kept in NVS:
 *   - the pairing key, generated on the device at first boot,
 *   - the settings Home Assistant pushed,
 *   - whether Home Assistant has proven that it holds the key.
 */

typedef enum {
    WP_SET_OK = 0,
    WP_SET_INVALID = 1,   /* blob does not parse or a value is out of range */
    WP_SET_STORAGE = 2,   /* could not write to flash */
} wp_set_status_t;

/** Load key, settings and the paired flag. Call after nvs_flash_init(). */
void wp_store_init(void);

/**
 * Create the key if there is none yet. Call once Wi-Fi or Bluetooth is running,
 * because only then the hardware random generator is a true entropy source.
 * Returns false if no key exists and none could be stored.
 */
bool wp_store_ensure_key(void);

/** The 32-byte key (valid after wp_store_ensure_key() returned true). */
const uint8_t *wp_store_psk(void);

/** The key as 64 lower-case hex digits plus NUL. */
void wp_store_psk_hex(char out[WP_PSK_LEN * 2 + 1]);

/** Copy of the settings in force. */
void wp_config_get(wp_config_t *out);

/** CRC-32 of the stored settings blob, 0 while none was ever stored. */
uint32_t wp_config_crc(void);

/**
 * Validate, store and apply a settings blob from Home Assistant. An identical
 * blob is accepted without touching flash or restarting the scan.
 */
wp_set_status_t wp_store_set_config(const uint8_t *blob, size_t len);

/** Called (from the Bluetooth task) after new settings were stored. */
void wp_store_on_config_change(void (*callback)(void));

/** True once Home Assistant authenticated a command with the key. */
bool wp_store_paired(void);
void wp_store_mark_paired(void);
