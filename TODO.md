# TODO — Known Issues & Upcoming Work

This file tracks pending compatibility fixes and planned feature work for the NGCP Pi 5 companion pipeline.

---

## 🔴 HIGH PRIORITY — GCS Compatibility Fixes

These issues were identified during a cross-repo audit on **2026-03-11** against the latest `ngcp-project/gcs-infrastructure` (commit `3d84531`).

### 1. Fix EmergencyStop Command ID in `gcs_translator.py`
**File:** `scripts/gcs_translator.py` — line 73  
**Issue:** Our code treats Command ID `3` as EmergencyStop, but the `gcs-infrastructure` README specifies:
- ID `1` = Heartbeat
- ID `2` = Emergency Stop ← **correct ID**
- ID `3` = Keep In Zone

**Fix needed:**
```python
# WRONG (current):
if COMMAND_ID == 3 and len(data) >= 3:

# CORRECT:
if COMMAND_ID == 2 and len(data) >= 3:
```

---

### 2. Update Stale Import Paths in `gcs_translator.py`
**File:** `scripts/gcs_translator.py` — lines 19–20  
**Issue:** Our imports reference old module paths that no longer match the refactored `gcs-infrastructure` repo layout:
```python
# STALE (current):
from Packet.Telemetry.Telemetry import Telemetry
from Communication.XBee.XBee import XBee
```
The repo was refactored. GCS now exposes everything through:
```
Application/Infrastructure/InfrastructureInterface.py
  → LaunchXBee(PORT)
  → SendCommand(Command, Vehicle)
  → ReceiveTelemetry()
```
**Fix needed:** Update `sys.path.append` to point to `Application/Infrastructure/` and use the `InfrastructureInterface` API — coordinate with the GCS Infrastructure subteam lead (Feniren / Aidan Sanders) before changing to confirm the expected integration pattern.

---

### 3. Fix XBee Frame Field Name Mismatch
**File:** `scripts/gcs_translator.py` — line 154  
**Issue:** Our code reads `frame.data` when processing real XBee frames, but `gcs-infrastructure`'s `GCSXBee.py` populates `Data.received_data` (not `.data`). Our mock works because `MockXBee` manually sets `.data`, but real hardware will silently drop all incoming commands.

**Fix needed:**
```python
# WRONG (current — only works with MockXBee):
if frame and hasattr(frame, 'data'):
    cmd_event = process_xbee_command(frame.data, ...)

# CORRECT (matches real XBee library):
if frame and hasattr(frame, 'received_data'):
    cmd_event = process_xbee_command(frame.received_data, ...)
```

---

## 🟡 MEDIUM PRIORITY — Planned Features

### 4. Automatic UDP Port Registration for External Scripts
**Context:** The MAVProxy pipeline currently has pre-configured static output ports (`14550`, `14601`, `14602`). Future scripts from the Software Team or other subteams should not need to manually edit the launch script to add a new UDP output.

**Planned Feature:** A dynamic UDP port manager that:
- Listens for scripts announcing themselves (e.g., via a local socket or config file)
- Calls `mavproxy.py --out udp:127.0.0.1:<PORT>` dynamically or manages a multiplexer
- See `README.md` → **Upcoming Features** section for more context

---

### 5. GUI Panel Showing Active UDP Ports in `gui_server.py`
**Context:** The GCS Telemetry Monitor (`gui_server.py`) currently only shows telemetry data. There is no visibility into which UDP ports are currently active and receiving MAVLink data.

**Planned Feature:** A "Port Monitor" panel within the existing web GUI (`web/index.html`) that:
- Queries a new `/ports` endpoint from `gui_server.py`
- Displays a live list of active UDP listeners (e.g., `14550 → gcs_translator.py`, `14601 → command_listener.py`)
- Highlights any port that has gone silent (no heartbeat in >5s)

---

## ✅ Completed

- [x] MAVProxy autostart on GNOME desktop login
- [x] `gcs_translator.py` MAVLink → GCS packet translation
- [x] Bidirectional XBee command reception (mock via UDP)
- [x] Firefox `--new-tab` integration with KrakenSDR browser
- [x] `wait` added to autostart script to prevent early process kill
- [x] Tailscale VPN documented in README
- [x] `gcs_translator.py` marked executable via git file mode
