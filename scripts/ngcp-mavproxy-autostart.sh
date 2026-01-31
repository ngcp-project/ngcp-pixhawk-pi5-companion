#!/usr/bin/env bash
set -euo pipefail

LAUNCH_CMD=${LAUNCH_CMD:-"$HOME/.local/bin/ngcp-mavproxy-telemetry"}

if ! [ -x "${LAUNCH_CMD}" ]; then
  echo "Error: ${LAUNCH_CMD} not found or not executable. Run scripts/install-mavproxy-autostart.sh first." >&2
  exit 1
fi

if command -v x-terminal-emulator >/dev/null 2>&1; then
  exec x-terminal-emulator -e "${LAUNCH_CMD}"
elif command -v lxterminal >/dev/null 2>&1; then
  exec lxterminal -e "${LAUNCH_CMD}"
elif command -v xfce4-terminal >/dev/null 2>&1; then
  exec xfce4-terminal --command "${LAUNCH_CMD}"
elif command -v gnome-terminal >/dev/null 2>&1; then
  exec gnome-terminal -- "${LAUNCH_CMD}"
else
  echo "Error: No supported terminal emulator found (x-terminal-emulator, lxterminal, xfce4-terminal, gnome-terminal)." >&2
  exit 1
fi
