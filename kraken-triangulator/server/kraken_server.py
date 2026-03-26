#!/usr/bin/env python3
"""
kraken_server.py — KrakenSDR Triangulator Dev Server
=====================================================
Single mobile KrakenSDR model with playback controls.

Playback API:
  GET  /api/bearings           — current observation history
  GET  /api/playback           — playback state (index, total, speed, paused)
  POST /api/playback           — send playback command (JSON body)
    { "action": "play" | "pause" | "forward" | "rewind" | "reset" | "seek" | "set_speed",
      "value": <int or float>  }   # value used by seek (waypoint index) and set_speed

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

# ── Configuration ──────────────────────────────────────────────────────────────
PORT            = int(os.environ.get("PORT", 5050))
KRAKEN_API_URL  = os.environ.get("KRAKEN_API_URL", "")
BASE_ADVANCE_S  = float(os.environ.get("ADVANCE_EVERY_S", "0.5"))

BASE_DIR        = Path(__file__).resolve().parent.parent
MOCK_FILE_NAME  = os.environ.get("BEARINGS_FILE", "bearings_20260313_154333.json")
MOCK_DATA_PATH  = BASE_DIR / "data" / MOCK_FILE_NAME
APP_DIR         = BASE_DIR / "app"

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
    if _paused:
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
        "source":              "mock",
        "frequency_hz":        _mock_data.get("frequency_hz", 462637500),
        "mode":                _mock_data.get("mode", "single_mobile_kraken"),
        "doa_method":          _mock_data.get("doa_method", "MUSIC"),
        "current_observation": current,
        "observation_history": enriched,
        "expected_target":     _mock_data.get("expected_target"),
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
    mode = "live" if KRAKEN_API_URL else "mock"
    with _lock:
        return jsonify({
            "status":  "ok",
            "mode":    mode,
            "port":    PORT,
            "index":   _obs_index,
            "total":   len(_waypoints),
        })

# ── Entry Point ────────────────────────────────────────────────────────────────

def udp_listener_thread():
    global _live_mode, _live_history, _live_current
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", UDP_PORT))
    logger.info(f"UDP Telemetry Listener bound to 0.0.0.0:{UDP_PORT}")
    while True:
        try:
            data, addr = sock.recvfrom(65535)
            payload = json.loads(data.decode("utf-8"))
            # Ensure it has a system clock stamp
            if 'received_at' not in payload:
                payload['received_at'] = _now_iso()
            with _lock:
                _live_mode = True
                _live_history.append(payload)
                _live_current = payload
        except Exception as e:
            logger.error(f"UDP parse error: {e}")

if __name__ == "__main__":
    _load_mock()
    
    # Spin up the background telemetry listener
    threading.Thread(target=udp_listener_thread, daemon=True).start()

    if KRAKEN_API_URL:
        logger.info(f"LIVE KRAKEN MODE — Proxying KrakenSDR API at {KRAKEN_API_URL}")
    else:
        logger.info(f"MOCK/UDP MODE — Ready for UDP stream on port {UDP_PORT} or falling back to {len(_waypoints)} waypoints.")
    logger.info(f"Opening at http://localhost:{PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
