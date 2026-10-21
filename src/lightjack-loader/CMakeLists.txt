# Lightjack laboratory profile, 2026-10-21. SPDX-License-Identifier: MIT.
cmake_minimum_required(VERSION 3.16)
set(IDF_TARGET esp32c3)
set(EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_LIST_DIR}/../wyze-loader/main")
set(PROJECT_VER "0.1.0-lightjack-loader")
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
idf_build_set_property(MINIMAL_BUILD ON)
# Keep the project identity expected by the Lightjack app's recovery checks.
project(wyze_loader)
idf_component_get_property(loader_component main COMPONENT_LIB)
target_compile_definitions(${loader_component} PRIVATE LIGHTJACK_LOADER_POC=1)
