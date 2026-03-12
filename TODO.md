# TODO — Known Issues & Upcoming Work

This file tracks pending compatibility fixes and planned feature work for the NGCP Pi 5 companion pipeline.

> **Rollback Tag:** `working-xbee-2.4ghz-pre-gcs-infra-refactor` (commit `e458ee1`)  
> Restore with: `git checkout working-xbee-2.4ghz-pre-gcs-infra-refactor -- scripts/gcs_translator.py`  
> This tag captures the last known-good state with 2.4 GHz XBee hardware and live GUI telemetry confirmed.

---

## 🔴 HIGH PRIORITY — GCS Compatibility Fixes

These issues were identified during a cross-repo audit on **2026-03-11** against the latest `ngcp-project/gcs-infrastructure` (commit `3d84531`).

### ~~1. Fix EmergencyStop Command ID in `gcs_translator.py`~~ ✅ DONE
**Fixed in commit after tag `working-xbee-2.4ghz-pre-gcs-infra-refactor`.**  
Changed `COMMAND_ID == 3` → `COMMAND_ID == 2` to match gcs-infrastructure spec.

---

### 2. Update Stale Import Paths in `gcs_translator.py` — ⏸️ DEFERRED
**File:** `scripts/gcs_translator.py` — lines 19–20  
**Status:** Deferred pending coordination with GCS Infrastructure subteam lead (Feniren / Aidan Sanders) to confirm expected integration pattern for the refactored `Application/Infrastructure/` layout.  
**Risk:** Low until Pi 5 receives a `git pull` of `gcs-infrastructure` that removes the old `Packet/` and `Communication/XBee/` paths. Current fallback `try/except` in the script will print an import warning and exit — **monitor this when the Pi is next updated.**

**Import change needed (do not apply until coordinated):**
```python
# STALE (current):
from Packet.Telemetry.Telemetry import Telemetry
from Communication.XBee.XBee import XBee

# TARGET (new gcs-infrastructure layout):
from InfrastructureInterface import LaunchXBee, SendCommand, ReceiveTelemetry
```

---

### ~~3. Fix XBee Frame Field Name Mismatch~~ ✅ DONE
**Fixed in commit after tag `working-xbee-2.4ghz-pre-gcs-infra-refactor`.**  
Updated `MockXBee.retrieve_data()` to set `frame.received_data` and changed `hasattr` check from `'data'` → `'received_data'` throughout. Mock and real hardware now share the same interface.

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
