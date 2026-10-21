if(DEFINED LIGHTJACK_LOADER_PAYLOAD)
    # The separate Lightjack build embeds its verified loader without replacing
    # the upstream payload.bin. The basename preserves the C symbol names.
    get_filename_component(payload_name "${LIGHTJACK_LOADER_PAYLOAD}" NAME)
    if(NOT EXISTS "${LIGHTJACK_LOADER_PAYLOAD}" OR NOT payload_name STREQUAL "payload.bin")
        message(FATAL_ERROR "LIGHTJACK_LOADER_PAYLOAD must name an existing payload.bin")
    endif()
    set(loader_payload "${LIGHTJACK_LOADER_PAYLOAD}")
else()
    set(loader_payload "${CMAKE_CURRENT_SOURCE_DIR}/../payload.bin")
endif()
idf_component_register(SRCS "ap_main.c"
                       INCLUDE_DIRS "."
                       EMBED_FILES "${loader_payload}"
                       REQUIRES esp_wifi esp_netif esp_event nvs_flash)
