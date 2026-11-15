#!/usr/bin/env bash
# Builds and runs the host tests for the pure C logic (no ESP-IDF needed).
set -euo pipefail
cd "$(dirname "$0")"
out="$(mktemp -d)"
trap 'rm -rf "$out"' EXIT
gcc -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined \
    host_test.c ../main/frame_parse.c ../main/wp_report.c ../main/wp_config.c ../main/wp_led_logic.c -o "$out/host_test"
"$out/host_test"
