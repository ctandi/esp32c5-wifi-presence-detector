#pragma once

#include <stdbool.h>

/**
 * Start NimBLE as a GATT server (see PROTOCOL.md). Home Assistant connects,
 * sends a random challenge and receives the current client list as one
 * AES-256-GCM message; it can then send sealed commands (new settings).
 * Nothing about the clients is ever advertised.
 *
 * Needs the pairing key: call wp_store_ensure_key() first.
 */
void wp_gatt_start(void);

/** The sensor's Bluetooth address as "AA:BB:CC:DD:EE:FF", once the stack is up. */
bool wp_gatt_address(char out[18]);
