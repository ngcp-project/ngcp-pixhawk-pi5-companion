# Changelog

All notable changes to the **ngcp-pixhawk-pi5-companion** project are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versioned per [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [v1.2.0] — 2026-04-10

### Added
- **GCS Laptop MAVProxy Router** (`gcs-laptop-router/`): A new directory containing a complete Windows-side MAVLink routing solution for the Ground Control Station laptop.
  - `launch_gcs_router.py`: Python script that auto-detects the RFD-900x COM port via FTDI USB hardware scanning and launches MAVProxy with UDP fan-out.
  - `launch.bat`: One-click Windows batch launcher for field operators. Auto-installs dependencies (`pyserial`, `MAVProxy`, `prompt_toolkit`, `wxPython`).
  - Pre-allocated UDP port map: `14550` (QGroundControl), `14551` (Kraken Triangulator), `14601` (Software Team).
  - `GCS-Laptop-MAVProxy-Router.md`: Comprehensive wiki-ready integration guide with architecture diagrams, Software Team migration instructions, code examples, and troubleshooting table.
- **GitHub Wiki page**: [GCS Laptop MAVProxy Router](https://github.com/ngcp-project/ngcp-pixhawk-pi5-companion/wiki/GCS-Laptop-MAVProxy-Router) published for cross-team reference.

### Changed
- `.gitignore`: Added MAVProxy auto-generated artifacts (`mav.parm`, `mav.tlog`) in `gcs-laptop-router/`. Added `gcs-desktop-app/` and `gcs-infrastructure/` to ignored local sub-repos.
- `README.md`: Complete overhaul reflecting v1.2.0 features, dual-pipeline architecture diagram, updated repo layout, and linked wiki documentation.

---

## [v1.1.0] — 2026-03-25

### Added
- **Kraken Triangulator Algorithms**: Implemented and documented the full triangulation math engine:
  - **LS-AoA** (Weighted Least Squares Angle of Arrival): Multi-station bearing intersection solver.
  - **Bayesian Grid**: Probabilistic spatial heatmap estimation for high-multipath environments.
  - **Midpoint**: Simple geometric midpoint of pairwise bearing intersections.
  - **Signal Filtering**: Ray-AABB geofencing, angular separation gating, spatial median clustering for outlier rejection.
- **Estimation Tab**: New UI tab for tracking and logging significant triangulation results with map plotting.
- **Spatial Filtering Tools**: Interactive Draw Area (AABB rectangle) and Draw Polygon tools for bearing ray clipping.
- **Playback System**: Full mock data playback controls (play/pause/seek/speed) for offline bearing log analysis.

### Changed
- `ngcp-mavproxy-telemetry.sh`: Expanded MAVProxy outputs to include UDP ports `14601` and `14602` for Software Team pipeline.

### Fixed
- XBee MAC address targeting: Fallback to universal broadcast (`000000000000FFFF`) when specific GCS MAC fails.
- Telemetry serialization: Resolved property naming mismatch causing silent encoding failures.

---

## [v1.0.0] — 2026-03-06

### Added
- **Pi 5 MAVProxy Pipeline**: Initial UART → MAVProxy → UDP routing from Pixhawk TELEM2 (`/dev/ttyAMA0`).
- **GCS Translator Daemon** (`gcs_translator.py`): MAVLink → custom 72-byte `Telemetry` struct → XBee API serial transmission.
- **GCS Command Receiver**: Incoming XBee commands (Heartbeat, EmergencyStop) parsed and forwarded as MAVLink commands to the flight controller.
- **MockXBee**: UDP-based mock XBee interface for local development without physical hardware.
- **Autostart Helpers**: `install-mavproxy-autostart.sh` for boot-time MAVProxy + Translator launch on the Pi 5.
- **GUI Telemetry Monitor** (`gui_server.py`): Lightweight web dashboard reading `/tmp/telemetry.json` for real-time field monitoring.

### Fixed
- GCS Infrastructure API compatibility: Resolved crash caused by `InfrastructureInterface` restructuring (nested `sys.path` mapping, `.encode()` → `.Encode()` rename).

---

## Remaining Work

The following items are planned but not yet implemented:

### High Priority
- [ ] **Transmit API Endpoint**: Add `POST /api/transmit` route to `kraken_server.py` that writes selected triangulation coordinates to `/tmp/kraken_target.json`.
- [ ] **GCS Translator Integration**: Update `gcs_translator.py` to read `/tmp/kraken_target.json` and populate `Telemetry.MessageLat`, `Telemetry.MessageLon`, and `Telemetry.MessageFlag` (flag value TBD — must confirm with GCS Subteam whether `1=Package` or `2=Patient` is appropriate).
- [ ] **Frontend Transmit Button**: Replace the mocked `console.log`/`alert` in `main.js` with a `fetch('/api/transmit')` call and visual blink/highlight feedback on the button.

### Medium Priority
- [ ] **Sensor Fusion Ingestion API**: Endpoint in `kraken_server.py` or `gcs_translator.py` to receive external positioning data from Software Team scripts.
- [ ] **Process Watchdog**: `systemd` service units for auto-restarting `mavproxy`, `gcs_translator.py`, and `gui_server.py` on the Pi 5.
- [ ] **Persistent State Directory**: Move runtime state files from `/tmp/` to `/var/run/ngcp/` to survive Pi 5 reboots.

### Low Priority
- [ ] **Dynamic UDP Port Manager**: Runtime registration for new MAVLink consumers without editing launch scripts.
- [ ] **Active UDP Port Monitor**: GUI panel in `gui_server.py` showing per-port heartbeat status.
- [ ] **Confirm MessageFlag with GCS Subteam**: Check latest `gcs-infrastructure` repo for which `MessageFlag` value (1 or 2) is appropriate for RF target coordinates.
