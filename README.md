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

![Data Pipeline Diagram](docs/data_pipeline_diagram.png)
> *Note: This data pipeline overview was generated using Nano Banana Pro and is subject to change as the repository is updated.*

The autostart script (`ngcp-mavproxy-telemetry.sh`) spins up the following MAVLink routing pipeline:
1. **MAVLink Hub (`mavlink_hub.py`)**: Starts first. Receives all MAVProxy frames on UDP `14550` and fans them out to every registered consumer script at runtime.
2. **MAVProxy (`mavproxy.py`)**: Connects to the Pixhawk over `/dev/ttyAMA0` at 57600 baud. Outputs **only to the hub** (`udp:127.0.0.1:14550`) — no more hardcoded consumer ports.
3. **GCS Translator (`gcs_translator.py`)**: Self-registers with the hub on port `14600` at startup. Extracts MAVLink data (Lat, Lon, Alt, Speed, Pitch, Roll, Yaw, Battery), packs it into the GCS team's `Telemetry` struct, and transmits via XBee.

> [!IMPORTANT]
> **Software Team / Autonomy Team:** The previous static ports `14601` and `14602` no longer receive data directly. Your scripts must self-register with the hub to receive MAVLink frames. See **[`docs/INTEGRATION_GUIDE.md`](docs/INTEGRATION_GUIDE.md)** for the 4-line fix and port assignments table.

### Dual-Control Arbitration (GCS vs. Autonomy)
To safely allow both the GCS and the Software Team's scripts to send commands to the flight controller without collision, control authority is managed via standard flight modes:
- **Offboard/Guided Mode:** Gives the Software Team's Autonomy Engine authority to autonomously navigate the drone.
- **Loiter/Manual/RTL Mode:** Gives the GCS or RC operator absolute manual override authority, causing the flight controller to safely reject the Autonomy Engine's trajectory commands.

## Optional: Tailscale VPN for Reliable SSH
Due to the dynamic IP addressing (DHCP) on university networks and active blocking of local Multicast (mDNS), it can be difficult to reliably connect to the Raspberry Pi 5 companion computer over SSH (e.g. the IP changes every time it reconnects).
To bypass these restrictions and avoid having a roaming IP address on every reboot, it is highly recommended to use **Tailscale**. Tailscale is a free, lightweight mesh VPN that assigns a permanent, static `100.x.x.x` IP address to the Pi 5.
- It bypasses university NAT and firewall restrictions seamlessly by establishing secure peer-to-peer tunnels.
- It allows you to SSH into the Pi 5 from anywhere (even off-campus) using the same IP address.
- To set it up, simply install Tailscale on both your development machine and the Pi 5, authenticate with the same account, and use the provided Tailscale IP in your SSH configuration.

## Documentation (start here)
Readers, current users, and future users should refer to the dedicated GitHub wiki pages for this repo for more detailed information.

Detailed SOPs live in `docs/wiki` (mirrors the GitHub Wiki).

1. `docs/wiki/MAVProxy-Autostart.md`
2. `docs/wiki/UART-MAVLink-Validation.md` *(planned)*

## Repo layout
- `docs/wiki/` – wiki-ready SOPs
- `scripts/` – MAVProxy helpers, autostart installer, and integration daemons.

### Script inventory
- `scripts/install-mavproxy-autostart.sh` – installs helpers into `~/.local/bin` and creates a GNOME desktop autostart entry.
- `scripts/ngcp-mavproxy-autostart.sh` – opens a terminal emulator and runs the telemetry helper.
- `scripts/ngcp-mavproxy-telemetry.sh` – launches Hub → MAVProxy → Translator Daemon in sequence.
- `scripts/gcs_translator.py` – MAVLink → GCS packet translator; self-registers with hub on startup.
- `scripts/mavlink_hub.py` – **[NEW]** Publish-subscribe MAVLink broker. Fan-out to all registered consumers.
- `scripts/test_mavlink_hub.py` – **[NEW]** 7-test unit suite for the hub (run locally, no hardware needed).

## Upcoming Features

### 🔌 Automatic UDP Port Registration for External Scripts
Currently, any new script that needs access to the live MAVLink stream must manually add a `--out udp:127.0.0.1:<PORT>` entry to the `ngcp-mavproxy-telemetry.sh` launch script and reboot. This creates friction for other subteams.

A planned enhancement is a **dynamic UDP port manager** where external scripts can announce themselves at runtime. MAVProxy (or a lightweight multiplexer) would then automatically stand up a new output UDP stream for them — no launch script edits, no reboot required. The goal is a plug-and-play data bus so scripts from the Software, GCS, and Autonomy subteams can consume MAVLink data independently without stepping on each other.

### 🖥️ Active UDP Port Monitor in the GUI
The GCS Telemetry Monitor (`gui_server.py`) currently only displays live telemetry fields. A planned **"Port Monitor" panel** will be added to the web GUI that shows:
- All active MAVLink UDP listeners on the Pi 5 (e.g., `14550 → gcs_translator.py`, `14601 → command_listener.py`)
- Live heartbeat status per port (green = active, red = silent >5s)
- A simple `/ports` REST endpoint on `gui_server.py` to serve this data

This gives operators a real-time health overview of the entire data bus at a glance.

> See [`TODO.md`](TODO.md) for a full backlog including pending GCS compatibility fixes.

## Status
- ✅ UART device mapping confirmed on Pi 5 (`/dev/ttyAMA0`)
- ✅ MAVLink frames observed on TELEM2
- ✅ MAVProxy receives heartbeat + parameters
- ✅ GCS Custom Translation Pipeline Implemented (MAVLink -> UDP -> Python -> XBee)
- 🔧 GCS compatibility fixes pending (see [`TODO.md`](TODO.md))

## Contributing
Update `docs/wiki` first, then mirror to the GitHub Wiki.
