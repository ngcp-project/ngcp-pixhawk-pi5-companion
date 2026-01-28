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
All step-by-step procedures and the validated “known-good” setup are maintained in the **GitHub Wiki**.

➡️ **Go to the Wiki for the full guide, commands, and SOPs**  
(Repo → **Wiki** tab)

Suggested reading order in the Wiki:
1. **UART MAVLink Validation (TELEM2 ↔ Pi 5)**  
2. **Quick Reference / Golden Commands**  
3. **Troubleshooting Decision Tree**  
4. **Telemetry Routing to GCS (Serial → UDP/TCP)** *(next phase)*

---

## Current Status
- ✅ UART device mapping confirmed on Pi 5 (`/dev/ttyAMA0`)  
- ✅ MAVLink frames observed on TELEM2 (raw byte validation)  
- ✅ MAVProxy receives heartbeat + parameters over UART (end-to-end link validated)

---

## Repo Layout (suggested)
- `README.md` – overview + pointers to the Wiki (this file)
- `docs/` – optional exported SOPs (if we later mirror wiki pages)
- `scripts/` – helper scripts (byte sniffers, port checks, launch commands)
- `configs/` – known-good config snippets (Pi boot config lines, systemd notes, etc.)

---

## Contributing / Updating the SOP
If you improve a procedure or discover a new failure mode, please update the **Wiki page first** so future engineers don’t repeat the same debugging.

---
