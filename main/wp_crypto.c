#include "wp_crypto.h"

#include <string.h>

#include "mbedtls/gcm.h"
#include "mbedtls/md.h"

static const char LABEL[] = "wifi-presence v1 session"; /* no terminating NUL is hashed */

bool wp_derive_key(const uint8_t psk[WP_PSK_LEN],
                   const uint8_t client_nonce[WP_NONCE_LEN],
                   const uint8_t dev_nonce[WP_NONCE_LEN],
                   uint8_t key[WP_KEY_LEN])
{
    uint8_t material[sizeof(LABEL) - 1 + 2 * WP_NONCE_LEN];
    size_t m = 0;

    memcpy(material, LABEL, sizeof(LABEL) - 1);
    m += sizeof(LABEL) - 1;
    memcpy(material + m, client_nonce, WP_NONCE_LEN);
    m += WP_NONCE_LEN;
    memcpy(material + m, dev_nonce, WP_NONCE_LEN);
    m += WP_NONCE_LEN;

    const mbedtls_md_info_t *sha256 = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
    const bool ok = sha256 && mbedtls_md_hmac(sha256, psk, WP_PSK_LEN, material, m, key) == 0;
    memset(material, 0, sizeof(material));
    return ok;
}

void wp_make_iv(uint8_t dir, uint32_t counter, uint8_t iv[12])
{
    memset(iv, 0, 12);
    iv[0] = dir;
    iv[8] = (uint8_t)(counter >> 24);
    iv[9] = (uint8_t)(counter >> 16);
    iv[10] = (uint8_t)(counter >> 8);
    iv[11] = (uint8_t)counter;
}

bool wp_gcm_seal(const uint8_t key[WP_KEY_LEN], const uint8_t iv[12],
                 const uint8_t *aad, size_t aad_len,
                 const uint8_t *plain, size_t plain_len, uint8_t *out)
{
    mbedtls_gcm_context gcm;
    mbedtls_gcm_init(&gcm);
    int rc = mbedtls_gcm_setkey(&gcm, MBEDTLS_CIPHER_ID_AES, key, 256);
    if (rc == 0) {
        rc = mbedtls_gcm_crypt_and_tag(&gcm, MBEDTLS_GCM_ENCRYPT, plain_len, iv, 12,
                                       aad, aad_len, plain, out,
                                       WP_TAG_LEN, out + plain_len);
    }
    mbedtls_gcm_free(&gcm);
    return rc == 0;
}

bool wp_gcm_open(const uint8_t key[WP_KEY_LEN], const uint8_t iv[12],
                 const uint8_t *aad, size_t aad_len,
                 const uint8_t *in, size_t in_len, uint8_t *out)
{
    if (in_len < WP_TAG_LEN) {
        return false;
    }
    const size_t n = in_len - WP_TAG_LEN;
    mbedtls_gcm_context gcm;
    mbedtls_gcm_init(&gcm);
    int rc = mbedtls_gcm_setkey(&gcm, MBEDTLS_CIPHER_ID_AES, key, 256);
    if (rc == 0) {
        /* constant-time tag check; the output is wiped on failure */
        rc = mbedtls_gcm_auth_decrypt(&gcm, n, iv, 12, aad, aad_len,
                                      in + n, WP_TAG_LEN, in, out);
    }
    mbedtls_gcm_free(&gcm);
    return rc == 0;
}

size_t wp_seal(const uint8_t psk[WP_PSK_LEN],
               const uint8_t client_nonce[WP_NONCE_LEN],
               const uint8_t dev_nonce[WP_NONCE_LEN],
               const uint8_t *plain, size_t plain_len, uint8_t *out,
               uint8_t key_out[WP_KEY_LEN])
{
    if (!wp_derive_key(psk, client_nonce, dev_nonce, key_out)) {
        return 0;
    }
    out[0] = WP_MSG_VERSION;
    memcpy(out + 1, dev_nonce, WP_NONCE_LEN);

    uint8_t iv[12];
    wp_make_iv(WP_DIR_DEVICE_TO_CLIENT, 0, iv);
    if (!wp_gcm_seal(key_out, iv, out, 1 + WP_NONCE_LEN, plain, plain_len,
                     out + 1 + WP_NONCE_LEN)) {
        return 0;
    }
    return plain_len + WP_MSG_OVERHEAD;
}
