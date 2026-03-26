# GCS Telemetry Pipeline Fixes

This document outlines the root cause debugging and final successful deployment fixes applied to restoring the Raspberry Pi 5 Telemetry GUI Pipeline on `Mar 25, 2026`.

## The Issue
After integrating the companion scripts with the **GCS Subteam's** newest `InfrastructureInterface` submodules, the headless data-translation node (`gcs_translator.py`) silently crashed on launch. Because the script died before establishing a MAVLink heartbeat from the `/dev/ttyAMA0` serial port, it failed to construct the `.json` stream. Consequently, the user-facing web dashboard (`gui_server.py`) continually presented an `OFFLINE` status.

## Root Causes Identified
Our deep dive confirmed that the physical hardware connection between the Pixhawk `TELEM2` UART pins and the Pi 5 GPIO header (`/dev/ttyAMA0`) was flawless. The break was entirely software-induced.

### 1. Nested API `ImportError`
The GCS Subteam recently migrated the core telemetry packet definitions out of their top-level root module and buried them within nested folders (`lib/gcs-packet/Packet/Telemetry`).
Because our background daemon was only injecting `sys.path.append('gcs-infrastructure')`, Python fatally threw a `ModuleNotFoundError` completely aborting the pipeline before boot.
**Fix:** The deployment explicitly injects four full-path API resolution links covering `gcs-packet` and `Application` directories to strictly resolve the new software mappings.

### 2. Capitalization `AttributeError` 
After overriding the import crash, a secondary bug arrested the script directly during data transmission: `Telemetry object has no attribute 'encode'`. 
The companion software assumed the `Telemetry` structure required standard python dictionary serialization via lowercase `.encode()`. However, the Subteam's `Telemetry.py` interface strictly implements a customized serialization function titled **`.Encode()`**. 
**Fix:** Refactored translator logic to accurately call `.Encode()`, avoiding the `AttributeError` exception stack trace.

## Final Result
Both edge-cases injected by external module reorganizations were fully patched. Re-triggering `./ngcp-mavproxy-telemetry.sh` autonomously synchronizes live flight data frames into the localhost Firefox GUI.
