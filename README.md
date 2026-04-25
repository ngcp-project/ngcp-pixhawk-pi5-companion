# NGCP MRA — Pixhawk / Pi 5 Companion Computer

> **Version:** v1.9.4 &nbsp;|&nbsp; **Branch:** `main`

This repository contains the **flight-side telemetry pipeline** for the NGCP Multi-Rotor Aircraft (MRA). It bridges MAVLink telemetry from the Cube Orange flight controller, through a Raspberry Pi 5 companion computer, over an **XBee XR 900 MHz** radio link, to the Ground Control Station (GCS).

MRA is a **read-only consumer** of the `gcs-infrastructure` library (owned by the GCS Subteam). This repo does not modify that library; it consumes its public API (`InfrastructureInterface`) to transmit telemetry and receive commands.

> Scripts and workflow are tailored for CPP NGCP MRA. MEA teams may use this repo as a reference template but should adapt it for their own hardware configuration.

---

## Features

| Component | Status | Description |
|---|---|---|
| **Pi 5 MAVProxy Pipeline** | ✅ Operational | UART → MAVProxy → multi-UDP fan-out (`14550`, `14540`, `14601–14607`) |
| **GCS Translator Daemon** | ✅ Operational | MAVLink → 72-byte `Telemetry` struct → XBee XR 900 MHz RF transmission |
| **GCS Infrastructure API** | ✅ Operational | `gcs-infrastructure` registered as git submodule; `LaunchVehicleXBee`, `SendTelemetry`, `ReceiveCommand(DecodeFormat.Class)` |
| **GCS Command Handling** | ✅ Operational | `Heartbeat`, `EmergencyStop` (→ MAVLink flight termination); `AddZone` and `PatientLocation` logged, MAVLink actions pending |
| **Kraken Triangulator** | ✅ Operational | Web-based RF triangulation dashboard with LS-AoA, Bayesian grid, and spatial filtering |
| **Kraken → Telemetry Injection** | ✅ Operational | `DEBUG_VECT KRAKEN_TGT` intercept feeds triangulation result into `Telemetry.MessageLat/Lon` |
| **Vehicle Telemetry Monitor** | ✅ Operational | `xbee_telemetry_monitor.py` — diagnostic GCS-side receiver, stand-in for `GCSTest.py` |
| **GCS Laptop MAVProxy Router** | ✅ Operational | Auto-detects XBee XR COM port, fans out MAVLink to QGC, Kraken, and Software Team |

---

## Architecture

The pipeline has two ends connected by the XBee XR 900 MHz RF link:

```
 ┌──────────────────────────────────┐              ┌─────────────────────────────────┐
 │   Raspberry Pi 5  (Airborne)     │              │   GCS Windows Laptop  (Ground)  │
 │                                  │              │                                 │
 │  Cube Orange FC                  │  XBee XR     │  XBee XR 900 MHz                │
 │  (TELEM2 / UART)                 │  900 MHz RF  │  (USB / COM port)               │
 │         │                        │◄────────────►│         │                       │
 │    MAVProxy                      │              │    GCSTest.py  (or GCS App)     │
 │    ├─ :14550 → gcs_translator.py │              │    ├─ SendCommand()             │
 │    ├─ :14540 → MAVSDK            │              │    └─ ReceiveTelemetry()        │
 │    ├─ :14601 → Cmd Listener      │              │                                 │
 │    └─ :14602–14607 → SW Team     │              │    QGroundControl (:14550)      │
 │                                  │              │    Kraken App    (:14551)       │
 │  gcs_translator.py               │              │    SW Team       (:14601)       │
 │  ├─ LaunchVehicleXBee()          │              │                                 │
 │  ├─ SendTelemetry(Telemetry)  ───┼──────────────►                                 │
 │  └─ ReceiveCommand(Decode.Class) │◄─────────────┼─ Commands from GCS              │
 └──────────────────────────────────┘              └─────────────────────────────────┘
```

**How it works end-to-end:**
1. The Cube Orange streams MAVLink over UART → MAVProxy fans it out to UDP ports.
2. `gcs_translator.py` reads MAVLink messages, maps fields into a `Telemetry()` object, and calls `SendTelemetry()` at 5 Hz — the gcs-infrastructure library encodes the 72-byte packet and transmits via the XBee XR radio.
3. Commands from the GCS arrive via the same XBee RF link; `ReceiveCommand(DecodeFormat.Class)` returns a typed command object for dispatch.
4. The Kraken Triangulator injects estimated target coordinates into `Telemetry.MessageLat/Lon` via a `DEBUG_VECT KRAKEN_TGT` MAVLink message, which `gcs_translator.py` intercepts.

---

## GCS Infrastructure API

`gcs-infrastructure` is registered as a **git submodule** at the repo root, per the GCS Subteam's setup instructions.

```
gcs-infrastructure/               ← read-only submodule (GCS Subteam repo)
├── Application/
│   └── Infrastructure/
│       ├── InfrastructureInterface.py  ← LaunchVehicleXBee, SendTelemetry, ReceiveCommand
│       ├── VehicleXBee.py              ← internal XBee TX/RX thread management
│       └── GCSXBee.py
├── TestScripts/
│   ├── GCSTest.py                ← GCS reference endpoint (commands out, telemetry in)
│   └── VehicleTest.py            ← Vehicle reference endpoint (telemetry out, commands in)
└── lib/
    ├── gcs-packet/               ← Telemetry, Command, Enum class definitions
    └── xbee-python/              ← XBee serial driver
```

**Initialise the submodule after cloning:**
```bash
git submodule update --init --recursive
```

**Important — module aliasing:** `Telemetry` must be imported as `from Telemetry.Telemetry import Telemetry`, not via the `Packet.*` namespace. Python caches these as separate class objects; `isinstance()` checks inside `VehicleXBee.RunTelemetryThread` will silently fail (dropping all packets) if the import path differs. See `gcs_library_bug_log.md` → Bug #001.

---

## Quick Start

### On the Raspberry Pi 5 (Airborne)

1. Clone the repo and initialise submodules:
   ```bash
   git clone https://github.com/ngcp-project/ngcp-pixhawk-pi5-companion.git
   cd ngcp-pixhawk-pi5-companion
   git submodule update --init --recursive
   ```
2. Plug the **XBee XR 900 MHz** radio into a USB port on the Pi 5.
3. Install the MAVProxy/Translator autostart helpers:
   ```bash
   ./scripts/install-mavproxy-autostart.sh
   ```
4. Reboot. MAVProxy will auto-start, detect the vehicle on `/dev/ttyAMA0`, and `gcs_translator.py` will begin streaming telemetry to the GCS.

### On the GCS Laptop (Ground)

1. Plug the **XBee XR 900 MHz** radio into a USB port on the laptop.
2. To verify the RF link without the full GCS app, run:
   ```bash
   # From gcs-infrastructure/ (must be on PATH per setup instructions)
   python TestScripts/GCSTest.py
   # or MRA diagnostic stand-in:
   python scripts/xbee_telemetry_monitor.py [COM_PORT]
   ```
3. For QGroundControl: navigate to `gcs-laptop-router/` and run **`launch.bat`**. It auto-detects the COM port and fans MAVLink out to QGC, Kraken, and the Software Team.

> ⚠️ The MAVProxy router must be started **before** QGroundControl. Windows enforces exclusive COM port locks.

---

## Repo Layout

```
ngcp-pixhawk-pi5-companion/
│
├── gcs-infrastructure/             ← GCS Subteam library (git submodule, read-only)
│
├── scripts/                        ← Pi 5 flight-side daemons
│   ├── gcs_translator.py           ← Main pipeline: MAVLink → Telemetry → XBee (Pi 5)
│   ├── xbee_telemetry_monitor.py   ← Diagnostic GCS-side receiver (laptop, stand-in for GCSTest.py)
│   ├── gui_server.py               ← Web-based telemetry state server (Pi 5)
│   ├── install-mavproxy-autostart.sh
│   ├── ngcp-mavproxy-autostart.sh
│   └── ngcp-mavproxy-telemetry.sh
│
├── gcs-laptop-router/              ← Windows laptop MAVProxy router
│   ├── launch.bat                  ← One-click operator launcher
│   ├── launch_gcs_router.py        ← COM port auto-detect + MAVProxy fan-out
│   └── README.md
│
├── kraken-triangulator/            ← RF triangulation app (separate submodule)
├── web/                            ← Pi 5 web dashboard (GCS view)
├── docs/                           ← SOPs and architecture documentation
│   └── wiki/
├── CHANGELOG.md
└── README.md
```

---

## Status

- ✅ UART device mapping confirmed on Pi 5 (`/dev/ttyAMA0`)
- ✅ MAVLink frames verified on TELEM2
- ✅ MAVProxy receives heartbeat + parameters
- ✅ GCS Translator pipeline operational (MAVLink → UDP → gcs_translator.py → XBee XR)
- ✅ `gcs-infrastructure` registered as proper git submodule
- ✅ `ReceiveCommand(DecodeFormat.Class)` API compliance verified
- ✅ GCS Laptop MAVProxy Router verified with XBee XR on COM5
- ✅ QGroundControl confirmed receiving live telemetry through the router
- ✅ Kraken Triangulator: LS-AoA, Bayesian Grid, spatial/temporal filtering operational
- ✅ Kraken target coordinates injecting into `Telemetry.MessageLat/Lon` over XBee

## Upcoming Work

- **AddZone MAVLink action:** Wire `AddZone` command to `MAV_CMD_DO_FENCE_ENABLE` / `MISSION_ITEM_INT` fence upload.
- **PatientLocation forward:** Forward GCS-pushed patient coordinates to autopilot or Kraken overlay.
- **Process Watchdog:** `systemd` service for auto-restarting `gcs_translator.py` on the Pi 5.
- **Dynamic UDP Port Manager:** Runtime registration for new MAVLink consumers without editing launch scripts.

## Contributing

Update `docs/wiki` first, then mirror to the GitHub Wiki. See [CHANGELOG.md](CHANGELOG.md) for version history. Do not commit to `gcs-infrastructure/` — it is a read-only submodule.
