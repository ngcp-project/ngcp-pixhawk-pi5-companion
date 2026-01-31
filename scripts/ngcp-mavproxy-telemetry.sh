#!/usr/bin/env bash
set -euo pipefail

MAVPROXY_BIN=${MAVPROXY_BIN:-mavproxy.py}
MAVPROXY_MASTER=${MAVPROXY_MASTER:-/dev/ttyAMA0}
MAVPROXY_BAUD=${MAVPROXY_BAUD:-57600}
MAVPROXY_EXTRA_ARGS=${MAVPROXY_EXTRA_ARGS:-${MAVPROXY_EXTRA:-}}

if ! command -v "${MAVPROXY_BIN}" >/dev/null 2>&1; then
  echo "Error: ${MAVPROXY_BIN} not found. Install MAVProxy (e.g., sudo apt install mavproxy)." >&2
  exit 1
fi

echo "Launching MAVProxy for UART validation..."
echo "  Master: ${MAVPROXY_MASTER}"
echo "  Baud:   ${MAVPROXY_BAUD}"

extra_args=()
if [[ -n "${MAVPROXY_EXTRA_ARGS}" ]]; then
  read -r -a extra_args <<< "${MAVPROXY_EXTRA_ARGS}"
fi

exec "${MAVPROXY_BIN}" --master="${MAVPROXY_MASTER}" --baudrate="${MAVPROXY_BAUD}" --console "${extra_args[@]}"
