idf_component_register(
    SRCS main.c frame_parse.c presence.c wifi_sniffer.c
         wp_config.c wp_report.c wp_crypto.c wp_store.c wp_gatt.c
         wp_led.c wp_led_logic.c
    INCLUDE_DIRS "."
    REQUIRES nvs_flash esp_wifi esp_event esp_netif esp_timer esp_driver_gpio bt mbedtls log)
