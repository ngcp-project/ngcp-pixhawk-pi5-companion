# NGCP Pixhawk ↔ Raspberry Pi 5 Companion Link

This repo is a **focused playbook + helper scripts** to validate and operationalize a **MAVLink UART link (TELEM2)** between a Pixhawk/Cube flight controller and a Raspberry Pi 5 companion computer, and to securely route that telemetry to the **Ground Control Station (GCS)** over an XBee radio.

## What you get
- Step-by-step SOPs for UART bring-up and validation.
- Autostart helpers to launch MAVProxy on Pi boot/login.
- A **Python Translation Daemon** (`gcs_translator.py`) that converts MAVLink data into the GCS team's custom 68-byte packet structure.
- Automatic routing of telemetry from the Flight Controller -> MAVProxy (UDP) -> Translator Daemon -> XBee Radio (USB).

## Quick start (Pi 5 desktop)
1. Plug your XBee Radio into any available USB port on the Pi 5.
2. Install the MAVProxy/Translator autostart helpers:
   ```bash
   ./scripts/install-mavproxy-autostart.sh
   ```
3. Reboot and log into the GNOME desktop.
4. A terminal should open. MAVProxy will detect the vehicle, and the background translator daemon will begin streaming data to the GCS!

## Architecture & Integration
The autostart script (`ngcp-mavproxy-telemetry.sh`) currently spins up two separate processes:
1. **MAVProxy (`mavproxy.py`)**: Connects physically to the Pixhawk over `/dev/ttyAMA0` (Serial0) at 57600 baud. It broadcasts all incoming MAVLink frames locally to UDP port `14550`.
2. **GCS Translator (`gcs_translator.py`)**: A Python daemon that listens to UDP `14550`. It extracts specific data (Lat, Lon, Alt, Speed, Pitch, Roll, Yaw, Battery), packs it into the GCS team's `Telemetry` struct, and transmits it via the XBee API out of an automatically-detected `/dev/ttyUSB*` port.

## Documentation (start here)
Detailed SOPs live in `docs/wiki` (mirrors the GitHub Wiki).

1. `docs/wiki/MAVProxy-Autostart.md`
2. `docs/wiki/UART-MAVLink-Validation.md` *(planned)*

## Repo layout
- `docs/wiki/` – wiki-ready SOPs
- `scripts/` – MAVProxy helpers, autostart installer, and integration daemons.

### Script inventory
- `scripts/install-mavproxy-autostart.sh` – installs helpers into `~/.local/bin` and creates a GNOME desktop autostart entry.
- `scripts/ngcp-mavproxy-autostart.sh` – opens a terminal emulator and runs the telemetry helper.
- `scripts/ngcp-mavproxy-telemetry.sh` – launches MAVProxy (to UDP) and the Translator Daemon in the background.
- `scripts/gcs_translator.py` – **[NEW]** The Python script bridging MAVLink and the external GCS radio.

## Status
- ✅ UART device mapping confirmed on Pi 5 (`/dev/ttyAMA0`)
- ✅ MAVLink frames observed on TELEM2
- ✅ MAVProxy receives heartbeat + parameters
- ✅ GCS Custom Translation Pipeline Implemented (MAVLink -> UDP -> Python -> XBee)

## Contributing
Update `docs/wiki` first, then mirror to the GitHub Wiki.
