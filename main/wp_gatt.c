#include "wp_gatt.h"

#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#include "esp_log.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "host/ble_hs.h"
#include "host/util/util.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "sdkconfig.h"
#include "services/gap/ble_svc_gap.h"
#include "services/gatt/ble_svc_gatt.h"

#include "frame_parse.h"
#include "presence.h"
#include "wifi_sniffer.h"
#include "wp_config.h"
#include "wp_crypto.h"
#include "wp_report.h"
#include "wp_store.h"

static const char *TAG = "gatt";

/* 6e1d000x-5a3c-4f1e-9b7a-0c2d8e4f1a60, written least significant byte first */
#define WP_UUID128(x) BLE_UUID128_INIT(0x60, 0x1a, 0x4f, 0x8e, 0x2d, 0x0c, 0x7a, 0x9b, \
                                       0x1e, 0x4f, 0x3c, 0x5a, (x), 0x00, 0x1d, 0x6e)

static const ble_uuid128_t SVC_UUID  = WP_UUID128(0x01);
static const ble_uuid128_t CTRL_UUID = WP_UUID128(0x02);
static const ble_uuid128_t DATA_UUID = WP_UUID128(0x03);
static const ble_uuid128_t CMD_UUID  = WP_UUID128(0x04);

#define CTRL_WRITE_LEN  (1 + WP_NONCE_LEN)
#define MAX_PLAIN       WP_REPORT_MAX_LEN(CONFIG_WP_MAX_DEVICES)
#define MAX_MSG         (MAX_PLAIN + WP_MSG_OVERHEAD)
#define MAX_CMD_PLAIN   (1 + WP_CFG_BLOB_MAX)
#define MAX_CMD_MSG     (WP_CMSG_OVERHEAD + MAX_CMD_PLAIN)
#define CMD_CHUNK_MAX   244 /* largest write accepted (a 247-byte MTU minus the ATT header) */
#define NOTIFY_RETRIES  100

/* Events for the sender task. */
#define NOTE_REPORT     0x01
#define NOTE_COMMAND    0x02

/* Commands (plaintext of a client message) and acknowledgements. */
#define CMD_SET_CONFIG  0x01
#define ACK_SET_CONFIG  0xA1

static uint8_t  s_own_addr_type;
static char     s_addr_str[18];
static uint16_t s_conn = BLE_HS_CONN_HANDLE_NONE;
static uint16_t s_data_handle;
static volatile bool s_subscribed;
static volatile bool s_busy;
static uint8_t  s_client_nonce[WP_NONCE_LEN];
static TaskHandle_t s_sender;
static esp_timer_handle_t s_conn_timer;

static wp_client_info_t s_clients[CONFIG_WP_MAX_DEVICES];
static uint8_t s_plain[MAX_PLAIN];
static uint8_t s_msg[MAX_MSG];

/* The session is the key of the latest report; commands are sealed under it. */
static uint8_t  s_key[WP_KEY_LEN];
static volatile bool s_session;
static uint32_t s_last_ctr;

static uint8_t     s_cmd_buf[MAX_CMD_MSG];
static wp_reasm_t  s_cmd_reasm;

static int gap_event(struct ble_gap_event *event, void *arg);

/* ---- advertising: service UUID and name only, nothing about clients ------ */

static void advertise(void)
{
    static ble_uuid128_t adv_uuid = WP_UUID128(0x01); /* non-const copy for the adv API */
    struct ble_hs_adv_fields fields = {0};
    fields.flags = BLE_HS_ADV_F_DISC_GEN | BLE_HS_ADV_F_BREDR_UNSUP;
    fields.uuids128 = &adv_uuid;
    fields.num_uuids128 = 1;
    fields.uuids128_is_complete = 1;
    int rc = ble_gap_adv_set_fields(&fields);
    if (rc != 0) {
        ESP_LOGE(TAG, "adv_set_fields rc=%d", rc);
        return;
    }

    struct ble_hs_adv_fields rsp = {0};
    rsp.name = (const uint8_t *)CONFIG_WP_BLE_NAME;
    rsp.name_len = strlen(CONFIG_WP_BLE_NAME);
    rsp.name_is_complete = 1;
    rc = ble_gap_adv_rsp_set_fields(&rsp);
    if (rc != 0) {
        ESP_LOGE(TAG, "adv_rsp_set_fields rc=%d", rc);
        return;
    }

    struct ble_gap_adv_params params = {0};
    params.conn_mode = BLE_GAP_CONN_MODE_UND;
    params.disc_mode = BLE_GAP_DISC_MODE_GEN;
    params.itvl_min = BLE_GAP_ADV_ITVL_MS(100);
    params.itvl_max = BLE_GAP_ADV_ITVL_MS(150);
    rc = ble_gap_adv_start(s_own_addr_type, NULL, BLE_HS_FOREVER, &params, gap_event, NULL);
    if (rc != 0 && rc != BLE_HS_EALREADY) {
        ESP_LOGE(TAG, "adv_start rc=%d", rc);
    }
}

/* ---- connection lifetime ------------------------------------------------- */

/* A stranger who connects and idles would block Home Assistant: cut them off. */
static void conn_timeout_cb(void *arg)
{
    if (s_conn != BLE_HS_CONN_HANDLE_NONE) {
        ESP_LOGW(TAG, "connection open too long, dropping it");
        ble_gap_terminate(s_conn, BLE_ERR_REM_USER_CONN_TERM);
    }
}

static int gap_event(struct ble_gap_event *event, void *arg)
{
    switch (event->type) {
    case BLE_GAP_EVENT_CONNECT:
        if (event->connect.status == 0) {
            s_conn = event->connect.conn_handle;
            s_subscribed = false;
            s_session = false;
            wp_reasm_reset(&s_cmd_reasm);
            esp_timer_stop(s_conn_timer);
            esp_timer_start_once(s_conn_timer, (uint64_t)CONFIG_WP_CONN_TIMEOUT_S * 1000000);
            ESP_LOGI(TAG, "connected");
        } else {
            advertise();
        }
        break;
    case BLE_GAP_EVENT_DISCONNECT:
        s_conn = BLE_HS_CONN_HANDLE_NONE;
        s_subscribed = false;
        s_session = false;
        esp_timer_stop(s_conn_timer);
        ESP_LOGI(TAG, "disconnected (reason %d)", event->disconnect.reason);
        advertise();
        break;
    case BLE_GAP_EVENT_SUBSCRIBE:
        if (event->subscribe.attr_handle == s_data_handle) {
            s_subscribed = event->subscribe.cur_notify;
        }
        break;
    case BLE_GAP_EVENT_ADV_COMPLETE:
        advertise();
        break;
    case BLE_GAP_EVENT_MTU:
        ESP_LOGI(TAG, "mtu %u", event->mtu.value);
        break;
    default:
        break;
    }
    return 0;
}

/* ---- GATT table ---------------------------------------------------------- */

static int ctrl_access(uint16_t conn, uint16_t attr, struct ble_gatt_access_ctxt *ctxt, void *arg)
{
    if (ctxt->op != BLE_GATT_ACCESS_OP_WRITE_CHR) {
        return BLE_ATT_ERR_UNLIKELY;
    }
    if (OS_MBUF_PKTLEN(ctxt->om) != CTRL_WRITE_LEN) {
        return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
    }
    uint8_t buf[CTRL_WRITE_LEN];
    if (os_mbuf_copydata(ctxt->om, 0, sizeof(buf), buf) != 0 || buf[0] != WP_MSG_VERSION) {
        return BLE_ATT_ERR_VALUE_NOT_ALLOWED;
    }
    if (!s_subscribed || s_busy) {
        return BLE_ATT_ERR_INSUFFICIENT_RES;
    }
    memcpy(s_client_nonce, buf + 1, WP_NONCE_LEN);
    wp_reasm_reset(&s_cmd_reasm);
    s_busy = true;
    xTaskNotify(s_sender, NOTE_REPORT, eSetBits);
    return 0;
}

/* A sealed command arrives in fragments, like a reply leaves in fragments. */
static int cmd_access(uint16_t conn, uint16_t attr, struct ble_gatt_access_ctxt *ctxt, void *arg)
{
    if (ctxt->op != BLE_GATT_ACCESS_OP_WRITE_CHR) {
        return BLE_ATT_ERR_UNLIKELY;
    }
    const size_t len = OS_MBUF_PKTLEN(ctxt->om);
    if (len < 1 || len > CMD_CHUNK_MAX) {
        return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
    }
    if (!s_session || !s_subscribed || s_busy) {
        return BLE_ATT_ERR_INSUFFICIENT_RES;
    }
    uint8_t chunk[CMD_CHUNK_MAX];
    if (os_mbuf_copydata(ctxt->om, 0, len, chunk) != 0) {
        return BLE_ATT_ERR_UNLIKELY;
    }
    const int r = wp_reasm_feed(&s_cmd_reasm, chunk, len);
    if (r == WP_REASM_ERR) {
        return BLE_ATT_ERR_VALUE_NOT_ALLOWED;
    }
    if (r == WP_REASM_DONE) {
        s_busy = true;
        xTaskNotify(s_sender, NOTE_COMMAND, eSetBits);
    }
    return 0;
}

static int data_access(uint16_t conn, uint16_t attr, struct ble_gatt_access_ctxt *ctxt, void *arg)
{
    return BLE_ATT_ERR_READ_NOT_PERMITTED; /* notify only */
}

static const struct ble_gatt_svc_def GATT_SVCS[] = {
    {
        .type = BLE_GATT_SVC_TYPE_PRIMARY,
        .uuid = &SVC_UUID.u,
        .characteristics = (struct ble_gatt_chr_def[]) {
            {
                .uuid = &CTRL_UUID.u,
                .access_cb = ctrl_access,
                .flags = BLE_GATT_CHR_F_WRITE,
            },
            {
                .uuid = &DATA_UUID.u,
                .access_cb = data_access,
                .val_handle = &s_data_handle,
                .flags = BLE_GATT_CHR_F_NOTIFY,
            },
            {
                .uuid = &CMD_UUID.u,
                .access_cb = cmd_access,
                .flags = BLE_GATT_CHR_F_WRITE,
            },
            { 0 },
        },
    },
    { 0 },
};

/* ---- answering a request ------------------------------------------------- */

static bool notify_chunk(uint16_t conn, const uint8_t *chunk, size_t len)
{
    for (int attempt = 0; attempt < NOTIFY_RETRIES; attempt++) {
        if (s_conn != conn || !s_subscribed) {
            return false;
        }
        struct os_mbuf *om = ble_hs_mbuf_from_flat(chunk, len);
        if (om) {
            int rc = ble_gatts_notify_custom(conn, s_data_handle, om); /* consumes om */
            if (rc == 0) {
                return true;
            }
            if (rc != BLE_HS_ENOMEM && rc != BLE_HS_EBUSY) {
                ESP_LOGW(TAG, "notify rc=%d", rc);
                return false;
            }
        }
        vTaskDelay(pdMS_TO_TICKS(10)); /* controller queue full: let it drain */
    }
    return false;
}

/** Fragment `msg` to the connection's MTU and notify it. */
static bool send_message(uint16_t conn, const uint8_t *msg, size_t mlen, size_t *frag_count)
{
    uint16_t mtu = ble_att_mtu(conn);
    if (mtu < BLE_ATT_MTU_DFLT) {
        mtu = BLE_ATT_MTU_DFLT;
    }
    const size_t per_chunk = mtu - 3 - 1;
    const size_t count = wp_frag_count(mlen, per_chunk);
    uint8_t chunk[1 + 512];
    if (count == 0 || count > 128 || per_chunk > sizeof(chunk) - 1) {
        ESP_LOGE(TAG, "message does not fit (%u bytes, mtu %u)", (unsigned)mlen, mtu);
        return false;
    }
    for (size_t seq = 0; seq < count; seq++) {
        size_t clen = wp_frag_build(msg, mlen, per_chunk, seq, chunk);
        if (!notify_chunk(conn, chunk, clen)) {
            ESP_LOGW(TAG, "message aborted at fragment %u/%u", (unsigned)seq, (unsigned)count);
            return false;
        }
    }
    *frag_count = count;
    return true;
}

static void send_report(void)
{
    const uint16_t conn = s_conn;
    if (conn == BLE_HS_CONN_HANDLE_NONE) {
        return;
    }

    size_t n = wp_presence_snapshot(s_clients, CONFIG_WP_MAX_DEVICES);
    size_t plen = wp_report_pack(s_plain, sizeof(s_plain),
                                 (uint32_t)(esp_timer_get_time() / 1000000),
                                 (uint8_t)wp_sniffer_target_count(), wp_config_crc(),
                                 s_clients, n);
    uint8_t dev_nonce[WP_NONCE_LEN];
    esp_fill_random(dev_nonce, sizeof(dev_nonce));
    s_session = false;
    size_t mlen = plen ? wp_seal(wp_store_psk(), s_client_nonce, dev_nonce,
                                 s_plain, plen, s_msg, s_key) : 0;
    if (mlen == 0) {
        ESP_LOGE(TAG, "could not build report");
        return;
    }
    s_last_ctr = 0;
    s_session = true;

    size_t count = 0;
    if (send_message(conn, s_msg, mlen, &count)) {
        ESP_LOGI(TAG, "sent %u client(s) in %u fragment(s)", (unsigned)n, (unsigned)count);
    }
}

static uint32_t be32(const uint8_t *p)
{
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | p[3];
}

/**
 * A client message: version || counter || ciphertext || tag, sealed under the
 * session key. A message that does not verify is dropped without an answer.
 */
static void handle_command(void)
{
    const uint16_t conn = s_conn;
    const size_t mlen = s_cmd_reasm.len;
    wp_reasm_reset(&s_cmd_reasm);
    if (conn == BLE_HS_CONN_HANDLE_NONE || !s_session) {
        return;
    }
    if (mlen < WP_CMSG_OVERHEAD + 1 || s_cmd_buf[0] != WP_MSG_VERSION) {
        ESP_LOGW(TAG, "command: malformed");
        return;
    }
    const uint32_t ctr = be32(&s_cmd_buf[1]);
    if (ctr == 0 || ctr <= s_last_ctr) {
        ESP_LOGW(TAG, "command: counter %u not fresh", (unsigned)ctr);
        return;
    }
    uint8_t iv[12];
    uint8_t plain[MAX_CMD_PLAIN];
    wp_make_iv(WP_DIR_CLIENT_TO_DEVICE, ctr, iv);
    if (!wp_gcm_open(s_key, iv, s_cmd_buf, WP_CMSG_HDR_LEN,
                     s_cmd_buf + WP_CMSG_HDR_LEN, mlen - WP_CMSG_HDR_LEN, plain)) {
        ESP_LOGW(TAG, "command: authentication failed");
        return;
    }
    s_last_ctr = ctr;
    const size_t plen = mlen - WP_CMSG_OVERHEAD;

    uint8_t status = WP_SET_INVALID;
    if (plain[0] == CMD_SET_CONFIG) {
        status = (uint8_t)wp_store_set_config(plain + 1, plen - 1);
        if (status == WP_SET_OK) {
            wp_store_mark_paired(); /* only a holder of the key gets this far */
        }
    } else {
        ESP_LOGW(TAG, "command: unknown 0x%02x", plain[0]);
    }

    /* acknowledgement: ack type, status, CRC of the settings now in force */
    const uint32_t crc = wp_config_crc();
    uint8_t ack[6] = { ACK_SET_CONFIG, status,
                       (uint8_t)(crc >> 24), (uint8_t)(crc >> 16), (uint8_t)(crc >> 8), (uint8_t)crc };
    s_msg[0] = WP_MSG_VERSION;
    s_msg[1] = (uint8_t)(ctr >> 24);
    s_msg[2] = (uint8_t)(ctr >> 16);
    s_msg[3] = (uint8_t)(ctr >> 8);
    s_msg[4] = (uint8_t)ctr;
    wp_make_iv(WP_DIR_DEVICE_TO_CLIENT, ctr, iv);
    if (!wp_gcm_seal(s_key, iv, s_msg, WP_CMSG_HDR_LEN, ack, sizeof(ack), s_msg + WP_CMSG_HDR_LEN)) {
        return;
    }
    size_t count = 0;
    if (send_message(conn, s_msg, WP_CMSG_OVERHEAD + sizeof(ack), &count)) {
        ESP_LOGI(TAG, "command 0x%02x handled, status %u", plain[0], status);
    }
}

static void sender_task(void *arg)
{
    for (;;) {
        uint32_t bits = 0;
        xTaskNotifyWait(0, UINT32_MAX, &bits, portMAX_DELAY);
        if (bits & NOTE_REPORT) {
            send_report();
        }
        if (bits & NOTE_COMMAND) {
            handle_command();
        }
        s_busy = false;
    }
}

/* ---- start-up ------------------------------------------------------------ */

static void on_sync(void)
{
    if (ble_hs_util_ensure_addr(0) != 0 || ble_hs_id_infer_auto(0, &s_own_addr_type) != 0) {
        ESP_LOGE(TAG, "no usable BLE address");
        return;
    }
    uint8_t addr[6];
    if (ble_hs_id_copy_addr(s_own_addr_type, addr, NULL) == 0) {
        snprintf(s_addr_str, sizeof(s_addr_str), "%02X:%02X:%02X:%02X:%02X:%02X",
                 addr[5], addr[4], addr[3], addr[2], addr[1], addr[0]);
    }
    ESP_LOGI(TAG, "BLE ready, advertising as '%s' (%s)", CONFIG_WP_BLE_NAME, s_addr_str);
    advertise();
}

static void host_task(void *param)
{
    nimble_port_run();
    nimble_port_freertos_deinit();
}

bool wp_gatt_address(char out[18])
{
    if (s_addr_str[0] == '\0') {
        return false;
    }
    memcpy(out, s_addr_str, sizeof(s_addr_str));
    return true;
}

void wp_gatt_start(void)
{
    const esp_timer_create_args_t targs = { .callback = conn_timeout_cb, .name = "wp_conn" };
    ESP_ERROR_CHECK(esp_timer_create(&targs, &s_conn_timer));
    wp_reasm_init(&s_cmd_reasm, s_cmd_buf, sizeof(s_cmd_buf));

    ESP_ERROR_CHECK(nimble_port_init());
    ble_hs_cfg.sync_cb = on_sync;
    ble_svc_gap_init();
    ble_svc_gatt_init();
    ESP_ERROR_CHECK(ble_gatts_count_cfg(GATT_SVCS));
    ESP_ERROR_CHECK(ble_gatts_add_svcs(GATT_SVCS));
    ble_svc_gap_device_name_set(CONFIG_WP_BLE_NAME);

    xTaskCreate(sender_task, "wp_sender", 6144, NULL, 4, &s_sender);
    nimble_port_freertos_init(host_task);
}
