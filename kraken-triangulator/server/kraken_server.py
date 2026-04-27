#!/usr/bin/env python3
"""
kraken_server.py — KrakenSDR Triangulator Server (XBee-Only Architecture)
=========================================================================
Single mobile KrakenSDR model with playback controls.

RF Architecture (v2.0+):
  This server does NOT use MAVLink or pymavlink. Target coordinates are
  exposed via GET /api/target for the GCS Dashboard to poll and relay to
  the Pi 5 via XBee PatientLocation command (Command ID 5).
  The RFD-900x modem and MAVProxy Router are no longer required.

API:
  GET  /api/bearings           — current observation history
  GET  /api/target             — latest Kraken target for GCS Dashboard
  POST /api/transmit           — store target coordinates from UI
  GET  /api/playback           — playback state
  POST /api/playback           — send playback command

Usage:
    python server/kraken_server.py
    KRAKEN_API_URL=http://<pi-ip>:8080 python server/kraken_server.py
"""

import json
import os
import sys
import time
import socket
import threading
import logging
from pathlib import Path
from datetime import datetime, timezone

try:
    from flask import Flask, jsonify, request, send_from_directory
    from flask_cors import CORS
except ImportError:
    print("ERROR: Missing dependencies. Run: pip install -r requirements.txt")
    sys.exit(1)

try:
    import requests as req_lib
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

# NOTE (XBee migration): pymavlink is no longer required on the GCS laptop.
# Target coordinates are relayed to Pi 5 by the GCS Dashboard via XBee
# PatientLocation command, not via MAVLink upstream through RFD-900x.

# ── Configuration ──────────────────────────────────────────────────────────────
PORT            = int(os.environ.get("PORT", 5050))
KRAKEN_API_URL  = os.environ.get("KRAKEN_API_URL", "")
BASE_ADVANCE_S  = float(os.environ.get("ADVANCE_EVERY_S", "0.5"))

BASE_DIR        = Path(__file__).resolve().parent.parent
MOCK_FILE_NAME  = os.environ.get("BEARINGS_FILE", "bearings_20260313_154333.json")
MOCK_DATA_PATH  = BASE_DIR / "data" / MOCK_FILE_NAME
APP_DIR         = BASE_DIR / "app"
UPLOAD_DIR      = BASE_DIR / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Valid file extensions for replay data
VALID_REPLAY_EXTS = {".json", ".jsonl"}

# ── App Setup ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("kraken_server")

app = Flask(__name__, static_folder=str(APP_DIR))
CORS(app)

# ── Playback State (protected by lock) ────────────────────────────────────────
_lock           = threading.Lock()
_mock_data      = None
_waypoints      = []
_obs_index      = 1        # How many waypoints are visible (1-based)
_paused         = False
_speed          = 1.0      # Multiplier: 0.25x, 0.5x, 1x, 2x, 4x
_last_advance_t = 0.0
# Observation receive timestamps (system clock, not mock data)
_obs_timestamps = {}       # { obs_id: ISO timestamp string }

# ── Live UDP State ────────────────────────────────────────────────────────────
_live_mode      = False
UDP_PORT        = int(os.environ.get("UDP_PORT", 5051))
_live_history   = []
_live_current   = None

# ── Target State (for GCS Dashboard polling) ─────────────────────────────────
_latest_target = None  # Dict: {lat, lon, spread_m, count, timestamp}

def _load_mock():
    global _mock_data, _waypoints, _obs_index, _last_advance_t, _obs_timestamps
    with open(MOCK_DATA_PATH, encoding='utf-8') as f:
        _mock_data = json.load(f)
    _waypoints = _mock_data.get("waypoint_sequence", [])
    _obs_index = 1
    _last_advance_t = time.time()
    _obs_timestamps = {}
    # Stamp the first waypoint immediately
    if _waypoints:
        _obs_timestamps[_waypoints[0]['id']] = _now_iso()
    logger.info(f"Loaded {len(_waypoints)} waypoints from mock data.")

def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

def _advance_waypoint():
    """Advance one step if unpaused and enough time has elapsed."""
    global _obs_index, _last_advance_t
    if _paused or not _waypoints:
        return
    effective_interval = BASE_ADVANCE_S / max(_speed, 0.1)
    now = time.time()
    if now - _last_advance_t >= effective_interval:
        if _obs_index < len(_waypoints):
            _obs_index += 1
            wp = _waypoints[_obs_index - 1]
            _obs_timestamps.setdefault(wp['id'], _now_iso())
            logger.info(f"Advanced to waypoint {_obs_index}/{len(_waypoints)}")
        else:
            _obs_index = 1
            _obs_timestamps.clear()
            _obs_timestamps[_waypoints[0]['id']] = _now_iso()
            logger.info("Sequence complete — looping back to start.")
        _last_advance_t = now

def _build_response():
    if _live_mode:
        return {
            "source":              "udp_stream",
            "frequency_hz":        _mock_data.get("frequency_hz", 462637500) if _mock_data else 462637500,
            "mode":                "live_telemetry",
            "doa_method":          _mock_data.get("doa_method", "MUSIC") if _mock_data else "MUSIC",
            "current_observation": _live_current,
            "observation_history": _live_history,
            "expected_target":     _mock_data.get("expected_target") if _mock_data else None,
            "playback":            None
        }

    if not _waypoints:
        return {
            "source":              "replay",
            "frequency_hz":        462637500,
            "mode":                "replay",
            "doa_method":          "MUSIC",
            "current_observation": None,
            "observation_history": [],
            "expected_target":     None,
            "playback": {"index": 0, "total": 0, "speed": _speed, "paused": _paused},
        }

    visible = _waypoints[:_obs_index]
    # Attach system-clock timestamps to each visible observation
    enriched = []
    for obs in visible:
        enriched.append({
            **obs,
            "received_at": _obs_timestamps.get(obs['id'], _now_iso()),
        })
    current = enriched[-1] if enriched else None
    return {
        "source":              "replay",
        "frequency_hz":        _mock_data.get("frequency_hz", 462637500) if _mock_data else 462637500,
        "mode":                _mock_data.get("mode", "single_mobile_kraken") if _mock_data else "replay",
        "doa_method":          _mock_data.get("doa_method", "MUSIC") if _mock_data else "MUSIC",
        "current_observation": current,
        "observation_history": enriched,
        "expected_target":     _mock_data.get("expected_target") if _mock_data else None,
        "playback": {
            "index":   _obs_index,
            "total":   len(_waypoints),
            "speed":   _speed,
            "paused":  _paused,
        },
    }

# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(str(APP_DIR), "index.html")

@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(str(APP_DIR), filename)

@app.route("/api/bearings", methods=["GET"])
def get_bearings():
    if KRAKEN_API_URL and REQUESTS_AVAILABLE:
        try:
            resp = req_lib.get(f"{KRAKEN_API_URL}/DOA_res", timeout=3)
            resp.raise_for_status()
            return jsonify({"source": "live", "raw": resp.json()})
        except Exception as e:
            logger.warning(f"Live fetch failed ({e}), falling back to mock.")

    with _lock:
        _advance_waypoint()
        return jsonify(_build_response())

@app.route("/api/clear_history", methods=["POST"])
def clear_history():
    with _lock:
        _live_history.clear()
        global _live_current
        _live_current = None
        logger.info("Live history cleared via API")
    return jsonify({"status": "cleared"})

@app.route("/api/playback", methods=["GET"])
def get_playback():
    with _lock:
        return jsonify({
            "index":  _obs_index,
            "total":  len(_waypoints),
            "speed":  _speed,
            "paused": _paused,
            "labels": [wp['label'] for wp in _waypoints],
        })

@app.route("/api/playback", methods=["POST"])
def post_playback():
    global _obs_index, _paused, _speed, _last_advance_t
    body = request.get_json(force=True) or {}
    action = body.get("action", "")

    with _lock:
        if action == "play":
            _paused = False
            _last_advance_t = time.time()
            logger.info("Playback: PLAY")
        elif action == "pause":
            _paused = True
            logger.info("Playback: PAUSE")
        elif action == "forward":
            if _obs_index < len(_waypoints):
                _obs_index += 1
                wp = _waypoints[_obs_index - 1]
                _obs_timestamps.setdefault(wp['id'], _now_iso())
            _last_advance_t = time.time()
            logger.info(f"Playback: FORWARD -> {_obs_index}")
        elif action == "rewind":
            if _obs_index > 1:
                _obs_index -= 1
            _last_advance_t = time.time()
            logger.info(f"Playback: REWIND -> {_obs_index}")
        elif action == "reset":
            _obs_index = 1
            _obs_timestamps.clear()
            _obs_timestamps[_waypoints[0]['id']] = _now_iso()
            _last_advance_t = time.time()
            logger.info("Playback: RESET")
        elif action == "seek":
            val = int(body.get("value", 1))
            _obs_index = max(1, min(val, len(_waypoints)))
            for i in range(_obs_index):
                wp = _waypoints[i]
                _obs_timestamps.setdefault(wp['id'], _now_iso())
            _last_advance_t = time.time()
            logger.info(f"Playback: SEEK -> {_obs_index}")
        elif action == "set_speed":
            val = float(body.get("value", 1.0))
            _speed = max(0.25, min(val, 200.0))
            logger.info(f"Playback: SET SPEED {_speed}x")

        return jsonify(_build_response())

@app.route("/api/health", methods=["GET"])
def health():
    mode = "live" if _live_mode else "replay"
    with _lock:
        return jsonify({
            "status":  "ok",
            "mode":    mode,
            "port":    PORT,
            "index":   _obs_index,
            "total":   len(_waypoints),
        })

# ── Replay Mode API ────────────────────────────────────────────────────────────

@app.route("/api/replay/files", methods=["GET"])
def list_replay_files():
    """List all valid replay files from data/, data/uploads/, and GCS fusion logs."""
    files = []
    # Scan data/ for bearings JSON files
    data_dir = BASE_DIR / "data"
    for f in sorted(data_dir.glob("bearings_*.json")):
        files.append({"name": f.name, "path": str(f.relative_to(BASE_DIR)), "size_kb": round(f.stat().st_size / 1024, 1), "type": "bearings_json"})
    for f in sorted(data_dir.glob("mock_bearings.json")):
        files.append({"name": f.name, "path": str(f.relative_to(BASE_DIR)), "size_kb": round(f.stat().st_size / 1024, 1), "type": "bearings_json"})
    # Scan uploads/
    for f in sorted(UPLOAD_DIR.iterdir()):
        if f.suffix in VALID_REPLAY_EXTS:
            files.append({"name": f.name, "path": str(f.relative_to(BASE_DIR)), "size_kb": round(f.stat().st_size / 1024, 1), "type": "upload"})
    # Scan GCS fusion logs (common location)
    gcs_log_dir = BASE_DIR.parent / "ngcp-uav-software" / "src" / "comms" / "logs" / "fusion_gcs"
    if gcs_log_dir.exists():
        for f in sorted(gcs_log_dir.glob("fusion_gcs_*.jsonl")):
            if f.stat().st_size > 0:  # skip empty logs
                files.append({"name": f.name, "path": str(f), "size_kb": round(f.stat().st_size / 1024, 1), "type": "fusion_gcs_log"})
    # Scan Pi-side fusion logs
    pi_log_dir = BASE_DIR.parent / "ngcp-uav-software" / "logs" / "fusion"
    if pi_log_dir.exists():
        for f in sorted(pi_log_dir.glob("fusion_*.jsonl")):
            if f.stat().st_size > 0:
                files.append({"name": f.name, "path": str(f), "size_kb": round(f.stat().st_size / 1024, 1), "type": "pi_fusion_log"})
    return jsonify({"files": files})

@app.route("/api/replay/upload", methods=["POST"])
def upload_replay_file():
    """Upload a bearings JSON or fusion JSONL file for replay."""
    if 'file' not in request.files:
        return jsonify({"error": "No file in request"}), 400
    f = request.files['file']
    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400
    ext = Path(f.filename).suffix.lower()
    if ext not in VALID_REPLAY_EXTS:
        return jsonify({"error": f"Invalid file type '{ext}'. Accepted: {', '.join(VALID_REPLAY_EXTS)}"}), 400
    dest = UPLOAD_DIR / f.filename
    f.save(str(dest))
    logger.info(f"Uploaded replay file: {dest}")
    return jsonify({"status": "ok", "name": f.filename, "size_kb": round(dest.stat().st_size / 1024, 1)})

def _load_replay_jsonl(path):
    """Load a fusion JSONL log and convert records to waypoint_sequence format."""
    global _mock_data, _waypoints, _obs_index, _last_advance_t, _obs_timestamps
    waypoints = []
    with open(path, encoding='utf-8') as fh:
        for idx, line in enumerate(fh):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Build a waypoint from the fusion record
            wp = {
                "id":          f"replay_{idx:05d}",
                "label":       f"Replay #{idx} | seq={rec.get('kraken_seq', idx)}",
                "lat":         rec.get("lat_deg", 0),
                "lon":         rec.get("lon_deg", 0),
                "bearing_deg": rec.get("doa_deg", 0),
                "confidence":  rec.get("confidence_0_1", 0.5),
            }
            # Carry forward extra telemetry fields for filtering
            for key in ("roll_deg", "pitch_deg", "yaw_deg", "ground_speed_ft_s", "altitude_rel_ft"):
                if key in rec:
                    wp[key] = rec[key]
            waypoints.append(wp)
    _mock_data = {
        "frequency_hz": 462637500,
        "mode": "replay",
        "doa_method": "MUSIC",
        "waypoint_sequence": waypoints,
    }
    _waypoints = waypoints
    _obs_index = 1
    _last_advance_t = time.time()
    _obs_timestamps = {}
    if _waypoints:
        _obs_timestamps[_waypoints[0]['id']] = _now_iso()
    logger.info(f"Loaded {len(_waypoints)} waypoints from JSONL replay: {Path(path).name}")

@app.route("/api/replay/load", methods=["POST"])
def load_replay():
    """Switch to replay mode and load a specific file."""
    global _live_mode, _mock_data, _waypoints, _obs_index, _last_advance_t, _obs_timestamps, _paused, _speed
    body = request.get_json(force=True) or {}
    file_path = body.get("path", "")
    if not file_path:
        return jsonify({"error": "Missing 'path'"}), 400

    # Resolve path: could be relative to BASE_DIR or absolute
    p = Path(file_path)
    if not p.is_absolute():
        p = BASE_DIR / p
    if not p.exists():
        return jsonify({"error": f"File not found: {p}"}), 404
    if p.suffix.lower() not in VALID_REPLAY_EXTS:
        return jsonify({"error": f"Invalid file type"}), 400

    with _lock:
        _live_mode = False
        _paused = True
        _speed = 1.0
        if p.suffix.lower() == '.jsonl':
            _load_replay_jsonl(str(p))
        else:
            _load_mock_from_path(str(p))
    logger.info(f"REPLAY MODE — Loaded {len(_waypoints)} waypoints from {p.name}")
    return jsonify({"status": "ok", "total": len(_waypoints), "filename": p.name})

def _load_mock_from_path(path):
    """Load a bearings JSON file (original format)."""
    global _mock_data, _waypoints, _obs_index, _last_advance_t, _obs_timestamps
    with open(path, encoding='utf-8') as fh:
        _mock_data = json.load(fh)
    _waypoints = _mock_data.get("waypoint_sequence", [])
    _obs_index = 1
    _last_advance_t = time.time()
    _obs_timestamps = {}
    if _waypoints:
        _obs_timestamps[_waypoints[0]['id']] = _now_iso()
    logger.info(f"Loaded {len(_waypoints)} waypoints from JSON: {Path(path).name}")

@app.route("/api/replay/stop", methods=["POST"])
def stop_replay():
    """Switch back to live UDP mode."""
    global _live_mode, _mock_data, _waypoints, _obs_index, _paused
    with _lock:
        _live_mode = True
        _mock_data = None
        _waypoints = []
        _obs_index = 1
        _paused = False
    logger.info("Switched back to LIVE UDP mode.")
    return jsonify({"status": "ok", "mode": "live"})

@app.route("/api/transmit", methods=["POST"])
def transmit():
    """Store target coordinates from UI for GCS Dashboard consumption.

    XBee-only architecture: This endpoint stores the target in memory and
    on disk. The GCS Dashboard polls GET /api/target to retrieve it, then
    relays it to the Pi 5 via XBee PatientLocation command (Command ID 5).
    """
    global _latest_target
    body = request.get_json(force=True) or {}
    lat = body.get("lat")
    lon = body.get("lon")
    spread_m = body.get("spread_m", 0)
    count = body.get("count", 1)

    if lat is None or lon is None:
        return jsonify({"error": "Missing lat/lon"}), 400

    payload = {
        "lat": lat,
        "lon": lon,
        "spread_m": spread_m,
        "count": count,
        "timestamp": time.time()
    }

    # Store in memory for GET /api/target polling
    _latest_target = payload

    # Also persist to disk as a fallback handoff mechanism
    target_file = Path("/tmp/kraken_gcs_target.json") if os.name != 'nt' \
        else Path(os.environ.get("TEMP", "C:/Temp")) / "kraken_gcs_target.json"
    try:
        target_file.parent.mkdir(parents=True, exist_ok=True)
        with open(target_file, "w") as f:
            json.dump(payload, f)
    except Exception as e:
        logger.warning(f"Could not write target file: {e}")

    logger.info(f"Target stored for GCS Dashboard: {lat}, {lon} "
                f"(spread={spread_m:.1f}m, {count} hits)")
    return jsonify({"status": "ok", "message": "Target stored — awaiting GCS Dashboard relay"})


@app.route("/api/target", methods=["GET"])
def get_target():
    """Returns the latest Kraken target coordinates.

    The GCS Dashboard polls this endpoint and, when a new target is detected,
    sends a PatientLocation command (Command ID 5) via XBee to the Pi 5.
    This replaces the old MAVLink upstream path through the RFD-900x.
    """
    if _latest_target:
        return jsonify(_latest_target)
    return jsonify({"lat": None, "lon": None, "spread_m": None,
                    "count": None, "timestamp": None})

# ── Entry Point ────────────────────────────────────────────────────────────────

def _translate_fusion_record(payload):
    """Auto-detect and translate MRA Software Team fusion records to Kraken schema."""
    if "kraken_seq" not in payload:
        return payload

    if not payload.get("usable_for_triangulation", True):
        return None

    seq = payload["kraken_seq"]
    ts_ms = payload.get("t_gcs_rx_ms", int(time.time() * 1000))

    translated = {
        "id":          f"fusion_{seq}",
        "label":       f"Fusion #{seq}",
        "lat":         payload["lat_deg"],
        "lon":         payload["lon_deg"],
        "bearing_deg": payload["doa_deg"],
        "confidence":  payload.get("confidence_0_1", 0.5),
        "received_at": datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat(timespec='seconds'),
        "fusion_meta": {
            "kraken_seq": seq,
            "usable": payload.get("usable_for_triangulation", True),
        },
    }
    return translated

def udp_listener_thread():
    global _live_mode, _live_history, _live_current
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", UDP_PORT))
    logger.info(f"UDP Telemetry Listener bound to 0.0.0.0:{UDP_PORT}")
    while True:
        try:
            data, addr = sock.recvfrom(65535)
            payload = json.loads(data.decode("utf-8"))
            
            # Translate MRA fusion records to Kraken schema
            payload = _translate_fusion_record(payload)
            if payload is None:
                continue
                
            # Ensure it has a system clock stamp
            if 'received_at' not in payload:
                payload['received_at'] = _now_iso()
            with _lock:
                _live_mode = True
                _live_history.append(payload)
                _live_current = payload
        except Exception as e:
            logger.error(f"UDP parse error: {e}")

# NOTE (XBee migration): _mavlink_drain_thread removed.
# MAVLink upstream via RFD-900x is no longer used. Target coordinates
# are relayed by the GCS Dashboard via XBee PatientLocation command.

if __name__ == "__main__":
    _live_mode = True
    logger.info("LIVE UDP MODE FORCED. Mock data disabled.")

    # Spin up the background telemetry listener
    threading.Thread(target=udp_listener_thread, daemon=True).start()

    # XBee-only architecture: no MAVLink upstream connection needed.
    # Target coordinates are served via GET /api/target for the GCS
    # Dashboard to poll and relay via XBee PatientLocation command.
    logger.info("RF Architecture: XBee-only (no RFD-900x / MAVLink upstream)")
    logger.info("Target relay: GET /api/target → GCS Dashboard → XBee → Pi 5")

    if KRAKEN_API_URL:
        logger.info(f"LIVE KRAKEN MODE — Proxying KrakenSDR API at {KRAKEN_API_URL}")
    else:
        logger.info(f"LIVE UDP MODE — Ready for UDP stream on port {UDP_PORT}.")
    logger.info(f"Opening at http://localhost:{PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
