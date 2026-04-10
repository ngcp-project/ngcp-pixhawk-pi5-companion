# NGCP Pixhawk ↔ Raspberry Pi 5 Companion Link

> **Version:** v1.2.0 &nbsp;|&nbsp; **Branch:** `EstimationTab`

This repo is a **focused playbook + helper scripts** to validate and operationalize a **MAVLink UART link (TELEM2)** between a Pixhawk/Cube flight controller and a Raspberry Pi 5 companion computer, and to securely route that telemetry to the **Ground Control Station (GCS)** over an XBee radio.

> Note: Scripts and workflow are tailored specifically for CPP MRA and GCS. CPSLO MEA may use this GitHub repo with caution and it is strongly advised to use this repo as a template.

## Features

| Component | Status | Description |
|---|---|---|
| **Pi 5 MAVProxy Pipeline** | ✅ Operational | UART → MAVProxy → multi-UDP fan-out (`14550`, `14540`, `14601`, `14602`) |
| **GCS Translator Daemon** | ✅ Operational | MAVLink → GCS custom 72-byte `Telemetry` struct → XBee API transmission |
| **GCS Laptop MAVProxy Router** | ✅ Operational | Auto-detects RFD-900x COM port, fans out to QGC + Kraken + Software Team |
| **Kraken Triangulator** | ✅ Operational (local) | Web-based RF triangulation dashboard with LS-AoA, Bayesian grid, and spatial filtering |
| **GCS Command Receiver** | ✅ Operational | Heartbeat & EmergencyStop commands from GCS → MAVLink flight termination |
| **Transmit to GCS Pipeline** | 🔲 Planned | Push Kraken triangulation results into `Telemetry.MessageLat/Lon` fields |

## Quick Start

### On the Raspberry Pi 5 (Airborne)
1. Plug the XBee Radio into any USB port on the Pi 5.
2. Install the MAVProxy/Translator autostart helpers:
   ```bash
   ./scripts/install-mavproxy-autostart.sh
   ```
3. Reboot and log into the GNOME desktop.
4. A terminal should open. MAVProxy will detect the vehicle, and the translator daemon will begin streaming data to the GCS.

### On the GCS Laptop (Ground)
1. Plug the **RFD-900x-US** radio modem into any USB port on the Windows laptop.
2. Navigate to `gcs-laptop-router/` and double-click **`launch.bat`**.
3. The script auto-detects the COM port and launches MAVProxy, splitting telemetry to:
   - `udp:127.0.0.1:14550` → QGroundControl
   - `udp:127.0.0.1:14551` → Kraken Triangulator / custom scripts
   - `udp:127.0.0.1:14601` → Software Team autonomy pipeline
4. **Leave the terminal open.** Then open QGroundControl — it auto-connects.

> ⚠️ **Important:** The MAVProxy router **must** be started before QGroundControl or any other MAVLink consumer. Windows enforces exclusive COM port locks.

## Architecture & Integration

The system operates as two parallel MAVProxy routing pipelines — one airborne on the Pi 5, one on the ground.

```
 ┌─────────────────────────┐              ┌──────────────────────────────┐
 │   Raspberry Pi 5        │   RFD-900x   │   GCS Windows Laptop         │
 │                         │  915 MHz RF  │                              │
 │  Pixhawk (TELEM2/UART)  │◄────────────►│  RFD-900x (USB / COM port)   │
 │         │                │              │         │                    │
 │    MAVProxy              │              │    MAVProxy                  │
 │    ├─ :14550 → Translator│              │    ├─ :14550 → QGround Ctrl  │
 │    ├─ :14540 → MAVSDK    │              │    ├─ :14551 → Kraken App    │
 │    ├─ :14601 → Cmd List. │              │    └─ :14601 → SW Team       │
 │    └─ :14602 → Reserved  │              │                              │
 │                         │              │                              │
 │  Translator → XBee ─────┼──── 2.4G ───►│  GCS Desktop App (Receiver)  │
 └─────────────────────────┘              └──────────────────────────────┘
```

### Dual-Control Arbitration (GCS vs. Autonomy)
Control authority is managed via standard ArduPilot flight modes:
- **Offboard/Guided Mode:** Software Team's autonomy engine has authority to navigate the drone.
- **Loiter/Manual/RTL Mode:** GCS or RC operator override — flight controller rejects autonomy commands.

### GCS Subteam API Integration
In March 2026, the GCS Subteam restructured their telemetry API (`InfrastructureInterface`) with nested payload definitions and renamed `.encode()` → `.Encode()`. The Pi 5 companion daemon now maps 4 layers deep into `sys.path` to resolve these dependencies. See `docs/gcs_integration_fixes.md` for the post-mortem.

## Repo Layout

```
├── scripts/                    # Pi 5 MAVProxy helpers & integration daemons
│   ├── install-mavproxy-autostart.sh
│   ├── ngcp-mavproxy-autostart.sh
│   ├── ngcp-mavproxy-telemetry.sh
│   ├── gcs_translator.py       # MAVLink → XBee translator (Pi 5)
│   └── gui_server.py           # Web-based telemetry monitor (Pi 5)
│
├── gcs-laptop-router/          # GCS Windows laptop MAVProxy router [NEW in v1.2.0]
│   ├── launch.bat              # One-click operator launcher
│   ├── launch_gcs_router.py    # COM port auto-detect + MAVProxy fan-out
│   ├── README.md               # Quick-start guide
│   └── GCS-Laptop-MAVProxy-Router.md  # Full integration wiki
│
├── docs/                       # SOPs and architecture documentation
│   └── wiki/                   # Wiki-ready markdown pages
│
├── CHANGELOG.md                # Version history and release notes
└── README.md                   # This file
```

> **Note:** The `kraken-triangulator/` app is developed in this repo but tracked on a separate branch cycle. It is excluded from the main `.gitignore` to keep the core repo lightweight.

## Optional: Tailscale VPN for Reliable SSH
Due to dynamic IP addressing (DHCP) on university networks and active blocking of mDNS, use **Tailscale** for reliable SSH access to the Pi 5. Tailscale assigns a permanent `100.x.x.x` IP that bypasses NAT and firewalls. Install on both your dev machine and the Pi 5, authenticate, and SSH using the Tailscale IP.

## Documentation
Refer to the dedicated [GitHub Wiki](https://github.com/ngcp-project/ngcp-pixhawk-pi5-companion/wiki) for detailed guides:
- [MAVProxy Autostart](https://github.com/ngcp-project/ngcp-pixhawk-pi5-companion/wiki/MAVProxy-Autostart-(New-landing-page))
- [GCS Laptop MAVProxy Router](https://github.com/ngcp-project/ngcp-pixhawk-pi5-companion/wiki/GCS-Laptop-MAVProxy-Router)
- [Changelog](https://github.com/ngcp-project/ngcp-pixhawk-pi5-companion/wiki/Changelog)

## Upcoming Work
- **Transmit API:** Backend endpoint in `kraken_server.py` to push triangulation coordinates to the Pi 5 via `/tmp/kraken_target.json`, feeding into `Telemetry.MessageLat`/`MessageLon` over the XBee.
- **Sensor Fusion Ingestion:** API endpoints to receive external sensor data from Software Team scripts into the Kraken Triangulator.
- **Process Watchdog:** `systemd` service for auto-restarting the telemetry pipeline on the Pi 5.
- **Dynamic UDP Port Manager:** Runtime registration for new MAVLink consumers without editing launch scripts.

## Status
- ✅ UART device mapping confirmed on Pi 5 (`/dev/ttyAMA0`)
- ✅ MAVLink frames verified on TELEM2
- ✅ MAVProxy receives heartbeat + parameters
- ✅ GCS Custom Translation Pipeline operational (MAVLink → UDP → Python → XBee)
- ✅ GCS Infrastructure API compatibility fixes resolved
- ✅ GCS Laptop MAVProxy Router verified with RFD-900x on COM13
- ✅ QGroundControl confirmed receiving live telemetry through the router
- ✅ Kraken Triangulator: LS-AoA, Bayesian Grid, spatial/temporal filtering operational

## Contributing
Update `docs/wiki` first, then mirror to the GitHub Wiki. See [CHANGELOG.md](CHANGELOG.md) for version history.
