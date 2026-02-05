# NGCP Pixhawk ↔ Raspberry Pi 5 Companion Link (MAVLink Telemetry Pipeline)

This repository is the **engineering playbook** for integrating a **Raspberry Pi 5 companion computer** with a **Pixhawk/Cube flight controller** and building a reliable **MAVLink telemetry pipeline** for NGCP.

**Core objective:**  
Validate and operationalize **Pixhawk ↔ Pi 5 MAVLink over UART (TELEM2)**, then **route/bridge telemetry to the Ground Control Station (GCS)** (e.g., serial → UDP/TCP, logging, diagnostics, future autonomy hooks).

---

## What this repo is for
- **Repeatable bring-up and validation** of MAVLink telemetry between Pixhawk and Pi 5  
- **Configuration + troubleshooting SOPs** (what to set on the FC, what to set on the Pi, how to verify frames/heartbeats)
- **Telemetry forwarding workflows** to support GCS software integration (serial routing, networking, logs)

---

## Documentation (Start Here)
The short summaries live in this repo, and the more detailed write-ups are mirrored for the
**GitHub Wiki**. The `docs/wiki` folder contains Markdown intended for that wiki.

Suggested reading order:
1. **MAVProxy Autostart (Pi 5 Desktop Validation)** (`docs/wiki/MAVProxy-Autostart.md`)  
2. **UART MAVLink Validation (TELEM2 ↔ Pi 5)** *(planned)*  
3. **Quick Reference / Golden Commands** *(planned)*  
4. **Troubleshooting Decision Tree** *(planned)*

---

## Current Status
- ✅ UART device mapping confirmed on Pi 5 (`/dev/ttyAMA0`)  
- ✅ MAVLink frames observed on TELEM2 (raw byte validation)  
- ✅ MAVProxy receives heartbeat + parameters over UART (end-to-end link validated)

---

## Repo Layout
- `README.md` – overview + quickstart info (this file)
- `docs/wiki/` – detailed pages intended for the GitHub Wiki
- `scripts/` – helper scripts for MAVProxy validation and autostart

### Script inventory
- `scripts/install-mavproxy-autostart.sh` – installs the helpers into `~/.local/bin` and
  creates the GNOME desktop autostart entry.
- `scripts/ngcp-mavproxy-autostart.sh` – opens a terminal emulator and runs the telemetry helper.
- `scripts/ngcp-mavproxy-telemetry.sh` – launches MAVProxy against the configured UART device.

---

## Autostart MAVProxy on Pi 5 boot (desktop)
Use the helper script below to install a desktop autostart entry that launches a terminal and runs
MAVProxy for quick visual confirmation of MAVLink traffic over UART.
This has been validated against Ubuntu 24.04 LTS desktop defaults (GNOME).

```bash
./scripts/install-mavproxy-autostart.sh
```

What it does:
- Installs launch helpers in `~/.local/bin`:
  - `ngcp-mavproxy-telemetry` (runs MAVProxy against `/dev/ttyAMA0` at 57600 baud)
  - `ngcp-mavproxy-autostart` (opens a terminal and runs the command above)
- Creates an autostart entry at `~/.config/autostart/ngcp-mavproxy.desktop`

Optional overrides (set in your shell profile or systemd user environment):
```bash
export MAVPROXY_MASTER=/dev/ttyAMA0
export MAVPROXY_BAUD=57600
export MAVPROXY_EXTRA_ARGS="--map --aircraft test"
export TERMINAL_EMULATOR=gnome-terminal
```

### Install MAVProxy on Ubuntu 24.04
Ubuntu 24.04 does not ship a `mavproxy` package in the default repositories. Install via `pipx`
or `pip` instead.

```bash
sudo apt update
sudo apt install -y pipx
pipx ensurepath
pipx install MAVProxy
```

## Contributing / Updating the SOP
If you improve a procedure or discover a new failure mode, please update the Markdown in
`docs/wiki` and then mirror it to the GitHub Wiki so future engineers don’t repeat the same
debugging.

---
