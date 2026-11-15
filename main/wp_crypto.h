#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define WP_PSK_LEN     32
#define WP_NONCE_LEN   16
#define WP_TAG_LEN     16
#define WP_KEY_LEN     32
#define WP_MSG_VERSION 0x01
/** report message = version(1) || dev_nonce(16) || ciphertext || tag(16) */
#define WP_MSG_OVERHEAD (1 + WP_NONCE_LEN + WP_TAG_LEN)
/** command/ack message = version(1) || counter(4) || ciphertext || tag(16) */
#define WP_CMSG_HDR_LEN  5
#define WP_CMSG_OVERHEAD (WP_CMSG_HDR_LEN + WP_TAG_LEN)

/** Direction byte of the GCM nonce. */
#define WP_DIR_DEVICE_TO_CLIENT 0
#define WP_DIR_CLIENT_TO_DEVICE 1

/**
 * Session key, unique per request/response pair (see PROTOCOL.md):
 *   HMAC-SHA256(psk, "wifi-presence v1 session" || client_nonce || dev_nonce)
 */
bool wp_derive_key(const uint8_t psk[WP_PSK_LEN],
                   const uint8_t client_nonce[WP_NONCE_LEN],
                   const uint8_t dev_nonce[WP_NONCE_LEN],
                   uint8_t key[WP_KEY_LEN]);

/** GCM nonce: direction byte, 7 zero bytes, 32-bit big-endian counter. */
void wp_make_iv(uint8_t dir, uint32_t counter, uint8_t iv[12]);

/** AES-256-GCM. `out` receives plain_len + WP_TAG_LEN bytes (ciphertext || tag). */
bool wp_gcm_seal(const uint8_t key[WP_KEY_LEN], const uint8_t iv[12],
                 const uint8_t *aad, size_t aad_len,
                 const uint8_t *plain, size_t plain_len, uint8_t *out);

/** Inverse: `in` is ciphertext || tag (in_len >= 16), `out` gets in_len - 16 bytes. */
bool wp_gcm_open(const uint8_t key[WP_KEY_LEN], const uint8_t iv[12],
                 const uint8_t *aad, size_t aad_len,
                 const uint8_t *in, size_t in_len, uint8_t *out);

/**
 * Seal one report: derive the key, then
 *   message = 0x01 || dev_nonce || AES-256-GCM(key, iv(0, 0), aad = first 17 bytes, plain) || tag
 *
 * `out` needs plain_len + WP_MSG_OVERHEAD bytes. Returns the message length, or
 * 0 on failure. The key is stored in `key_out` so the session can go on with
 * commands. dev_nonce must be fresh random bytes every time.
 */
size_t wp_seal(const uint8_t psk[WP_PSK_LEN],
               const uint8_t client_nonce[WP_NONCE_LEN],
               const uint8_t dev_nonce[WP_NONCE_LEN],
               const uint8_t *plain, size_t plain_len, uint8_t *out,
               uint8_t key_out[WP_KEY_LEN]);
