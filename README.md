# NGCP Pixhawk ↔ Raspberry Pi 5 Companion Link

This repo is a **focused playbook + helper scripts** to validate and operationalize a **MAVLink
UART link (TELEM2)** between a Pixhawk/Cube flight controller and a Raspberry Pi 5 companion
computer, and to prepare telemetry for routing to a GCS.

## What you get
- Step-by-step SOPs for UART bring-up and validation
- Autostart helpers to launch MAVProxy on Pi boot/login
- A baseline for future telemetry routing (serial → UDP/TCP)

## Quick start (Pi 5 desktop)
1. Install the MAVProxy autostart helpers:
   ```bash
   ./scripts/install-mavproxy-autostart.sh
   ```
2. Reboot and log into the GNOME desktop.
3. A terminal should open and MAVProxy should report a detected vehicle.

## Documentation (start here)
Detailed SOPs live in `docs/wiki` (mirrors the GitHub Wiki).

1. `docs/wiki/MAVProxy-Autostart.md`
2. `docs/wiki/UART-MAVLink-Validation.md` *(planned)*

## Repo layout
- `docs/wiki/` – wiki-ready SOPs
- `scripts/` – MAVProxy helpers and autostart installer

### Script inventory
- `scripts/install-mavproxy-autostart.sh` – installs helpers into `~/.local/bin` and creates a
  GNOME desktop autostart entry
- `scripts/ngcp-mavproxy-autostart.sh` – opens a terminal emulator and runs the telemetry helper
- `scripts/ngcp-mavproxy-telemetry.sh` – launches MAVProxy against the configured UART device

## Status
- UART device mapping confirmed on Pi 5 (`/dev/ttyAMA0`)
- MAVLink frames observed on TELEM2
- MAVProxy receives heartbeat + parameters

## Contributing
Update `docs/wiki` first, then mirror to the GitHub Wiki.
