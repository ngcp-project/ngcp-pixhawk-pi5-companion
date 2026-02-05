#!/usr/bin/env bash
set -euo pipefail

MAVPROXY_BIN=${MAVPROXY_BIN:-mavproxy.py}
MAVPROXY_MASTER=${MAVPROXY_MASTER:-}
MAVPROXY_BAUD=${MAVPROXY_BAUD:-57600}
MAVPROXY_EXTRA_ARGS=${MAVPROXY_EXTRA_ARGS:-${MAVPROXY_EXTRA:-}}

if ! command -v "${MAVPROXY_BIN}" >/dev/null 2>&1; then
  echo "Error: ${MAVPROXY_BIN} not found. Install MAVProxy (e.g., sudo apt install mavproxy)." >&2
  exit 1
fi

if [[ -z "${MAVPROXY_MASTER}" ]]; then
  # Pick the first common Pi UART path that exists on this host.
  for candidate in /dev/ttyAMA0 /dev/serial0 /dev/ttyS0 /dev/ttyAMA10; do
    if [[ -e "${candidate}" ]]; then
      MAVPROXY_MASTER="${candidate}"
      break
    fi
  done
fi

if [[ -z "${MAVPROXY_MASTER}" ]]; then
  echo "Error: Could not auto-detect a UART device. Set MAVPROXY_MASTER explicitly." >&2
  echo "Hint: detected serial devices:" >&2
  ls -1 /dev/ttyAMA* /dev/ttyS* 2>/dev/null >&2 || echo "  (none found)" >&2
  exit 1
fi

if [[ ! -e "${MAVPROXY_MASTER}" ]]; then
  echo "Error: MAVPROXY_MASTER points to a missing device: ${MAVPROXY_MASTER}" >&2
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
