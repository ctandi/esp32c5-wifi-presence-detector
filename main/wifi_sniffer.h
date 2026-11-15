#pragma once

#include <stddef.h>

/**
 * Bring up Wi-Fi (never connecting) and start the task that
 *   1. scans for the BSSIDs and channels of the configured SSIDs,
 *   2. sniffs data frames on those channels, hopping when there are several,
 *   3. feeds every client it sees into the presence table,
 * then rescans as often as the settings say. With no SSID configured it idles
 * until settings arrive (wp_store.h). Call wp_store_init() first.
 */
void wp_sniffer_start(void);

/** Number of access point BSSIDs currently being watched. */
size_t wp_sniffer_target_count(void);

/** New settings were stored: stop what the task is doing and start over with them. */
void wp_sniffer_config_changed(void);
