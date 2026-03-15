#!/usr/bin/env bash
set -euo pipefail

MAVPROXY_BIN=${MAVPROXY_BIN:-mavproxy.py}
MAVPROXY_MASTER=${MAVPROXY_MASTER:-}
MAVPROXY_BAUD=${MAVPROXY_BAUD:-57600}
MAVPROXY_EXTRA_ARGS=${MAVPROXY_EXTRA_ARGS:-${MAVPROXY_EXTRA:-}}

# Hardcode the path to the workspace so it survives executing as a symlink
REPO_ROOT="/home/ngcp25/work/ngcp-pixhawk-pi5-companion"

if ! command -v "${MAVPROXY_BIN}" >/dev/null 2>&1; then
  echo "Error: ${MAVPROXY_BIN} not found." >&2
  exit 1
fi

# We need to detect the UART master if not provided
if [[ -z "${MAVPROXY_MASTER}" ]]; then
  if [[ -e /dev/ttyAMA0 ]]; then
    MAVPROXY_MASTER=/dev/ttyAMA0
  elif [[ -e /dev/ttyS0 ]]; then
    MAVPROXY_MASTER=/dev/ttyS0
  else
    echo "Warning: No UART detected and MAVPROXY_MASTER unset! Will attempt /dev/ttyAMA0 anyway."
    MAVPROXY_MASTER=/dev/ttyAMA0
  fi
fi

# Launch MAVProxy to pipe Serial -> UDP
echo "Starting local MAVProxy link..."
"${MAVPROXY_BIN}" --master="${MAVPROXY_MASTER}" --baudrate="${MAVPROXY_BAUD}" \
  --out=udp:127.0.0.1:14550 \
  --out=udp:127.0.0.1:14540 \
  --out=udp:127.0.0.1:14601 \
  --out=udp:127.0.0.1:14602 \
  --out=udp:127.0.0.1:14603 \
  --daemon ${MAVPROXY_EXTRA_ARGS} &
MAVPROXY_PID=$!


# Launch backend translation services
echo "Starting Telemetry Translator services..."
"${REPO_ROOT}/scripts/gcs_translator.py" &
TRANSLATOR_PID=$!

python3 "${REPO_ROOT}/scripts/gui_server.py" &
GUI_PID=$!

echo "Opening GUI in Firefox..."
firefox --new-tab http://localhost:8082 &
FIREFOX_PID=$!

echo "All services started. Press Ctrl+C to terminate."
wait