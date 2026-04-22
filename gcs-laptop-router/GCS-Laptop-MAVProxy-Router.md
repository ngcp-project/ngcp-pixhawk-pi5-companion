# GCS Laptop MAVProxy Router — Setup & Integration Guide

> **Audience:** GCS Operators, Software Team, Kraken RF Team  
> **Last Updated:** April 2026  
> **Repository:** [`ngcp-project/ngcp-pixhawk-pi5-companion`](https://github.com/ngcp-project/ngcp-pixhawk-pi5-companion)

---

## 1. Problem Statement

The **RFD-900x-US** radio modem is the primary air-to-ground telemetry link between the UAV's Pixhawk flight controller and the Ground Control Station (GCS) laptop. When this radio is plugged into a Windows machine, the operating system assigns it a single COM port (e.g. `COM13`).

**The core issue:** Windows enforces an **exclusive lock** on serial COM ports. If QGroundControl opens the port first, no other application can access it. Without a router, **only one application at a time** can receive live MAVLink telemetry from the aircraft.

Our ground station requires **simultaneous access** by:

| Consumer | Purpose |
|---|---|
| **QGroundControl** | Primary flight monitoring, mission planning, manual override |
| **Kraken Triangulator** | RF signal localization dashboard (bearing + triangulation display) |
| **Software Team Scripts** | Autonomous decision-making, waypoint injection, sensor fusion |

---

## 2. Solution: MAVProxy as a Local UDP Router

We use **MAVProxy** — the same tool already running on the Raspberry Pi 5 companion computer — as a local multiplexer on the GCS laptop. MAVProxy exclusively claims the RFD-900x COM port, then fans out identical copies of the MAVLink stream to multiple local UDP endpoints.

### Architecture Diagram

```
                     ┌──────────────────────────────────────────────┐
                     │           GCS Windows Laptop                 │
                     │                                              │
  RFD-900x USB      │   ┌──────────────────────┐                   │
  ──────────────────►│   │    MAVProxy Router    │                   │
  (COM13, 57600bd)   │   │  (launch_gcs_router)  │                   │
                     │   └──────┬───┬───┬────────┘                   │
                     │          │   │   │                            │
                     │          ▼   ▼   ▼                            │
                     │   ┌──────┐ ┌──────┐ ┌──────┐                  │
                     │   │:14550│ │:14551│ │:14601│                  │
                     │   └──┬───┘ └──┬───┘ └──┬───┘                  │
                     │      │        │        │                      │
                     │      ▼        ▼        ▼                      │
                     │  QGround   Kraken    Software                 │
                     │  Control   Triang.   Team                     │
                     │            App       Scripts                  │
                     └──────────────────────────────────────────────┘
```

### Pre-Allocated UDP Port Map

| UDP Port | Assigned To | Protocol | Notes |
|---|---|---|---|
| `udp:127.0.0.1:14550` | **QGroundControl** | Raw MAVLink | QGC auto-connects to this port by default. No configuration needed. |
| `udp:127.0.0.1:14551` | **Kraken Triangulator** | Raw MAVLink | Available for the triangulation backend or any custom Python GCS script. |
| `udp:127.0.0.1:14601` | **Software Team** | Raw MAVLink | Dedicated port for autonomy scripts, command listeners, and sensor fusion. |

> **Important:** All ports use `127.0.0.1` (localhost only). No telemetry is exposed to the network. This is strictly a local fan-out.

---

## 3. How to Launch the Router

### Method 1: Double-Click the Batch File (Recommended for Operators)

1. Navigate to `gcs-laptop-router/` in Windows Explorer.
2. Double-click **`launch.bat`**.
3. The script will:
   - Verify Python is installed.
   - Auto-install missing dependencies (`pyserial`, `MAVProxy`, `prompt_toolkit`, `wxPython`).
   - Scan the USB hardware registry for FTDI devices (the RFD-900x chipset).
   - Auto-detect the correct COM port.
   - Launch MAVProxy with all three UDP outputs.
4. **Leave the terminal window open** for the entire flight. Closing it kills all telemetry streams.

### Method 2: Manual Terminal Command (Fallback)

If auto-detection fails, look up the COM port in **Windows Device Manager** → Ports (COM & LPT), then run:

```powershell
mavproxy.py --master=COM13 --baudrate=57600 --out=udp:127.0.0.1:14550 --out=udp:127.0.0.1:14551 --out=udp:127.0.0.1:14601
```

Replace `COM13` with your actual port number.

### Method 3: Python Script Directly

```powershell
cd gcs-laptop-router
python launch_gcs_router.py
```

---

## 4. For the Software Team — Connecting Your Scripts

### What Changed

Previously, your scripts connected directly to the RFD-900x serial port. **This will no longer work** because MAVProxy now holds the exclusive lock on the COM port. You must connect to the **UDP output** instead.

### How to Connect via `pymavlink`

Replace your existing MAVLink connection line:

```python
# OLD — Direct serial (WILL FAIL if MAVProxy is running)
mav = mavutil.mavlink_connection('/dev/ttyUSB0', baud=57600)
# or
mav = mavutil.mavlink_connection('COM13', baud=57600)
```

With the UDP listener:

```python
# NEW — Connect to the MAVProxy UDP output on port 14601
from pymavlink import mavutil

mav = mavutil.mavlink_connection('udp:127.0.0.1:14601')
mav.wait_heartbeat()
print(f"Connected! System {mav.target_system}, Component {mav.target_component}")
```

### Important Notes for Software Team

1. **Your port is `14601`.** Do NOT use `14550` (that's QGroundControl) or `14551` (that's the Kraken app).
2. **Bidirectional by default.** MAVProxy UDP outputs are bidirectional. You can both **read** telemetry and **send** MAVLink commands (e.g., waypoints, mode changes) through the same connection. Commands sent to `udp:127.0.0.1:14601` will be forwarded by MAVProxy back through the RFD-900x to the flight controller.
3. **Launch order matters.** The MAVProxy router **must** be started before your scripts. If your script starts first and binds port `14601`, MAVProxy will fail to output to that port.
4. **No code changes needed for `mavutil` message parsing.** The MAVLink protocol is identical whether it comes from a serial port or a UDP socket. All your existing `recv_match()`, `GLOBAL_POSITION_INT`, `HEARTBEAT`, etc. logic works unchanged.

### Minimal Working Example

```python
#!/usr/bin/env python3
"""software_listener.py — Minimal example for Software Team."""
from pymavlink import mavutil
import time

# Connect to the Software Team's dedicated MAVProxy output
mav = mavutil.mavlink_connection('udp:127.0.0.1:14601')
print("Waiting for heartbeat...")
mav.wait_heartbeat()
print(f"Heartbeat received (system={mav.target_system})")

while True:
    msg = mav.recv_match(blocking=True, timeout=1.0)
    if msg:
        msg_type = msg.get_type()
        if msg_type == 'GLOBAL_POSITION_INT':
            lat = msg.lat / 1e7
            lon = msg.lon / 1e7
            alt = msg.alt / 1000.0
            print(f"Position: {lat:.6f}, {lon:.6f} | Alt: {alt:.1f}m")
        elif msg_type == 'HEARTBEAT':
            armed = msg.base_mode & 0x80
            print(f"Heartbeat — Armed: {bool(armed)}")
```

### Sending Commands Back to the Flight Controller

```python
# Example: Set the flight mode to GUIDED
mav.set_mode_apm(15)  # 15 = GUIDED mode for ArduPilot

# Example: Arm the vehicle
mav.arducopter_arm()

# Example: Send a waypoint command
mav.mav.mission_item_int_send(
    mav.target_system, mav.target_component,
    0,  # seq
    mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
    mavutil.mavlink.MAV_CMD_NAV_WAYPOINT,
    2, 0,  # current=2 (guided), autocontinue
    0, 0, 0, 0,
    int(33.8823 * 1e7),  # lat
    int(-117.8825 * 1e7),  # lon
    50  # alt (meters)
)
```

---

## 5. Parallel Architecture — Pi 5 vs. GCS Laptop

This router mirrors the existing MAVProxy setup already running on the Raspberry Pi 5 companion computer. Both systems use the same fan-out pattern, but serve different sides of the telemetry link:

| Component | Pi 5 (Airborne) | GCS Laptop (Ground) |
|---|---|---|
| **Radio** | RFD-900x via UART (`/dev/ttyAMA0`) | RFD-900x via USB (`COM13`) |
| **MAVProxy Script** | `scripts/ngcp-mavproxy-telemetry.sh` | `gcs-laptop-router/launch_gcs_router.py` |
| **Port: GCS Translator** | `udp:127.0.0.1:14550` | — |
| **Port: QGroundControl** | — | `udp:127.0.0.1:14550` |
| **Port: Software Team** | `udp:127.0.0.1:14601` | `udp:127.0.0.1:14601` |
| **Port: Kraken / Custom** | `udp:127.0.0.1:14602` | `udp:127.0.0.1:14551` |

---

## 6. Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| `No COM ports found!` | RFD-900x not plugged in or driver missing | Plug in the radio. Install [FTDI VCP drivers](https://ftdichip.com/drivers/vcp-drivers/) if needed. |
| `NoConsoleScreenBufferError` | Script was run from a non-interactive shell (e.g. IDE terminal) | Run `launch.bat` by double-clicking it in Explorer, or use `cmd.exe` directly. |
| QGroundControl not connecting | MAVProxy not started, or QGC opened before MAVProxy | Start the router first, then open QGC. QGC auto-detects `udp:14550`. |
| `Port already in use` | Another application bound the port before MAVProxy | Close QGC or other MAVLink consumers, then restart the router. |
| Script can't find `mavproxy.py` | MAVProxy not installed or not on PATH | Run `pip install MAVProxy prompt_toolkit wxPython` |
| Multiple FTDI devices detected | Multiple USB-serial adapters plugged in | The script will prompt you to choose. Pick the RFD-900x entry. |

---

## 7. Dependencies

Install all required Python packages with:

```powershell
pip install pyserial MAVProxy prompt_toolkit wxPython pymavlink
```

**Minimum Python version:** 3.9+

---

## 8. File Inventory

| File | Purpose |
|---|---|
| `gcs-laptop-router/launch_gcs_router.py` | Python COM port auto-detector & MAVProxy launcher |
| `gcs-laptop-router/launch.bat` | Windows batch helper — double-click to start |
| `gcs-laptop-router/README.md` | Quick-start README for the directory |
| `gcs-laptop-router/GCS-Laptop-MAVProxy-Router.md` | This document (GitHub Wiki page) |
