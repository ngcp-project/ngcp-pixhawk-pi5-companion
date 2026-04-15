#!/usr/bin/env python3
"""
kraken_server.py — KrakenSDR Triangulator Server
=====================================================
Live-only telemetry server. Receives bearing observations via UDP
and serves them to the web dashboard.

API:
  GET  /api/bearings           — current observation history
  GET  /api/health             — server health check

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

BASE_DIR        = Path(__file__).resolve().parent.parent
APP_DIR         = BASE_DIR / "app"

# ── App Setup ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("kraken_server")

app = Flask(__name__, static_folder=str(APP_DIR))
CORS(app)

# ── Live UDP State ────────────────────────────────────────────────────────────
_lock           = threading.Lock()
UDP_PORT        = int(os.environ.get("UDP_PORT", 5051))
_live_history   = []
_live_current   = None

def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

def _build_response():
    if _live_history:
        return {
            "source":              "udp_stream",
            "frequency_hz":        462637500,
            "mode":                "live_telemetry",
            "doa_method":          "MUSIC",
            "current_observation": _live_current,
            "observation_history": _live_history,
            "expected_target":     None,
        }

    # No data received yet — return empty waiting state
    return {
        "source":              "waiting",
        "frequency_hz":        462637500,
        "mode":                "live_telemetry",
        "doa_method":          "MUSIC",
        "current_observation": None,
        "observation_history": [],
        "expected_target":     None,
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
            logger.warning(f"Live fetch failed ({e}), waiting for UDP data.")

    with _lock:
        return jsonify(_build_response())

@app.route("/api/health", methods=["GET"])
def health():
    mode = "live" if (_live_history or KRAKEN_API_URL) else "waiting"
    with _lock:
        return jsonify({
            "status":  "ok",
            "mode":    mode,
            "port":    PORT,
            "observations": len(_live_history),
        })

# ── Entry Point ────────────────────────────────────────────────────────────────

def _translate_fusion_record(payload):
    """Auto-detect and translate MRA Software Team fusion records to Kraken schema.

    MRA fusion records (from fusion_receiver.py) use field names like
    lat_deg, lon_deg, doa_deg, confidence_0_1.  The Kraken observation
    pipeline expects lat, lon, bearing_deg, confidence.

    If the payload already uses Kraken-native keys it is returned as-is.
    Returns None if the record should be skipped (usable_for_triangulation=False).
    """
    if "kraken_seq" not in payload:
        return payload   # Already in Kraken-native format

    # Skip records that the fusion pipeline marked as unusable
    if not payload.get("usable_for_triangulation", True):
        logger.debug(f"Skipping non-usable fusion record seq={payload.get('kraken_seq')}")
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
        "received_at": datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
                              .isoformat(timespec='seconds'),
        # Preserve MRA metadata for debugging / downstream consumers
        "fusion_meta": {
            "kraken_seq": seq,
            "usable": payload.get("usable_for_triangulation", True),
        },
    }
    logger.info(f"Translated fusion record seq={seq}: "
                f"({translated['lat']:.6f}, {translated['lon']:.6f}) "
                f"bearing={translated['bearing_deg']:.1f}° "
                f"conf={translated['confidence']:.2f}")
    return translated


def udp_listener_thread():
    global _live_history, _live_current
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", UDP_PORT))
    logger.info(f"UDP Telemetry Listener bound to 0.0.0.0:{UDP_PORT}")
    while True:
        try:
            data, addr = sock.recvfrom(65535)
            payload = json.loads(data.decode("utf-8"))

            # Translate MRA fusion records to Kraken schema (no-op for native)
            payload = _translate_fusion_record(payload)
            if payload is None:
                continue  # Record was non-usable, skip it

            # Ensure it has a system clock stamp
            if 'received_at' not in payload:
                payload['received_at'] = _now_iso()
            with _lock:
                _live_history.append(payload)
                _live_current = payload
        except Exception as e:
            logger.error(f"UDP parse error: {e}")

if __name__ == "__main__":
    # Spin up the background telemetry listener
    threading.Thread(target=udp_listener_thread, daemon=True).start()

    if KRAKEN_API_URL:
        logger.info(f"LIVE KRAKEN MODE — Proxying KrakenSDR API at {KRAKEN_API_URL}")
    else:
        logger.info(f"LIVE MODE — Waiting for UDP telemetry on port {UDP_PORT}")
    logger.info(f"Opening at http://localhost:{PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
