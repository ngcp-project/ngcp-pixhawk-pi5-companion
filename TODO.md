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

### 4. Automatic UDP Port Registration for External Scripts — ⏸️ DEFERRED
**Status:** Deferred pending coordination with the **Software Team and Autonomy Team** (2026-03-11).  
**Reason:** Switching from hardcoded ports to a hub-based model changes how all external scripts receive MAVLink data. Activating this without prior notice would silently break `command_listener.py` (port 14601) and the Autonomy Engine (port 14602).  
**Code Status:** `scripts/mavlink_hub.py` is written and tested (7-unit test suite passes), but is **not wired into the launch script**. No changes are active in production.

**Before activating:**
- Coordinate with Software/Autonomy leads to agree on the migration timeline
- Ensure all consumer scripts are updated to call `register_with_hub()` before switching the launch script
- Reference the design in `scripts/mavlink_hub.py` and `scripts/test_mavlink_hub.py`

---

### 5. GUI Panel Showing Active UDP Ports in `gui_server.py` — ⏸️ DEFERRED
**Status:** Deferred — depends on TODO #4 (hub activation). Deferred for the same reason.  
**Code Status:** Port Monitor panel is implemented in the web GUI (`web/index.html`, `web/app.js`, `web/style.css`) and `gui_server.py` has a `/ports` endpoint. Both currently render **mock data** gracefully when the hub is not running. No functional regression.

---

## ✅ Completed

- [x] MAVProxy autostart on GNOME desktop login
- [x] `gcs_translator.py` MAVLink → GCS packet translation
- [x] Bidirectional XBee command reception (mock via UDP)
- [x] Firefox `--new-tab` integration with KrakenSDR browser
- [x] `wait` added to autostart script to prevent early process kill
- [x] Tailscale VPN documented in README
- [x] `gcs_translator.py` marked executable via git file mode
