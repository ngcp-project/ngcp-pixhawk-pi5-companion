#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
LOCAL_BIN="${HOME}/.local/bin"
AUTOSTART_DIR="${HOME}/.config/autostart"

mkdir -p "${LOCAL_BIN}" "${AUTOSTART_DIR}"

install -m 0755 "${REPO_ROOT}/scripts/ngcp-mavproxy-telemetry.sh" "${LOCAL_BIN}/ngcp-mavproxy-telemetry"
install -m 0755 "${REPO_ROOT}/scripts/ngcp-mavproxy-autostart.sh" "${LOCAL_BIN}/ngcp-mavproxy-autostart"

cat <<DESKTOP > "${AUTOSTART_DIR}/ngcp-mavproxy.desktop"
[Desktop Entry]
Type=Application
Name=NGCP MAVProxy Autostart
Comment=Launch MAVProxy on boot to validate Pixhawk UART telemetry
Exec=${LOCAL_BIN}/ngcp-mavproxy-autostart
Terminal=false
X-GNOME-Autostart-enabled=true
DESKTOP

cat <<'EONOTES'
Autostart installed.
- Command: ~/.local/bin/ngcp-mavproxy-telemetry
- Autostart entry: ~/.config/autostart/ngcp-mavproxy.desktop

Optional overrides (set in your shell profile or systemd user environment):
  MAVPROXY_MASTER=/dev/ttyAMA0
  MAVPROXY_BAUD=57600
  MAVPROXY_EXTRA="--map"
EONOTES
