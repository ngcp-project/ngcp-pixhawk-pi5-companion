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

# ── Step 1: Start MAVLink Hub (publish-subscribe broker) ─────────────────────
# The hub receives all MAVProxy frames on port 14550 and fans them out to any
# registered consumer script at runtime — no restart needed to add new scripts.
echo "Starting MAVLink Hub broker..."
python3 "${REPO_ROOT}/scripts/mavlink_hub.py" \
  --in-port 14550 \
  --reg-port 14555 &
HUB_PID=$!

# Give the hub a moment to bind its sockets before MAVProxy starts sending
sleep 1

# ── Step 2: Start MAVProxy → single output to hub ─────────────────────────────
# Previously used 3 hardcoded --out ports; now uses 1 (the hub's input).
# New consumer scripts self-register via register_with_hub() — no edits here.
echo "Starting MAVProxy (output → hub on udp:127.0.0.1:14550)..."
"${MAVPROXY_BIN}" --master="${MAVPROXY_MASTER}" --baudrate="${MAVPROXY_BAUD}" \
  --out=udp:127.0.0.1:14550 \
  --daemon ${MAVPROXY_EXTRA_ARGS} &
MAVPROXY_PID=$!

# ── Step 3: Launch backend translation services ───────────────────────────────
# gcs_translator.py calls register_with_hub() internally on startup.
echo "Starting Telemetry Translator services..."
"${REPO_ROOT}/scripts/gcs_translator.py" &
TRANSLATOR_PID=$!

python3 "${REPO_ROOT}/scripts/gui_server.py" &
GUI_PID=$!

echo "Opening GUI in Firefox..."
firefox --new-tab http://localhost:8082 &
FIREFOX_PID=$!

echo "All services started (hub PID=${HUB_PID}, mavproxy PID=${MAVPROXY_PID})."
echo "Press Ctrl+C to terminate."
wait